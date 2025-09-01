"""
Data loader for PeerDAS Analysis V2 - Head correctness analysis.

This module loads head correctness data by analyzing whether attestations
voted for the correct block_root, with support for filtering by proposer
and attester characteristics.
"""

import pandas as pd
import polars as pl
import streamlit as st
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import logging
import yaml
import os

from shared.database import get_database_connection
from shared.network_spec import get_network_spec
from queries import (
    get_eligible_slots_query,
    get_committee_assignments_query,
    get_head_correctness_attestations_query,
    get_blob_counts_query,
    get_node_classification_query,
    get_proposer_blocks_query,
    build_proposer_filter,
    build_validator_filter
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_network_mapping(network: str) -> Dict[str, Any]:
    """
    Load network mapping from YAML files.
    
    Args:
        network: Network name
        
    Returns:
        Dictionary with node configurations
    """
    network_file = f"networks/{network}.yaml"
    if not os.path.exists(network_file):
        logger.warning(f"Network file {network_file} not found")
        return {}
    
    try:
        with open(network_file, 'r') as f:
            data = yaml.safe_load(f)
            return data.get('nodes', {})
    except Exception as e:
        logger.error(f"Error loading network mapping: {e}")
        return {}


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def get_node_classifications(network: str, cluster_name: Optional[str] = None) -> pd.DataFrame:
    """
    Get node classifications from the network mapping.
    
    Returns a DataFrame with node names and their classifications.
    """
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return pd.DataFrame()
    
    # Get classifications from database
    query = get_node_classification_query()
    params = {
        'network': network,
        'start_date': datetime.now().replace(hour=0, minute=0, second=0),
        'end_date': datetime.now()
    }
    
    try:
        df = pd.read_sql(query, conn, params=params)
        
        # Enhance with network mapping if available
        network_mapping = load_network_mapping(network)
        if network_mapping:
            # Map node configurations
            node_types = {}
            cl_implementations = {}
            el_implementations = {}
            
            for node_name, node_config in network_mapping.items():
                tags = node_config.get('tags', [])
                
                # Determine node type
                if 'supernode' in tags:
                    node_types[node_name] = 'supernode'
                else:
                    node_types[node_name] = 'regular'
                
                # Extract CL and EL from tags
                for tag in tags:
                    if tag.startswith('cl:'):
                        cl_implementations[node_name] = tag.split(':')[1]
                    elif tag.startswith('el:'):
                        el_implementations[node_name] = tag.split(':')[1]
            
            # Update DataFrame with mapping
            df['node_type_mapped'] = df['client_name'].map(node_types).fillna(df['node_type'])
            df['cl_mapped'] = df['client_name'].map(cl_implementations).fillna(df['cl_implementation'])
            df['el_mapped'] = df['client_name'].map(el_implementations).fillna(df['el_implementation'])
            
            # Use mapped values
            df['node_type'] = df['node_type_mapped']
            df['cl_implementation'] = df['cl_mapped']
            df['el_implementation'] = df['el_mapped']
            df = df.drop(columns=['node_type_mapped', 'cl_mapped', 'el_mapped'])
        
        return df
    except Exception as e:
        logger.error(f"Error getting node classifications: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_eligible_slots(
    network: str,
    start_date: datetime,
    end_date: datetime,
    proposer_type: Optional[str] = None,
    cl_filter: Optional[List[str]] = None,
    el_filter: Optional[List[str]] = None,
    cluster_name: Optional[str] = None
) -> Tuple[List[int], Dict[int, str]]:
    """
    Load eligible slots based on proposer filtering.
    
    Returns:
        Tuple of (slot_list, slot_to_block_root_mapping)
    """
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return [], {}
    
    # Get network spec for filtering
    network_spec = get_network_spec(network)
    proposer_indices = []
    
    if network_spec and (proposer_type or cl_filter or el_filter):
        # Filter by validator indices based on node characteristics
        for node_name in network_spec.get_all_nodes():
            node_info = network_spec.get_node_info(node_name)
            if not node_info:
                continue
                
            # Check if node matches filters
            tags = node_info.get('tags', [])
            node_is_supernode = 'supernode' in tags
            
            # Check node type filter
            if proposer_type:
                if proposer_type == 'supernode' and not node_is_supernode:
                    continue
                if proposer_type == 'regular' and node_is_supernode:
                    continue
            
            # Check CL filter
            if cl_filter:
                node_cl = None
                for tag in tags:
                    if tag.startswith('cl:'):
                        node_cl = tag.split(':')[1]
                        break
                if not node_cl or node_cl not in cl_filter:
                    continue
            
            # Check EL filter
            if el_filter:
                node_el = None
                for tag in tags:
                    if tag.startswith('el:'):
                        node_el = tag.split(':')[1]
                        break
                if not node_el or node_el not in el_filter:
                    continue
            
            # Add validator indices for this node
            validators = network_spec.get_validators(node_name)
            proposer_indices.extend(validators)
        
        logger.info(f"Found {len(proposer_indices)} validator indices matching proposer filters")
    
    # Build proposer filter
    proposer_filter = build_proposer_filter(proposer_indices)
    
    # Get query with filter
    query = get_eligible_slots_query().format(proposer_filter=proposer_filter)
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date
    }
    
    try:
        df = pd.read_sql(query, conn, params=params)
        logger.info(f"Eligible slots query returned {len(df)} rows")
        if df.empty:
            return [], {}
        
        slots = df['slot'].tolist()
        slot_to_block = dict(zip(df['slot'], df['block_root']))
        
        logger.info(f"Found {len(slots)} eligible slots with proposer filters")
        return slots, slot_to_block
    except Exception as e:
        logger.error(f"Error loading eligible slots: {e}")
        return [], {}


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_head_correctness_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    eligible_slots: List[int],
    slot_to_block: Dict[int, str],
    attester_type: Optional[str] = None,
    cl_filter: Optional[List[str]] = None,
    el_filter: Optional[List[str]] = None,
    cluster_name: Optional[str] = None
) -> pd.DataFrame:
    """
    Load head correctness data by analyzing attestations against canonical blocks.
    
    For each slot:
    1. Get total validators scheduled to attest (from committee assignments)
    2. Get attestations that voted for correct block_root
    3. Calculate head correctness percentage
    
    Args:
        network: Network name
        start_date: Start of analysis period
        end_date: End of analysis period
        eligible_slots: List of slots to analyze
        slot_to_block: Mapping of slot to canonical block_root
        attester_type: Filter by attester node type
        cl_filter: Filter by CL implementations
        el_filter: Filter by EL implementations
        cluster_name: Optional cluster name
        
    Returns:
        DataFrame with head correctness data by slot
    """
    if not eligible_slots:
        return pd.DataFrame()
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return pd.DataFrame()
    
    # Get network spec for validator mapping
    network_spec = get_network_spec(network)
    
    # Format the slots list directly into the query for ClickHouse IN clause
    slots_str = '(' + ','.join(str(s) for s in eligible_slots) + ')'
    
    # Filter validators if network spec is available
    validator_indices = []
    if network_spec and (attester_type or cl_filter or el_filter):
        for node_name in network_spec.get_all_nodes():
            node_info = network_spec.get_node_info(node_name)
            if not node_info:
                continue
                
            # Check if node matches filters
            tags = node_info.get('tags', [])
            node_is_supernode = 'supernode' in tags
            
            # Check node type filter
            if attester_type:
                if attester_type == 'supernode' and not node_is_supernode:
                    continue
                if attester_type == 'regular' and node_is_supernode:
                    continue
            
            # Check CL filter
            if cl_filter:
                node_cl = None
                for tag in tags:
                    if tag.startswith('cl:'):
                        node_cl = tag.split(':')[1]
                        break
                if not node_cl or node_cl not in cl_filter:
                    continue
            
            # Check EL filter
            if el_filter:
                node_el = None
                for tag in tags:
                    if tag.startswith('el:'):
                        node_el = tag.split(':')[1]
                        break
                if not node_el or node_el not in el_filter:
                    continue
            
            # Add validator indices for this node
            validators = network_spec.get_validators(node_name)
            validator_indices.extend(validators)
    
    try:
        logger.info(f"Loading head correctness data for {len(eligible_slots)} slots")
        
        # Step 1: Get committee assignments (total validators scheduled to attest)
        committee_query = get_committee_assignments_query().replace('%(eligible_slots)s', slots_str)
        committee_params = {
            'network': network,
            'start_date': start_date,
            'end_date': end_date
        }
        
        committee_df = pd.read_sql(committee_query, conn, params=committee_params)
        logger.info(f"Committee assignments query returned {len(committee_df)} validator assignments")
        
        # Check if committee data exists
        if committee_df.empty:
            error_msg = (f"No committee data found for network '{network}' in time range "
                        f"{start_date} to {end_date}. Committee data is required to calculate "
                        f"head correctness percentages. Check both canonical_beacon_committee and "
                        f"beacon_api_eth_v1_beacon_committee tables.")
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Step 2: Get attestations with head vote information
        validator_filter = build_validator_filter(validator_indices)
        attestations_query = get_head_correctness_attestations_query().format(validator_filter=validator_filter)
        attestations_query = attestations_query.replace('%(eligible_slots)s', slots_str)
        
        attestations_df = pd.read_sql(attestations_query, conn, params=committee_params)
        logger.info(f"Head correctness attestations query returned {len(attestations_df)} attestations")
        
        # Step 3: Get blob counts for slots
        blob_query = get_blob_counts_query().replace('%(eligible_slots)s', slots_str)
        blob_df = pd.read_sql(blob_query, conn, params=committee_params)
        logger.info(f"Blob counts query returned {len(blob_df)} slot blob counts")
        
        # Step 4: Calculate head correctness for each slot
        results = []
        
        for slot in eligible_slots:
            canonical_block_root = slot_to_block.get(slot)
            if not canonical_block_root:
                continue
            
            # Get total validators for this slot
            slot_committee = committee_df[committee_df['slot'] == slot]
            if slot_committee.empty:
                logger.warning(f"No committee data for slot {slot}, skipping")
                continue
            
            total_validators = len(slot_committee)
            
            # Get attestations for this slot
            slot_attestations = attestations_df[attestations_df['slot'] == slot]
            
            # Count correct head votes (attestations that match canonical block_root)
            correct_votes = len(slot_attestations[slot_attestations['beacon_block_root'] == canonical_block_root])
            
            # Count total attestations for this slot
            total_attestations = len(slot_attestations)
            
            # Calculate head correctness percentage
            head_correctness_pct = (correct_votes / total_validators * 100) if total_validators > 0 else 0
            
            # Get blob count for this slot
            slot_blob = blob_df[blob_df['slot'] == slot]
            
            # Only include slots with blob data for PeerDAS analysis
            # If there's no data_column_sidecar data, skip this slot
            if slot_blob.empty:
                logger.debug(f"No blob data for slot {slot}, skipping")
                continue
            
            blob_count = slot_blob['blob_count'].iloc[0]
            
            results.append({
                'slot': slot,
                'total_validators_assigned': total_validators,
                'total_attestations': total_attestations,
                'correct_head_votes': correct_votes,
                'head_correctness_pct': head_correctness_pct,
                'blob_count': blob_count,
                'canonical_block_root': canonical_block_root
            })
        
        if not results:
            logger.warning("No head correctness data calculated - possible causes:")
            logger.warning("1. No data_column_sidecar data available for selected slots")
            logger.warning("2. No committee data available for selected slots")
            logger.warning("3. No matching attestation data found")
            return pd.DataFrame()
        
        result_df = pd.DataFrame(results)
        
        # Add validator node information if network spec is available
        if network_spec:
            # For head correctness analysis, we aggregate by slot rather than individual validators
            # But we can add metadata about which node types were involved
            def get_slot_validator_distribution(slot_val):
                """Get distribution of validator node types for a slot."""
                slot_committee = committee_df[committee_df['slot'] == slot_val]
                if slot_committee.empty:
                    return pd.Series({
                        'supernode_validators': 0,
                        'regular_validators': 0,
                        'unknown_validators': 0
                    })
                
                supernode_count = 0
                regular_count = 0
                unknown_count = 0
                
                for validator_idx in slot_committee['validator_index']:
                    node_name = network_spec.get_validator_node(int(validator_idx))
                    if node_name:
                        node_info = network_spec.get_node_info(node_name)
                        if node_info and 'supernode' in node_info.get('tags', []):
                            supernode_count += 1
                        else:
                            regular_count += 1
                    else:
                        unknown_count += 1
                
                return pd.Series({
                    'supernode_validators': supernode_count,
                    'regular_validators': regular_count,
                    'unknown_validators': unknown_count
                })
            
            # Apply validator distribution to dataframe
            validator_dist = result_df['slot'].apply(get_slot_validator_distribution)
            result_df = pd.concat([result_df, validator_dist], axis=1)
        
        logger.info(f"Calculated head correctness for {len(result_df)} slots")
        return result_df
        
    except Exception as e:
        logger.error(f"Error loading head correctness data: {e}")
        return pd.DataFrame()



