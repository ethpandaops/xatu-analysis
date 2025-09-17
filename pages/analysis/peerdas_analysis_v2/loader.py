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
from shared.ethereum.validator_filters import get_node_classifications
from queries import (
    get_eligible_slots_query,
    build_proposer_filter,
    build_validator_filter,
    build_proposer_filter_ranges,
    build_validator_filter_ranges,
    get_head_correctness_per_slot_query,
    get_head_correctness_per_slot_grouped_query,
    get_head_correctness_per_slot_attester_grouped_query,
    get_mev_slots_query
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


# Note: get_node_classifications function moved to shared.ethereum.validator_filters


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_mev_slots(
    network: str,
    start_date: datetime,
    end_date: datetime,
    cluster_name: Optional[str] = None
) -> List[int]:
    """
    Load slots that were delivered via MEV relay.
    
    Returns:
        List of slot numbers that had MEV payloads
    """
    logger.info(f"Loading MEV slots for network={network}")
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return []
    
    query = get_mev_slots_query()
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date
    }
    
    try:
        df = pd.read_sql(query, conn, params=params)
        if df.empty:
            logger.info(f"No MEV slots found for network {network}")
            return []
        
        mev_slots = df['slot'].tolist()
        logger.info(f"Found {len(mev_slots)} MEV slots for {network} between {start_date} and {end_date}")
        logger.info(f"MEV slot range: {min(mev_slots)} to {max(mev_slots)}")
        # Sample some slots for debugging
        if len(mev_slots) > 10:
            logger.info(f"Sample MEV slots: {mev_slots[:5]} ... {mev_slots[-5:]}")
        return mev_slots
    except Exception as e:
        logger.warning(f"Error loading MEV slots (may not be available for this network): {e}")
        return []


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_eligible_slots(
    network: str,
    start_date: datetime,
    end_date: datetime,
    proposer_type: Optional[str] = None,
    cl_filter: Optional[List[str]] = None,
    el_filter: Optional[List[str]] = None,
    architecture_filter: Optional[List[str]] = None,
    operator_filter: Optional[List[str]] = None,
    mev_filter: Optional[str] = None,
    cluster_name: Optional[str] = None
) -> Tuple[List[int], Dict[int, str], Dict[int, int], List[int]]:
    """
    Load eligible slots based on proposer filtering and MEV status.

    Args:
        network: Network name
        start_date: Start datetime
        end_date: End datetime
        proposer_type: Filter by proposer node type
        cl_filter: Filter by CL implementations
        el_filter: Filter by EL implementations
        architecture_filter: Filter by architecture (ARM, x86)
        mev_filter: Filter by MEV status ('yes', 'no', 'both' or None)
        cluster_name: Cluster name

    Returns:
        Tuple of (slot_list, slot_to_block_root_mapping, slot_to_proposer_index_mapping, mev_slots_list)
    """
    logger.info(f"Loading eligible slots for network={network}")
    logger.info(f"Filters: proposer_type={proposer_type}, cl_filter={cl_filter}, el_filter={el_filter}, architecture_filter={architecture_filter}, operator_filter={operator_filter}, mev_filter={mev_filter}")
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return [], {}, {}, []
    
    # Get network spec for filtering
    network_spec = get_network_spec(network)
    
    if not network_spec:
        logger.error(f"Network spec not found for {network} - cannot proceed")
        return [], {}, {}, []
    
    logger.info(f"Network spec loaded for {network}")
    
    proposer_ranges = []  # Will store (start, end) tuples
    total_validator_count = 0

    # Check for filters that require network spec
    has_filters = proposer_type or cl_filter or el_filter or architecture_filter or operator_filter

    # ALWAYS filter to only validators in the spec
    # This prevents "unknown" entries from validators not in our config
    # Build list of ALL validator ranges in spec first
    all_spec_ranges = []
    for node_name in network_spec.get_all_nodes():
        v_range = network_spec.get_validator_range(node_name)
        if v_range:
            all_spec_ranges.append(v_range)
            total_validator_count += (v_range[1] - v_range[0])
    logger.info(f"Network spec contains {total_validator_count} validators across {len(all_spec_ranges)} ranges")

    # Now apply filters if any
    nodes_processed = 0
    nodes_matched = 0
    filtered_validator_count = 0
    for node_name in network_spec.get_all_nodes():
        nodes_processed += 1
        node_info = network_spec.get_node_info(node_name)
        if not node_info:
            continue

        v_range = network_spec.get_validator_range(node_name)
        if not v_range:
            continue

        # If no filters, include all nodes from the spec
        if not has_filters:
            proposer_ranges.append(v_range)
            filtered_validator_count += (v_range[1] - v_range[0])
            nodes_matched += 1
            continue

        # Check if node matches filters
        tags = node_info.get('tags', [])
        groups = node_info.get('groups', [])
        node_is_supernode = 'supernode' in tags

        # Check node type filter
        if proposer_type:
            if proposer_type == 'supernode' and not node_is_supernode:
                continue
            if proposer_type == 'regular' and node_is_supernode:
                continue

        # Check architecture filter
        if architecture_filter:
            node_architecture = 'ARM' if 'arm' in groups else 'x86'
            if node_architecture not in architecture_filter:
                continue

        # Operator filter will be applied in SQL via join with dim_node

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

        # Add validator range for this node
        proposer_ranges.append(v_range)
        filtered_validator_count += (v_range[1] - v_range[0])
        nodes_matched += 1

    logger.info(f"Proposer filter: processed {nodes_processed} nodes, matched {nodes_matched}, total validators: {filtered_validator_count}")

    # CRITICAL: When no filters are applied, use ALL spec validators to filter out unknown proposers
    if not has_filters:
        proposer_ranges = all_spec_ranges
        logger.info(f"No filters applied - using all {len(all_spec_ranges)} ranges to exclude unknown proposers")
    
    # Show validator selection in UI
    with st.expander("🔎 Validator Selection Debug", expanded=False):
        st.write(f"**Nodes processed:** {nodes_processed}")
        st.write(f"**Nodes matched filters:** {nodes_matched}")
        st.write(f"**Total validator count:** {filtered_validator_count}")
        st.write(f"**Number of ranges:** {len(proposer_ranges)}")
        if proposer_ranges:
            st.write(f"**Sample ranges (first 5):** {proposer_ranges[:5]}")
            # Calculate query size reduction
            old_size = sum((r[1] - r[0]) * 6 for r in proposer_ranges)  # Approx 6 chars per number
            new_size = len(proposer_ranges) * 15  # Approx 15 chars per range
            st.write(f"**Query size reduction:** {old_size:,} bytes → {new_size:,} bytes ({100 - (new_size*100//old_size)}% reduction)")
        else:
            st.write("⚠️ No validators selected! This will return no results.")
    
    # Build proposer filter using ranges - this will exclude proposers outside our spec
    # If we have many validators, use range-based approach
    if proposer_ranges and sum(r[1] - r[0] for r in proposer_ranges) > 1000:
        filter_result = build_proposer_filter_ranges(proposer_ranges)

        # Parse the CTE and WHERE clause from the result
        if filter_result:
            parts = filter_result.split('|||')
            proposer_cte = parts[0] if len(parts) > 0 else ""
            proposer_where = parts[1] if len(parts) > 1 else ""
        else:
            proposer_cte = ""
            proposer_where = ""
    else:
        # For small sets, still use the old approach to avoid unnecessary complexity
        proposer_cte = ""
        if proposer_ranges:
            # Convert ranges back to indices for small sets
            proposer_indices = []
            for start, end in proposer_ranges:
                proposer_indices.extend(range(start, end))
            proposer_where = build_proposer_filter(proposer_indices)
        else:
            proposer_where = ""

    # Debug logging
    logger.info(f"Proposer ranges count: {len(proposer_ranges)}")
    if proposer_ranges:
        logger.info(f"First 5 ranges: {proposer_ranges[:5]}")
        logger.info(f"Total validators covered: {sum(r[1] - r[0] for r in proposer_ranges)}")
    
    # Get base query and inject the CTE if needed
    base_query = get_eligible_slots_query()

    if proposer_cte:
        # Inject the CTE at the beginning of the query
        if "WITH" in base_query:
            # Add to existing WITH clause
            query = base_query.replace("WITH", f"WITH {proposer_cte},", 1)
        else:
            # Add new WITH clause
            query = f"WITH {proposer_cte}\n{base_query}"
        # Apply the WHERE clause
        query = query.format(proposer_filter=proposer_where)
    else:
        query = base_query.format(proposer_filter="")

    # Debug: Log part of the query
    if proposer_cte:
        logger.info(f"Proposer CTE applied with {len(proposer_ranges)} ranges")
        with st.expander("🔍 SQL Query Debug", expanded=False):
            st.write("**Range-based filter (CTE):**")
            st.code(proposer_cte[:500] + "..." if len(proposer_cte) > 500 else proposer_cte)
    else:
        logger.info("No proposer filter applied")
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date
    }
    
    try:
        # First, let's check what's actually in the database
        with st.expander("🔍 Database Query Debug", expanded=False):
            st.write("**Running eligibility query...**")
            st.code(query[:500] + "..." if len(query) > 500 else query)
            
            # Run a simpler test query first
            test_query = """
            SELECT COUNT(*) as total_blocks,
                   COUNT(DISTINCT proposer_index) as unique_proposers,
                   MIN(proposer_index) as min_proposer,
                   MAX(proposer_index) as max_proposer
            FROM beacon_api_eth_v2_beacon_block
            WHERE meta_network_name = %(network)s
              AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            """
            test_df = pd.read_sql(test_query, conn, params=params)
            st.write("**Test query results:**")
            st.write(test_df)
            
        df = pd.read_sql(query, conn, params=params)
        
        with st.expander("✅ Query Results", expanded=False):
            st.write(f"**Slots found:** {len(df) if not df.empty else 0}")
            if not df.empty:
                st.write(f"**Unique slots:** {df['slot'].nunique() if 'slot' in df.columns else 0}")
                st.write(f"**Slot range:** {df['slot'].min()} to {df['slot'].max()}" if 'slot' in df.columns else "N/A")
        
        if df.empty:
            logger.warning(f"No slots found in database for network {network}")
            
            # Show what proposers are actually in the database
            with st.expander("🔍 Available Proposers in Database", expanded=False):
                check_query = """
                SELECT proposer_index, COUNT(*) as block_count
                FROM beacon_api_eth_v2_beacon_block
                WHERE meta_network_name = %(network)s
                  AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
                GROUP BY proposer_index
                ORDER BY proposer_index
                LIMIT 20
                """
                check_df = pd.read_sql(check_query, conn, params=params)
                st.write("**Sample proposers in database:**")
                st.write(check_df)
                
                if proposer_indices:
                    # Check overlap
                    db_proposers = set(check_df['proposer_index'].tolist()) if not check_df.empty else set()
                    filter_proposers = set(proposer_indices)
                    overlap = db_proposers.intersection(filter_proposers)
                    st.write(f"**Overlap between filter and database:** {len(overlap)} proposers")
                    if overlap:
                        st.write(f"**Overlapping proposers:** {sorted(overlap)[:20]}")
                    
            return [], {}, {}, []
        
        # Load MEV slots
        mev_slots = load_mev_slots(network, start_date, end_date, cluster_name)
        mev_slots_set = set(mev_slots)
        
        # Apply MEV filter if specified
        if mev_filter and mev_filter != 'both':
            if mev_filter == 'yes':
                # Only keep MEV slots
                df = df[df['slot'].isin(mev_slots_set)]
                logger.info(f"Filtered to {len(df)} MEV slots")
            elif mev_filter == 'no':
                # Only keep non-MEV slots
                df = df[~df['slot'].isin(mev_slots_set)]
                logger.info(f"Filtered to {len(df)} non-MEV slots")
        
        if df.empty:
            logger.warning(f"No slots remaining after MEV filter: {mev_filter}")
            return [], {}, {}, []
        
        slots = df['slot'].tolist()
        slot_to_block = dict(zip(df['slot'], df['block_root']))
        slot_to_proposer = dict(zip(df['slot'], df['proposer_index']))
        
        logger.info(f"Found {len(slots)} eligible slots (MEV filter: {mev_filter})")
        logger.info(f"Returning {len(mev_slots)} MEV slots along with eligible slots")
        return slots, slot_to_block, slot_to_proposer, mev_slots
    except Exception as e:
        error_msg = f"Error loading eligible slots: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Orig exception: {e}", exc_info=True)
        # Store error in session state for display
        if hasattr(st, 'session_state'):
            st.session_state['peerdas_v2_last_error'] = error_msg
        # Re-raise the exception so it can be caught and displayed in the UI
        raise Exception(error_msg) from e


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def _build_attester_map_union_selects(_network_spec, attester_type: Optional[str], cl_filter: Optional[List[str]], el_filter: Optional[List[str]], architecture_filter: Optional[List[str]], operator_filter: Optional[List[str]]) -> str:
    """Build UNION ALL SELECT mapping for validator->group using network_spec ranges."""
    logger.info(f"Building attester map: attester_type={attester_type}, cl_filter={cl_filter}, el_filter={el_filter}, architecture_filter={architecture_filter}, operator_filter={operator_filter}")

    if not _network_spec:
        logger.error("No network_spec provided to _build_attester_map_union_selects")
        return ""

    # Use the unhashed network_spec parameter
    network_spec = _network_spec

    nodes_processed = 0
    nodes_included = 0

    # Group ranges by their characteristics to minimize query size
    # Key: (node_type, cl_client, el_client) -> List of (start, end) ranges
    grouped_ranges = {}

    for node_name in network_spec.get_all_nodes():
        nodes_processed += 1
        node_info = network_spec.get_node_info(node_name) or {}
        v_range = network_spec.get_validator_range(node_name)

        if not v_range:
            logger.debug(f"Node {node_name} has no validator range, skipping")
            continue
        start, end = v_range

        tags = network_spec.get_node_tags(node_name) or []
        groups = node_info.get('groups', [])
        attributes = node_info.get('attributes', {})
        node_is_supernode = 'supernode' in tags or attributes.get('supernode', False)
        node_architecture = 'ARM' if 'arm' in groups else 'x86'
        # Operator will come from dim_node join, not from YAML

        # Apply attester-type filter
        if attester_type == 'supernode' and not node_is_supernode:
            continue
        if attester_type == 'regular' and node_is_supernode:
            continue

        # Apply architecture filter
        if architecture_filter and node_architecture not in architecture_filter:
            continue

        # Operator filter will be applied in SQL via join with dim_node
        # Skip operator filtering in the attester map generation

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

        # Group by characteristics (without operator, which comes from dim_node)
        key = (node_type, cl, el, node_architecture)
        if key not in grouped_ranges:
            grouped_ranges[key] = []
        grouped_ranges[key].append((int(start), int(end)))
        nodes_included += 1

        # Debug: Log nodes that don't have clear supernode determination
        if not node_is_supernode and 'supernode' not in tags and not node_info.get('attributes', {}).get('supernode', False):
            logger.debug(f"DEBUG: Node {node_name} classified as 'regular' - tags: {tags}, supernode attr: {node_info.get('attributes', {}).get('supernode')}")

    logger.info(f"Processed {nodes_processed} nodes, included {nodes_included} in attester map")
    logger.info(f"Grouped into {len(grouped_ranges)} unique characteristic combinations")

    # Build efficient SELECT statements using arrayConcat for each group
    selects = []
    for (node_type, cl, el, architecture), ranges in grouped_ranges.items():
        # Build range expressions
        range_parts = [f"range({start}, {end})" for start, end in ranges]

        # If we have many ranges for this group, chunk them
        if len(range_parts) > 50:
            # Split into chunks of 50 ranges
            chunk_size = 50
            chunks = [range_parts[i:i + chunk_size] for i in range(0, len(range_parts), chunk_size)]

            for chunk in chunks:
                select_sql = f"""SELECT
      arrayJoin(arrayConcat({','.join(chunk)})) AS validator_index,
      '{node_type}' AS node_type,
      '{cl}' AS cl_client,
      '{el}' AS el_client,
      '{architecture}' AS architecture"""
                selects.append(select_sql)
        else:
            # For smaller sets, use a single arrayConcat
            select_sql = f"""SELECT
      arrayJoin(arrayConcat({','.join(range_parts)})) AS validator_index,
      '{node_type}' AS node_type,
      '{cl}' AS cl_client,
      '{el}' AS el_client,
      '{architecture}' AS architecture"""
            selects.append(select_sql)

    if not selects:
        logger.warning("No SELECT statements generated for attester map")
        return ""

    result = "\nUNION ALL\n".join(selects)
    logger.info(f"Generated {len(selects)} SELECT statements for attester map")
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
            logger.warning(f"Missing proposer index for slot {slot} - EXCLUDING from analysis")
            # Skip this slot entirely - don't add to selects
            continue
            
        proposer_index = slot_to_proposer[slot]
        
        # If proposer not in our validator mapping, EXCLUDE from analysis
        if proposer_index not in validator_to_node:
            logger.debug(f"Proposer {proposer_index} for slot {slot} not in network spec - EXCLUDING from analysis")
            # Skip this slot entirely - don't add to selects
            continue
            
        node_name = validator_to_node[proposer_index]
        
        # Get node characteristics (cached per node)
        cache_key = f"node_chars_{node_name}"
        if not hasattr(_build_proposer_map_union_selects, cache_key):
            node_info = network_spec.get_node_info(node_name) or {}
            tags = network_spec.get_node_tags(node_name) or []
            groups = node_info.get('groups', [])
            attributes = node_info.get('attributes', {})
            node_is_supernode = 'supernode' in tags or attributes.get('supernode', False)
            node_architecture = 'ARM' if 'arm' in groups else 'x86'
            # Operator will come from dim_node join, not from YAML

            # Extract clients from tags
            cl = ''
            el = ''
            for tag in tags:
                if tag.startswith('cl:') and len(tag.split(':')) == 2:
                    cl = tag.split(':')[1]
                elif tag.startswith('el:') and len(tag.split(':')) == 2:
                    el = tag.split(':')[1]

            node_type = 'supernode' if node_is_supernode else 'regular'
            setattr(_build_proposer_map_union_selects, cache_key, (node_type, cl, el, node_architecture))

        node_type, cl, el, architecture = getattr(_build_proposer_map_union_selects, cache_key)

        # Build SELECT for this slot - operator will be joined from dim_node
        select_sql = f"SELECT {slot} AS slot, {proposer_index} AS proposer_index, '{node_type}' AS node_type, '{cl}' AS cl_client, '{el}' AS el_client, '{architecture}' AS architecture"
        selects.append(select_sql)
    
    logger.info(f"Built proposer map for {len(selects)} slots out of {len(eligible_slots)} eligible slots")
    if len(selects) < len(eligible_slots):
        excluded_count = len(eligible_slots) - len(selects)
        logger.warning(f"Excluded {excluded_count} slots ({excluded_count*100/len(eligible_slots):.1f}%) with proposers outside network spec")
    
    if not selects:
        logger.error("No valid slots remaining after filtering out unknown proposers!")
        return ""
    
    result = "\nUNION ALL\n".join(selects)
    return result


