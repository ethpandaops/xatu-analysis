"""
Data loader for PeerDAS Analysis V2 - Head correctness analysis.

This module loads head correctness data by analyzing whether attestations
voted for the proposed block_root (including blocks that may have been reorged),
with support for filtering by proposer and attester characteristics.
"""

import pandas as pd
import polars as pl
import streamlit as st
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import logging
import yaml
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from shared.database import get_database_connection
from shared.network_spec import get_network_spec
from queries import (
    get_eligible_slots_query,
    build_proposer_filter,
    build_validator_filter,
    get_head_correctness_per_slot_query,
    get_head_correctness_per_slot_grouped_query
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
    Get node classifications from the network YAML file.
    
    Returns a DataFrame with node names and their classifications.
    """
    # Load network mapping from YAML
    network_mapping = load_network_mapping(network)
    if not network_mapping:
        logger.error(f"No network mapping found for network: {network}")
        return pd.DataFrame()
    
    try:
        # Build classifications from YAML
        classifications = []
        
        for node_name, node_config in network_mapping.items():
            tags = node_config.get('tags', [])
            groups = node_config.get('groups', [])
            attributes = node_config.get('attributes', {})
            
            # Determine node type
            node_type = 'regular'
            if 'bootnode' in groups:
                node_type = 'bootnode'
            elif 'supernode' in tags or attributes.get('supernode', False):
                node_type = 'supernode'
            
            # Extract CL and EL from tags
            cl_implementation = None
            el_implementation = None
            
            for tag in tags:
                if tag.startswith('cl:'):
                    cl_implementation = tag.split(':')[1]
                elif tag.startswith('el:'):
                    el_implementation = tag.split(':')[1]
            
            classifications.append({
                'client_name': node_name,
                'node_type': node_type,
                'cl_implementation': cl_implementation,
                'el_implementation': el_implementation
            })
        
        df = pd.DataFrame(classifications)
        return df
        
    except Exception as e:
        logger.error(f"Error getting node classifications from YAML: {e}")
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
) -> Tuple[List[int], Dict[int, str], Dict[int, int]]:
    """
    Load eligible slots based on proposer filtering.
    
    Returns:
        Tuple of (slot_list, slot_to_block_root_mapping, slot_to_proposer_index_mapping)
    """
    logger.info(f"Loading eligible slots for network={network}")
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return [], {}
    
    # Get network spec for filtering
    network_spec = get_network_spec(network)
    
    proposer_indices = []
    
    # Check for filters that require network spec
    has_filters = proposer_type or cl_filter or el_filter
    
    if not network_spec and has_filters:
        logger.warning(f"Network spec not found for {network} but filters requested - ignoring filters")
    
    # If we have a network spec, ALWAYS filter to only validators in the spec
    # This prevents "unknown" entries from validators not in our config
    if network_spec:
        # Filter by validator indices based on node characteristics
        nodes_processed = 0
        nodes_matched = 0
        for node_name in network_spec.get_all_nodes():
            nodes_processed += 1
            node_info = network_spec.get_node_info(node_name)
            if not node_info:
                continue
            
            # If no filters, include all nodes from the spec
            if not has_filters:
                validators = network_spec.get_validators(node_name)
                proposer_indices.extend(validators)
                nodes_matched += 1
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
            nodes_matched += 1
        
        logger.info(f"Proposer filter: processed {nodes_processed} nodes, matched {nodes_matched}, total validators: {len(proposer_indices)}")
    
    # Build proposer filter
    proposer_filter = build_proposer_filter(proposer_indices)
    
    # Get query with filter (do NOT restrict to sidecars; 0-blob slots are valid)
    query = get_eligible_slots_query().format(proposer_filter=proposer_filter)
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date
    }
    
    try:
        df = pd.read_sql(query, conn, params=params)
        if df.empty:
            logger.warning(f"No slots found in database for network {network}")
            return [], {}, {}
        
        slots = df['slot'].tolist()
        slot_to_block = dict(zip(df['slot'], df['block_root']))
        slot_to_proposer = dict(zip(df['slot'], df['proposer_index']))
        
        logger.info(f"Found {len(slots)} eligible slots")
        return slots, slot_to_block, slot_to_proposer
    except Exception as e:
        logger.error(f"Error loading eligible slots: {e}")
        return [], {}, {}


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def _build_attester_map_union_selects(network_spec, attester_type: Optional[str], cl_filter: Optional[List[str]], el_filter: Optional[List[str]]) -> str:
    """Build UNION ALL SELECT mapping for validator->group using network_spec ranges."""
    logger.info(f"Building attester map: attester_type={attester_type}, cl_filter={cl_filter}, el_filter={el_filter}")
    
    selects = []
    if not network_spec:
        logger.error("No network_spec provided to _build_attester_map_union_selects")
        return ""

    nodes_processed = 0
    nodes_included = 0
    
    for node_name in network_spec.get_all_nodes():
        nodes_processed += 1
        node_info = network_spec.get_node_info(node_name) or {}
        v_range = network_spec.get_validator_range(node_name)
        
        if not v_range:
            logger.debug(f"Node {node_name} has no validator range, skipping")
            continue
        start, end = v_range

        tags = network_spec.get_node_tags(node_name) or []
        node_is_supernode = 'supernode' in tags or node_info.get('attributes', {}).get('supernode', False)

        # Apply attester-type filter
        if attester_type == 'supernode' and not node_is_supernode:
            continue
        if attester_type == 'regular' and node_is_supernode:
            continue

        # Extract clients from tags
        cl = ''
        el = ''
        cl_tags = []
        el_tags = []
        
        for tag in tags:
            if tag.startswith('cl:'):
                parts = tag.split(':')
                if len(parts) == 2 and parts[1]:
                    cl_tags.append(parts[1])
                else:
                    logger.error(f"Node {node_name} has malformed CL tag: '{tag}'")
            elif tag.startswith('el:'):
                parts = tag.split(':')
                if len(parts) == 2 and parts[1]:
                    el_tags.append(parts[1])
                else:
                    logger.error(f"Node {node_name} has malformed EL tag: '{tag}'")
        
        cl = cl_tags[0] if cl_tags else ''
        el = el_tags[0] if el_tags else ''

        # Validate client info when filtering is required
        if cl_filter or el_filter:
            if cl_filter and not cl:
                logger.error(f"Node {node_name} has no CL client information but CL filter is applied! Available tags: {tags}")
                raise ValueError(f"Missing CL client info for node {node_name} when CL filtering is required")
            
            if el_filter and not el:
                logger.error(f"Node {node_name} has no EL client information but EL filter is applied! Available tags: {tags}")
                raise ValueError(f"Missing EL client info for node {node_name} when EL filtering is required")

        # Apply client filters if provided
        if cl_filter and cl not in cl_filter:
            continue
        if el_filter and el not in el_filter:
            continue

        node_type = 'supernode' if node_is_supernode else 'regular'
        select_sql = f"SELECT arrayJoin(range({int(start)},{int(end)})) AS validator_index, '{node_type}' AS node_type, '{cl}' AS cl_client, '{el}' AS el_client"
        selects.append(select_sql)
        nodes_included += 1
        
        # Debug: Log nodes that don't have clear supernode determination
        if not node_is_supernode and 'supernode' not in tags and not node_info.get('attributes', {}).get('supernode', False):
            logger.debug(f"DEBUG: Node {node_name} classified as 'regular' - tags: {tags}, supernode attr: {node_info.get('attributes', {}).get('supernode')}")

    logger.info(f"Processed {nodes_processed} nodes, included {nodes_included} in attester map")
    
    result = "\nUNION ALL\n".join(selects)
    return result


def _build_proposer_map_union_selects(network_spec, eligible_slots: List[int], slot_to_proposer: Dict[int, int] = None) -> str:
    """Build UNION ALL SELECT mapping for slot->proposer characteristics using network_spec."""
    logger.info(f"Building proposer map for {len(eligible_slots)} eligible slots")
    
    if not eligible_slots:
        logger.error("No eligible_slots provided")
        return ""
    
    # If no network spec, return empty - NO FALLBACKS
    if not network_spec:
        logger.error("No network spec available - cannot build proposer map")
        return ""
    
    # Build validator_index -> node mapping from network spec (cached)
    if not hasattr(_build_proposer_map_union_selects, '_validator_to_node_cache'):
        validator_to_node = {}
        for node_name in network_spec.get_all_nodes():
            v_range = network_spec.get_validator_range(node_name)
            if v_range:
                start, end = v_range
                for validator_index in range(int(start), int(end)):
                    validator_to_node[validator_index] = node_name
        _build_proposer_map_union_selects._validator_to_node_cache = validator_to_node
    
    validator_to_node = _build_proposer_map_union_selects._validator_to_node_cache
    
    selects = []
    validator_indices = list(validator_to_node.keys())
    if not validator_indices:
        logger.error("No validator indices found in network spec")
        return ""
    
    for slot in eligible_slots:
        # Get actual proposer index from database - NEVER use approximations
        if not slot_to_proposer or slot not in slot_to_proposer:
            logger.warning(f"Missing proposer index for slot {slot} - marking as unknown")
            select_sql = f"SELECT {slot} AS slot, 'unknown' AS node_type, 'unknown' AS cl_client, 'unknown' AS el_client"
            selects.append(select_sql)
            continue
            
        proposer_index = slot_to_proposer[slot]
        
        # If proposer not in our validator mapping, mark as unknown
        if proposer_index not in validator_to_node:
            logger.debug(f"Proposer {proposer_index} for slot {slot} not in network spec - marking as unknown")
            select_sql = f"SELECT {slot} AS slot, 'unknown' AS node_type, 'unknown' AS cl_client, 'unknown' AS el_client"
            selects.append(select_sql)
            continue
            
        node_name = validator_to_node[proposer_index]
        
        # Get node characteristics (cached per node)
        cache_key = f"node_chars_{node_name}"
        if not hasattr(_build_proposer_map_union_selects, cache_key):
            node_info = network_spec.get_node_info(node_name) or {}
            tags = network_spec.get_node_tags(node_name) or []
            node_is_supernode = 'supernode' in tags or node_info.get('attributes', {}).get('supernode', False)
            
            # Extract clients from tags
            cl = ''
            el = ''
            for tag in tags:
                if tag.startswith('cl:') and len(tag.split(':')) == 2:
                    cl = tag.split(':')[1]
                elif tag.startswith('el:') and len(tag.split(':')) == 2:
                    el = tag.split(':')[1]
            
            node_type = 'supernode' if node_is_supernode else 'regular'
            setattr(_build_proposer_map_union_selects, cache_key, (node_type, cl, el))
        
        node_type, cl, el = getattr(_build_proposer_map_union_selects, cache_key)
        
        # Build SELECT for this slot
        select_sql = f"SELECT {slot} AS slot, '{node_type}' AS node_type, '{cl}' AS cl_client, '{el}' AS el_client"
        selects.append(select_sql)
    
    logger.info(f"Built proposer map for {len(selects)} slots")
    result = "\nUNION ALL\n".join(selects)
    return result


def _build_group_index_map(
    network_spec,
    grouping_dimension: str,
    attester_type: Optional[str],
    cl_filter: Optional[List[str]],
    el_filter: Optional[List[str]]
) -> Dict[str, List[int]]:
    """Build a mapping of group_key -> validator indices using network_spec."""
    groups: Dict[str, List[int]] = {}
    if not network_spec:
        return groups

    for node_name in network_spec.get_all_nodes():
        node_info = network_spec.get_node_info(node_name) or {}
        v_range = network_spec.get_validator_range(node_name)
        if not v_range:
            continue
        start, end = v_range
        tags = network_spec.get_node_tags(node_name) or []
        node_is_supernode = 'supernode' in tags or node_info.get('attributes', {}).get('supernode', False)
        clients = network_spec.get_node_clients(node_name)
        cl = clients.get('cl') or ''
        el = clients.get('el') or ''

        # Apply filters
        if attester_type == 'supernode' and not node_is_supernode:
            continue
        if attester_type == 'regular' and node_is_supernode:
            continue
        if cl_filter and cl not in cl_filter:
            continue
        if el_filter and el not in el_filter:
            continue

        if grouping_dimension == 'node_type':
            key = 'supernode' if node_is_supernode else 'regular'
        elif grouping_dimension == 'cl_client':
            if not cl:
                continue
            key = cl
        elif grouping_dimension == 'el_client':
            if not el:
                continue
            key = el
        elif grouping_dimension == 'cl_el_combined':
            if not cl or not el:
                continue
            key = f"{cl}-{el}"
        elif grouping_dimension == 'cl_node_type':
            if not cl:
                continue
            node_type = 'supernode' if node_is_supernode else 'regular'
            key = f"{cl}-{node_type}"
        else:
            key = 'all'

        groups.setdefault(key, []).extend(range(int(start), int(end)))

    return groups


def load_head_correctness_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    eligible_slots: List[int],
    slot_to_block: Dict[int, str],
    slot_to_proposer: Dict[int, int] = None,
    attester_type: Optional[str] = None,
    cl_filter: Optional[List[str]] = None,
    el_filter: Optional[List[str]] = None,
    grouping_dimension: Optional[str] = None,
    cluster_name: Optional[str] = None
) -> pd.DataFrame:
    """
    Load head correctness data by analyzing attestations against proposed blocks.
    
    For each slot:
    1. Get total validators scheduled to attest (from committee assignments)
    2. Get attestations that voted for the proposed block_root (including reorged blocks)
    3. Calculate head correctness percentage
    
    Args:
        network: Network name
        start_date: Start of analysis period
        end_date: End of analysis period
        eligible_slots: List of slots to analyze
        slot_to_block: Mapping of slot to proposed block_root
        slot_to_proposer: Mapping of slot to proposer_index
        attester_type: Filter by attester node type
        cl_filter: Filter by CL implementations
        el_filter: Filter by EL implementations
        grouping_dimension: Optional grouping dimension
        cluster_name: Optional cluster name
        
    Returns:
        DataFrame with head correctness data by slot
    """
    logger.info(f"Loading head correctness data for {network}, {len(eligible_slots)} slots")
    
    
    if not eligible_slots:
        logger.warning("No eligible slots provided")
        return pd.DataFrame()
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return pd.DataFrame()
    
    # Get network spec for validator mapping
    network_spec = get_network_spec(network)
    logger.info(f"Network spec loaded: {network_spec is not None}, nodes: {len(network_spec.get_all_nodes()) if network_spec else 0}")
    
    
    # Format the slots list directly into the query for ClickHouse IN clause
    slots_str = '(' + ','.join(str(s) for s in eligible_slots) + ')'
    
    # Filter validators if network spec is available
    # If we have a network spec, ALWAYS filter to only validators in the spec
    validator_indices = []
    has_attester_filters = attester_type or cl_filter or el_filter
    
    if network_spec:
        for node_name in network_spec.get_all_nodes():
            node_info = network_spec.get_node_info(node_name)
            if not node_info:
                continue
            
            # If no filters, include all nodes from the spec
            if not has_attester_filters:
                validators = network_spec.get_validators(node_name)
                validator_indices.extend(validators)
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
        
        logger.info(f"Attester filter: total validators: {len(validator_indices)}")
    
    # Check if committee data exists FIRST - REQUIRED for accurate head correctness
    committee_check_sql = """
    SELECT 
        (SELECT COUNT(*) FROM canonical_beacon_committee 
         WHERE meta_network_name = %(network)s 
           AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
         LIMIT 1) as canonical_count,
        (SELECT COUNT(*) FROM beacon_api_eth_v1_beacon_committee
         WHERE meta_network_name = %(network)s 
           AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
         LIMIT 1) as beacon_api_count
    """
    committee_params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
    }
    committee_check = pd.read_sql(committee_check_sql, conn, params=committee_params)
    if committee_check.iloc[0]['canonical_count'] == 0 and committee_check.iloc[0]['beacon_api_count'] == 0:
        st.error(f"""
        ❌ **No committee data available for {network} in the selected time range**
        
        Head correctness calculation requires committee data to identify which validators 
        were scheduled to attest in each slot. Without this data, we cannot distinguish 
        between:
        - Validators attesting in their assigned slot (correct)
        - Validators from slot N+1 voting for slot N's block (incorrect, inflates metrics)
        
        Committee data is missing from both:
        - `canonical_beacon_committee` 
        - `beacon_api_eth_v1_beacon_committee`
        
        For the time range: {start_date} to {end_date}
        
        **Try selecting a different time range or check data collection for {network}.**
        """)
        return pd.DataFrame()

    try:
        params = {
            'network': network,
            'start_date': start_date,
            'end_date': end_date,
        }

        if grouping_dimension:
            # Grouping REQUIRES a network spec to work
            if not network_spec:
                st.error(f"""
                ❌ **Cannot use grouping for {network} - no network specification available**
                
                Grouping analysis requires a network specification file that maps validator indices
                to node names and client types. This file is missing for {network}.
                
                **Options:**
                1. Disable grouping to view overall head correctness
                2. Select a different network that has a network spec (e.g., holesky, sepolia)
                3. Add a network spec YAML file for {network}
                """)
                return pd.DataFrame()
            
            # Process slots in chunks to avoid query size limits with parallelization
            chunk_size = 500  # Process 500 slots at a time
            chunks = [eligible_slots[i:i + chunk_size] for i in range(0, len(eligible_slots), chunk_size)]
            
            def process_chunk(chunk_data):
                chunk_idx, slot_chunk = chunk_data
                try:
                    # Build proposer map for this chunk
                    proposer_map_sql = _build_proposer_map_union_selects(network_spec, slot_chunk, slot_to_proposer)
                    
                    if not proposer_map_sql:
                        logger.warning(f"No proposer mapping for chunk {chunk_idx + 1} - network spec missing or invalid")
                        return None

                    # Use the grouped query
                    sql = get_head_correctness_per_slot_grouped_query(group_by=grouping_dimension)
                    
                    # Create slot string for this chunk
                    chunk_slots_str = '(' + ','.join(str(s) for s in slot_chunk) + ')'
                    sql = sql.replace('%(eligible_slots)s', chunk_slots_str)
                    sql = sql.replace('{proposer_map_union_selects}', proposer_map_sql)
                    sql = sql.replace('{validator_filter}', '')  # No validator filtering for grouped queries
                    
                    # Create new connection for this thread
                    chunk_conn = get_database_connection(cluster_name)
                    if not chunk_conn:
                        logger.error(f"Failed to get database connection for chunk {chunk_idx + 1}")
                        return None
                    
                    chunk_df = pd.read_sql(sql, chunk_conn, params=params)
                    logger.info(f"Chunk {chunk_idx + 1} returned {len(chunk_df)} rows")
                    
                    if chunk_df.empty:
                        # Debug why no data
                        logger.warning(f"Chunk {chunk_idx + 1} returned empty - checking component tables")
                        
                        # Check if there's committee data for these slots
                        committee_test = f"""
                        SELECT COUNT(*) as count
                        FROM canonical_beacon_committee
                        WHERE meta_network_name = %(network)s
                          AND slot IN {chunk_slots_str}
                        """
                        try:
                            committee_count = pd.read_sql(committee_test, chunk_conn, params=params).iloc[0]['count']
                            logger.info(f"Chunk {chunk_idx + 1}: Committee rows found: {committee_count}")
                        except Exception as e:
                            logger.error(f"Chunk {chunk_idx + 1}: Committee check failed: {e}")
                        
                        # Check if there are blocks for these slots  
                        blocks_test = f"""
                        SELECT COUNT(*) as count
                        FROM beacon_api_eth_v2_beacon_block
                        WHERE meta_network_name = %(network)s
                          AND slot IN {chunk_slots_str}
                        """
                        try:
                            blocks_count = pd.read_sql(blocks_test, chunk_conn, params=params).iloc[0]['count']
                            logger.info(f"Chunk {chunk_idx + 1}: Blocks found: {blocks_count}")
                        except Exception as e:
                            logger.error(f"Chunk {chunk_idx + 1}: Blocks check failed: {e}")
                    
                    return chunk_df if not chunk_df.empty else None
                    
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Chunk {chunk_idx + 1} failed with error: {error_msg}")
                    import traceback
                    logger.error(f"Chunk {chunk_idx + 1} traceback: {traceback.format_exc()}")
                    
                    # Return error info to be handled in main thread
                    return {'error': error_msg, 'chunk': chunk_idx + 1}
            
            # Process chunks in parallel (5 at a time)
            all_dfs = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                # Submit all chunks
                future_to_chunk = {
                    executor.submit(process_chunk, (i, chunk)): i 
                    for i, chunk in enumerate(chunks)
                }
                
                # Collect results as they complete
                sql_errors = []
                for future in as_completed(future_to_chunk):
                    chunk_idx = future_to_chunk[future]
                    try:
                        result = future.result()
                        if result is not None:
                            # Check if it's an error dict
                            if isinstance(result, dict) and 'error' in result:
                                sql_errors.append(result)
                            else:
                                all_dfs.append(result)
                    except Exception as e:
                        logger.error(f"Chunk {chunk_idx + 1} future failed: {e}")
                
                # Show SQL errors if any
                if sql_errors:
                    for err in sql_errors[:1]:  # Show first error only to avoid spam
                        if "UNKNOWN_IDENTIFIER" in err['error'] or "DB::Exception" in err['error']:
                            st.error(f"""
                            ❌ **SQL Query Error in chunk {err['chunk']}**
                            
                            {err['error']}
                            
                            This is likely due to missing data or a query issue.
                            """)
            
            if not all_dfs:
                # Error already shown from SQL errors above if any
                return pd.DataFrame()
            
            # Combine all chunks
            df = pd.concat(all_dfs, ignore_index=True)
            logger.info(f"Combined {len(chunks)} chunks: {len(df)} total rows")

            # Add labels
            df['group_key'] = df['group_key'].astype(str)
            if grouping_dimension == 'node_type':
                df['group_label'] = df['group_key'].map({'supernode': 'Supernode', 'regular': 'Regular Node'}).fillna(df['group_key'])
            elif grouping_dimension == 'cl_client':
                df['group_label'] = df['group_key'].str.title()
            elif grouping_dimension == 'el_client':
                df['group_label'] = df['group_key'].str.title()
            elif grouping_dimension == 'cl_el_combined':
                df['group_label'] = df['group_key'].apply(lambda s: ' + '.join([p.title() for p in s.split('-')]) if isinstance(s, str) else s)
            elif grouping_dimension == 'cl_node_type':
                def format_cl_node_type(s):
                    if isinstance(s, str) and '-' in s:
                        parts = s.split('-')
                        if len(parts) == 2:
                            cl, node_type = parts
                            node_type_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                            return f"{cl.title()} + {node_type_label}"
                    return s
                df['group_label'] = df['group_key'].apply(format_cl_node_type)
            else:
                df['group_label'] = df['group_key']

            return df
        else:
            # Non-grouped per-slot computation
            validator_filter = build_validator_filter(validator_indices)
            
            # Use the per-slot query
            sql = get_head_correctness_per_slot_query().format(
                validator_filter=f"\n      {validator_filter}" if validator_filter else ""
            )
            sql = sql.replace('%(eligible_slots)s', slots_str)
            

            df = pd.read_sql(sql, conn, params=params)

            if df.empty:
                st.warning("No head correctness data found for the selected time range and filters.")
                return pd.DataFrame()

            df = df.rename(columns={
                'slot': 'slot',
                'blob_count': 'blob_count',
                'head_correctness_pct': 'head_correctness_pct',
                'total_scheduled': 'total_validators_assigned',
                'correct_votes': 'correct_head_votes'
            })
            return df

    except Exception as e:
        logger.error(f"Error loading head correctness data: {e}")
        import traceback
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