def validate_data_availability(
    network: str,
    start_date: datetime,
    end_date: datetime,
    cluster_name: Optional[str] = None
) -> Dict[str, bool]:
    """
    Check which data sources are available for the given time range.
    
    Returns:
        Dictionary indicating availability of each data source
    """
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return {}
    
    availability = {}
    
    # Check beacon API attestations
    try:
        query = """
        SELECT COUNT(*) as count
        FROM beacon_api_eth_v1_events_attestation
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        LIMIT 1
        """
        result = pd.read_sql(query, conn, params={'network': network, 'start_date': start_date, 'end_date': end_date})
        availability['beacon_api'] = result['count'].iloc[0] > 0 if not result.empty else False
    except Exception as e:
        logger.warning(f"Failed to check beacon_api availability: {e}")
        availability['beacon_api'] = False
    
    # Check libp2p attestations
    try:
        query = """
        SELECT COUNT(*) as count
        FROM libp2p_gossipsub_beacon_attestation
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        LIMIT 1
        """
        result = pd.read_sql(query, conn, params={'network': network, 'start_date': start_date, 'end_date': end_date})
        availability['libp2p_gossipsub'] = result['count'].iloc[0] > 0 if not result.empty else False
    except Exception as e:
        logger.warning(f"Failed to check libp2p_gossipsub availability: {e}")
        availability['libp2p_gossipsub'] = False
    
    # Check message delivery
    try:
        query = """
        SELECT COUNT(*) as count
        FROM libp2p_deliver_message
        WHERE meta_network_name = %(network)s
            AND event_date_time BETWEEN %(start_date)s AND %(end_date)s
        LIMIT 1
        """
        result = pd.read_sql(query, conn, params={'network': network, 'start_date': start_date, 'end_date': end_date})
        availability['message_delivery'] = result['count'].iloc[0] > 0 if not result.empty else False
    except Exception as e:
        logger.warning(f"Failed to check message_delivery availability: {e}")
        availability['message_delivery'] = False
    
    return availability