def _build_group_index_map(
    network_spec,
    grouping_dimension: str,
    attester_type: Optional[str],
    cl_filter: Optional[List[str]],
    el_filter: Optional[List[str]],
    architecture_filter: Optional[List[str]]
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
        groups = node_info.get('groups', [])
        node_is_supernode = 'supernode' in tags or node_info.get('attributes', {}).get('supernode', False)
        node_architecture = 'ARM' if 'arm' in groups else 'x86'
        clients = network_spec.get_node_clients(node_name)
        cl = clients.get('cl') or ''
        el = clients.get('el') or ''

        # Apply filters
        if attester_type == 'supernode' and not node_is_supernode:
            continue
        if attester_type == 'regular' and node_is_supernode:
            continue
        if architecture_filter and node_architecture not in architecture_filter:
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
        elif grouping_dimension == 'cl_architecture':
            if not cl:
                continue
            key = f"{cl}-{node_architecture}"
        elif grouping_dimension == 'architecture':
            key = node_architecture
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
    mev_slots: List[int] = None,
    attester_type: Optional[str] = None,
    cl_filter: Optional[List[str]] = None,
    el_filter: Optional[List[str]] = None,
    architecture_filter: Optional[List[str]] = None,
    operator_filter: Optional[List[str]] = None,
    grouping_dimension: Optional[str] = None,
    attester_grouping_dimension: Optional[str] = None,  # New parameter
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
        mev_slots: List of MEV slots for grouping
        attester_type: Filter by attester node type
        cl_filter: Filter by CL implementations
        el_filter: Filter by EL implementations
        architecture_filter: Filter by architecture (ARM, x86)
        grouping_dimension: Optional grouping dimension for proposers
        attester_grouping_dimension: Optional grouping dimension for attesters
        cluster_name: Optional cluster name

    Returns:
        DataFrame with head correctness data by slot
    """
    logger.info(f"Loading head correctness data for {network}, {len(eligible_slots)} slots")
    logger.info(f"Received {len(mev_slots) if mev_slots else 0} MEV slots for analysis")
    
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
    validator_ranges = []  # Will store (start, end) tuples
    total_attester_count = 0
    has_attester_filters = attester_type or cl_filter or el_filter

    if network_spec:
        # First collect ALL validator ranges in the spec
        all_spec_ranges = []
        for node_name in network_spec.get_all_nodes():
            v_range = network_spec.get_validator_range(node_name)
            if v_range:
                all_spec_ranges.append(v_range)
                total_attester_count += (v_range[1] - v_range[0])
        logger.info(f"Network spec contains {total_attester_count} validators for attester filtering")

        # Now apply filters if needed
        filtered_attester_count = 0
        for node_name in network_spec.get_all_nodes():
            node_info = network_spec.get_node_info(node_name)
            if not node_info:
                continue

            v_range = network_spec.get_validator_range(node_name)
            if not v_range:
                continue

            # If no filters, we'll use all_spec_ranges later
            if not has_attester_filters:
                validator_ranges.append(v_range)
                filtered_attester_count += (v_range[1] - v_range[0])
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

            # Add validator range for this node
            validator_ranges.append(v_range)
            filtered_attester_count += (v_range[1] - v_range[0])

        # CRITICAL: When no filters, use ALL spec validators to filter out unknown attesters
        if not has_attester_filters:
            validator_ranges = all_spec_ranges
            logger.info(f"No attester filters - using all {len(all_spec_ranges)} ranges to exclude unknown attesters")
        else:
            logger.info(f"Attester filter applied: {filtered_attester_count} validators selected across {len(validator_ranges)} ranges")
    
    # Check if committee data exists FIRST - REQUIRED for accurate head correctness
    committee_check_sql = """
    SELECT
        (SELECT COUNT(*) FROM canonical_beacon_committee
         WHERE meta_network_name = %(network)s
           AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
         LIMIT 1) as canonical_count
    """
    committee_params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
    }
    committee_check = pd.read_sql(committee_check_sql, conn, params=committee_params)
    if committee_check.iloc[0]['canonical_count'] == 0:
        st.error(f"""
        ❌ **No committee data available for {network} in the selected time range**

        Head correctness calculation requires committee data to identify which validators
        were scheduled to attest in each slot. Without this data, we cannot distinguish
        between:
        - Validators attesting in their assigned slot (correct)
        - Validators from slot N+1 voting for slot N's block (incorrect, inflates metrics)

        Committee data is missing from `canonical_beacon_committee` table.

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
                    
                    # Verify proposer_map_sql has SELECT statements
                    if 'SELECT' not in proposer_map_sql:
                        logger.error(f"Chunk {chunk_idx + 1}: Invalid proposer map SQL - no SELECT statements found")
                        return None

                    # Use the grouped query
                    sql = get_head_correctness_per_slot_grouped_query(group_by=grouping_dimension)

                    # Create slot string for this chunk
                    chunk_slots_str = '(' + ','.join(str(s) for s in slot_chunk) + ')'
                    sql = sql.replace('%(eligible_slots)s', chunk_slots_str)
                    sql = sql.replace('{proposer_map_union_selects}', proposer_map_sql)
                    sql = sql.replace('{network}', network)

                    # Add operator filter if provided
                    if operator_filter:
                        operator_list = ','.join([f"'{op}'" for op in operator_filter])
                        operator_where = f"WHERE dn.source IN ({operator_list})"
                        sql = sql.replace('{operator_filter_proposer}', operator_where)
                    else:
                        sql = sql.replace('{operator_filter_proposer}', '')
                    
                    # Apply validator filter for attester filtering even in grouped queries
                    # Build validator filter from the attester-filtered validator ranges
                    filter_result = build_validator_filter_ranges(validator_ranges)
                    if filter_result:
                        parts = filter_result.split('|||')
                        validator_cte = parts[0] if len(parts) > 0 else ""
                        validator_where = parts[1] if len(parts) > 1 else ""

                        # Add the CTE to the query
                        if validator_cte:
                            # Find the WITH clause and add our CTE
                            if "WITH" in sql:
                                sql = sql.replace("WITH", f"WITH {validator_cte},", 1)
                            else:
                                sql = f"WITH {validator_cte}\n{sql}"

                        logger.info(f"Chunk {chunk_idx + 1}: Applying attester filter using {len(validator_ranges)} ranges")
                        sql = sql.replace('{validator_filter}', f"\n      {validator_where}" if validator_where else '')
                    else:
                        sql = sql.replace('{validator_filter}', '')
                    
                    # Debug: Check if query still has unreplaced placeholders
                    if '{' in sql and '}' in sql:
                        logger.warning(f"Chunk {chunk_idx + 1}: Query may have unreplaced placeholders")
                        # Find and log any remaining placeholders
                        import re
                        placeholders = re.findall(r'\{[^}]+\}', sql)
                        if placeholders:
                            logger.error(f"Chunk {chunk_idx + 1}: Unreplaced placeholders found: {placeholders}")
                    
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
                        sql_errors.append({'error': str(e), 'chunk': chunk_idx + 1})
                
                # Show SQL errors if any
                if sql_errors:
                    for err in sql_errors[:1]:  # Show first error only to avoid spam
                        # Store error for dashboard to display
                        st._last_sql_error = err['error']
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
            if grouping_dimension == 'none':
                df['group_label'] = 'All Proposers'
            elif grouping_dimension == 'block_building':
                df['group_label'] = df['group_key'].map({'mev': 'Via MEV Relay', 'non-mev': 'Locally Built'}).fillna(df['group_key'])
            elif grouping_dimension == 'node_type':
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
            elif grouping_dimension == 'node_type_mev':
                def format_node_type_mev(s):
                    if isinstance(s, str):
                        # Handle the format: "supernode-non-mev" or "regular-mev"
                        if s.endswith('-non-mev'):
                            node_type = s[:-8]  # Remove '-non-mev'
                            node_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                            return f"{node_label} (Locally built)"
                        elif s.endswith('-mev'):
                            node_type = s[:-4]  # Remove '-mev'
                            node_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                            return f"{node_label} (Via MEV)"
                    return s
                df['group_label'] = df['group_key'].apply(format_node_type_mev)
            elif grouping_dimension == 'cl_node_type_mev':
                def format_cl_node_type_mev(s):
                    if isinstance(s, str):
                        # Handle the format: "lighthouse-supernode-non-mev" or "prysm-regular-mev"
                        if '-non-mev' in s:
                            base = s.replace('-non-mev', '')
                            parts = base.split('-')
                            if len(parts) == 2:
                                cl, node_type = parts
                                node_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                                return f"{cl.title()} {node_label} (Locally built)"
                        elif '-mev' in s and '-non-mev' not in s:
                            base = s.replace('-mev', '')
                            parts = base.split('-')
                            if len(parts) == 2:
                                cl, node_type = parts
                                node_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                                return f"{cl.title()} {node_label} (Via MEV)"
                    return s
                df['group_label'] = df['group_key'].apply(format_cl_node_type_mev)
            else:
                df['group_label'] = df['group_key']
            
            # If attester grouping is also requested, load that data too
            # Note: We load attester data even when grouping is 'none' to show all attesters as a single series
            if attester_grouping_dimension:
                logger.info(f"Loading attester-grouped data with dimension: {attester_grouping_dimension}")
                
                # Build attester map for grouping
                attester_map_sql = _build_attester_map_union_selects(
                    network_spec,
                    attester_type,
                    cl_filter,
                    el_filter,
                    architecture_filter,
                    operator_filter
                )
                
                if not attester_map_sql:
                    logger.warning("No attester mapping available - skipping attester grouping")
                    df['data_type'] = 'proposer'
                    return df
                
                # Use the attester grouped query
                attester_sql = get_head_correctness_per_slot_attester_grouped_query(group_by=attester_grouping_dimension)
                attester_sql = attester_sql.replace('%(eligible_slots)s', slots_str)
                attester_sql = attester_sql.replace('{attester_map_union_selects}', attester_map_sql)
                attester_sql = attester_sql.replace('{network}', network)

                # Add operator filter if provided
                if operator_filter:
                    operator_list = ','.join([f"'{op}'" for op in operator_filter])
                    operator_where = f"WHERE dn.source IN ({operator_list})"
                    attester_sql = attester_sql.replace('{operator_filter_attester}', operator_where)
                else:
                    attester_sql = attester_sql.replace('{operator_filter_attester}', '')

                # Apply validator filter for attester filtering - SAME AS PROPOSER QUERY
                # Build validator filter from the attester-filtered validator ranges
                filter_result = build_validator_filter_ranges(validator_ranges)
                if filter_result:
                    parts = filter_result.split('|||')
                    validator_cte = parts[0] if len(parts) > 0 else ""
                    validator_where = parts[1] if len(parts) > 1 else ""

                    # Add the CTE to the query
                    if validator_cte:
                        # Find the WITH clause and add our CTE
                        if "WITH" in attester_sql:
                            attester_sql = attester_sql.replace("WITH", f"WITH {validator_cte},", 1)
                        else:
                            attester_sql = f"WITH {validator_cte}\n{attester_sql}"

                    logger.info(f"Attester query: Applying attester filter using {len(validator_ranges)} ranges")
                    attester_sql = attester_sql.replace('{validator_filter}', f"\n      {validator_where}" if validator_where else '')
                else:
                    attester_sql = attester_sql.replace('{validator_filter}', '')
                
                # Debug: Log first part of query to check formatting
                logger.debug(f"First 500 chars of attester SQL: {attester_sql[:500]}")
                
                # Execute attester query
                try:
                    attester_df = pd.read_sql(attester_sql, conn, params=params)
                except Exception as e:
                    logger.error(f"Attester query failed. First 2000 chars of SQL:\n{attester_sql[:2000]}")
                    raise
                
                if not attester_df.empty:
                    # Filter out any rows with null or empty group_key values
                    # This can happen if validators are not in our network spec
                    # Exception: when grouping is 'none', group_key will be 'all' which is valid
                    initial_count = len(attester_df)
                    attester_df = attester_df[attester_df['group_key'].notna()]
                    if attester_grouping_dimension != 'none':
                        # Only filter out empty values when not using 'none' grouping
                        attester_df = attester_df[~attester_df['group_key'].isin(['', 'None', 'nan'])]
                    filtered_count = initial_count - len(attester_df)
                    if filtered_count > 0:
                        logger.info(f"Filtered out {filtered_count} rows with empty/unknown group_key values")
                    
                    # Add labels for attester groups
                    attester_df['group_key'] = attester_df['group_key'].astype(str)
                    if attester_grouping_dimension == 'none':
                        attester_df['group_label'] = 'All Attesters'
                    elif attester_grouping_dimension == 'node_type':
                        attester_df['group_label'] = attester_df['group_key'].map({
                            'supernode': 'Supernode',
                            'regular': 'Regular Node'
                        }).fillna(attester_df['group_key'])
                    elif attester_grouping_dimension == 'cl_client':
                        attester_df['group_label'] = attester_df['group_key'].str.title()
                    elif attester_grouping_dimension == 'el_client':
                        attester_df['group_label'] = attester_df['group_key'].str.title()
                    elif attester_grouping_dimension == 'cl_el_combined':
                        attester_df['group_label'] = attester_df['group_key'].apply(
                            lambda s: ' + '.join([p.title() for p in s.split('-')]) if isinstance(s, str) else s
                        )
                    elif attester_grouping_dimension == 'cl_node_type':
                        def format_cl_node_type(s):
                            if isinstance(s, str) and '-' in s:
                                parts = s.split('-')
                                if len(parts) == 2:
                                    cl, node_type = parts
                                    node_type_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                                    return f"{cl.title()} + {node_type_label}"
                            return s
                        attester_df['group_label'] = attester_df['group_key'].apply(format_cl_node_type)
                    elif attester_grouping_dimension == 'el_node_type':
                        def format_el_node_type(s):
                            if isinstance(s, str) and '-' in s:
                                parts = s.split('-')
                                if len(parts) == 2:
                                    el, node_type = parts
                                    node_type_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                                    return f"{el.title()} + {node_type_label}"
                            return s
                        attester_df['group_label'] = attester_df['group_key'].apply(format_el_node_type)
                    else:
                        attester_df['group_label'] = attester_df['group_key']
                    
                    # Mark data types
                    df['data_type'] = 'proposer'
                    attester_df['data_type'] = 'attester'
                    
                    # Combine both dataframes
                    combined_df = pd.concat([df, attester_df], ignore_index=True)
                    return combined_df
                else:
                    logger.warning("No attester grouped data returned")
                    df['data_type'] = 'proposer'
                    return df
            else:
                df['data_type'] = 'proposer'
                return df

            return df
        else:
            # Non-grouped per-slot computation
            # Build validator filter using ranges
            filter_result = build_validator_filter_ranges(validator_ranges)

            # Parse the CTE and WHERE clause from the result
            if filter_result:
                parts = filter_result.split('|||')
                validator_cte = parts[0] if len(parts) > 0 else ""
                validator_where = parts[1] if len(parts) > 1 else ""
                logger.info(f"Applying attester filter to {sum(r[1] - r[0] for r in validator_ranges)} validators using {len(validator_ranges)} ranges")
            else:
                validator_cte = ""
                validator_where = ""

            # Use the per-slot query
            base_query = get_head_correctness_per_slot_query()

            # Inject the CTE if needed
            if validator_cte:
                # The query already has WITH clause from CTEs, so we need to add our CTE
                sql = base_query.replace("WITH\n    ", f"WITH\n    {validator_cte},\n    ")
                sql = sql.format(validator_filter=f"\n      {validator_where}" if validator_where else "")
            else:
                sql = base_query.format(validator_filter="")

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
        error_msg = f"Error loading head correctness data: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        # Store error in session state for display
        if hasattr(st, 'session_state'):
            st.session_state['peerdas_v2_last_error'] = error_msg
        # Re-raise the exception so it can be caught and displayed in the UI
        raise Exception(error_msg) from e



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