def get_unique_clients(
    network: str,
    start_date: datetime,
    end_date: datetime,
    cluster_name: Optional[str] = None
) -> List[str]:
    """
    Get list of unique client implementations from the network spec.
    
    Returns:
        List of client names (CL and EL implementations)
    """
    # Get network spec for this network
    network_spec = get_network_spec(network)
    
    if network_spec:
        # Get all unique CL and EL implementations from the network spec
        cl_implementations = set()
        el_implementations = set()
        
        for node_name in network_spec.get_all_nodes():
            node_clients = network_spec.get_node_clients(node_name)
            if node_clients['cl']:
                cl_implementations.add(node_clients['cl'])
            if node_clients['el']:
                el_implementations.add(node_clients['el'])
        
        # Return a list of unique implementations
        # Format as "cl-el" for compatibility with existing code
        client_combinations = []
        for cl in cl_implementations:
            for el in el_implementations:
                client_combinations.append(f"{cl}-{el}")
        
        return sorted(client_combinations)
    else:
        # Fallback to querying the database if no network spec
        conn = get_database_connection(cluster_name)
        if not conn:
            logger.error(f"Failed to get database connection for cluster: {cluster_name}")
            return []
        
        query = """
        SELECT DISTINCT meta_client_name as client_name
        FROM beacon_api_eth_v1_events_attestation
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND meta_client_name != ''
        ORDER BY client_name
        """
        
        try:
            df = pd.read_sql(query, conn, params={'network': network, 'start_date': start_date, 'end_date': end_date})
            return df['client_name'].tolist() if not df.empty else []
        except Exception as e:
            logger.error(f"Error getting unique clients: {e}")
            return []