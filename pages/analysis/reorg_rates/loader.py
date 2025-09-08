"""
Data loader for Reorg Rates Analysis.

This module loads reorg rate data by comparing blocks in beacon_api_eth_v2_beacon_block
(all proposed blocks) vs canonical_beacon_block (finalized chain), with support for 
filtering by proposer characteristics and handling canonical table lag.
"""

import pandas as pd
import polars as pl
import streamlit as st
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
import logging
import yaml
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from shared.database import get_database_connection
from shared.network_spec import get_network_spec
from shared.ethereum.validator_filters import get_filtered_proposer_indices
from pages.analysis.reorg_rates.queries import (
    get_eligible_slots_query,
    build_proposer_filter,
    get_canonical_max_slot_query,
    get_reorg_rates_query,
    get_reorg_rates_grouped_query,
    get_mev_slots_query
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def get_canonical_max_slot(
    network: str,
    start_date: datetime,
    end_date: datetime,
    cluster_name: Optional[str] = None
) -> Optional[int]:
    """
    Get the highest finalized slot from canonical_beacon_block to ensure proper analysis bounds.
    
    CRITICAL: Only analyze blocks up to this slot to avoid false reorg classifications
    for recent unfinalized blocks.
    
    Returns:
        The maximum slot in canonical_beacon_block, or None if no data found
    """
    logger.info(f"Getting canonical max slot for network={network}")
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return None
    
    query = get_canonical_max_slot_query()
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date
    }
    
    try:
        df = pd.read_sql(query, conn, params=params)
        if df.empty or pd.isna(df.iloc[0]['max_canonical_slot']):
            logger.warning(f"No canonical blocks found for network {network}")
            return None
        
        max_slot = int(df.iloc[0]['max_canonical_slot'])
        logger.info(f"Canonical max slot for {network}: {max_slot}")
        return max_slot
    except Exception as e:
        logger.error(f"Error getting canonical max slot: {e}")
        return None


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_mev_slots(
    network: str,
    start_date: datetime,
    end_date: datetime,
    max_canonical_slot: int,
    cluster_name: Optional[str] = None
) -> List[int]:
    """
    Load slots that were delivered via MEV relay, limited to finalized slots.
    
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
        
        # Filter to only finalized slots
        mev_slots = df['slot'].tolist()
        finalized_mev_slots = [slot for slot in mev_slots if slot <= max_canonical_slot]
        
        logger.info(f"Found {len(finalized_mev_slots)} finalized MEV slots (out of {len(mev_slots)} total) for {network}")
        if finalized_mev_slots:
            logger.info(f"MEV slot range: {min(finalized_mev_slots)} to {max(finalized_mev_slots)}")
        return finalized_mev_slots
    except Exception as e:
        logger.warning(f"Error loading MEV slots (may not be available for this network): {e}")
        return []


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_eligible_slots(
    network: str,
    start_date: datetime,
    end_date: datetime,
    max_canonical_slot: int,
    proposer_type: Optional[str] = None,
    cl_filter: Optional[List[str]] = None,
    el_filter: Optional[List[str]] = None,
    mev_filter: Optional[str] = None,
    cluster_name: Optional[str] = None
) -> Tuple[List[int], Dict[int, str], Dict[int, int], List[int]]:
    """
    Load eligible slots based on proposer filtering and MEV status, limited to finalized slots.
    
    Args:
        network: Network name
        start_date: Start datetime
        end_date: End datetime
        max_canonical_slot: Maximum canonical slot (finalized blocks only)
        proposer_type: Filter by proposer node type
        cl_filter: Filter by CL implementations
        el_filter: Filter by EL implementations
        mev_filter: Filter by MEV status ('yes', 'no', 'both' or None)
        cluster_name: Cluster name
    
    Returns:
        Tuple of (slot_list, slot_to_block_root_mapping, slot_to_proposer_index_mapping, mev_slots_list)
    """
    logger.info(f"Loading eligible slots for network={network} up to slot {max_canonical_slot}")
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return [], {}, {}, []
    
    # Get proposer indices from network spec for filtering
    proposer_indices = get_filtered_proposer_indices(
        network=network,
        proposer_type=proposer_type,
        cl_filter=cl_filter,
        el_filter=el_filter
    )
    
    logger.info(f"Proposer filter: {len(proposer_indices)} validators selected")
    
    # Build proposer filter
    proposer_filter = build_proposer_filter(proposer_indices)
    
    # Get query with filter
    query = get_eligible_slots_query()
    query = query.replace('{{proposer_filter}}', proposer_filter)
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date
    }
    
    try:
        df = pd.read_sql(query, conn, params=params)
        if df.empty:
            logger.warning(f"No slots found in database for network {network}")
            return [], {}, {}, []
        
        # Filter to only finalized slots
        df = df[df['slot'] <= max_canonical_slot]
        
        if df.empty:
            logger.warning(f"No finalized slots found for network {network} up to slot {max_canonical_slot}")
            return [], {}, {}, []
        
        # Load MEV slots (already filtered to finalized)
        mev_slots = load_mev_slots(network, start_date, end_date, max_canonical_slot, cluster_name)
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
        
        logger.info(f"Found {len(slots)} eligible finalized slots (MEV filter: {mev_filter})")
        logger.info(f"Slot range: {min(slots)} to {max(slots)} (canonical max: {max_canonical_slot})")
        return slots, slot_to_block, slot_to_proposer, mev_slots
    except Exception as e:
        logger.error(f"Error loading eligible slots: {e}")
        return [], {}, {}, []


def _build_proposer_map_union_selects(network_spec, eligible_slots: List[int], slot_to_proposer: Dict[int, int] = None) -> str:
    """Build UNION ALL SELECT mapping for proposer_index->characteristics using network_spec."""
    logger.info(f"Building proposer map for {len(eligible_slots)} eligible slots")
    
    if not eligible_slots:
        logger.error("No eligible_slots provided")
        return ""
    
    # If no network spec, return empty - NO FALLBACKS
    if not network_spec:
        logger.error("No network spec available - cannot build proposer map")
        return ""
    
    # Build validator_index -> node mapping from network spec (no caching in multi-threaded context)
    validator_to_node = {}
    for node_name in network_spec.get_all_nodes():
        v_range = network_spec.get_validator_range(node_name)
        if v_range:
            start, end = v_range
            for validator_index in range(int(start), int(end)):
                validator_to_node[validator_index] = node_name
    
    logger.info(f"Built validator mapping for {len(validator_to_node)} validators")
    
    # Get unique proposer indices from eligible slots
    unique_proposers = set()
    if slot_to_proposer:
        for slot in eligible_slots:
            if slot in slot_to_proposer:
                unique_proposers.add(slot_to_proposer[slot])
    
    logger.info(f"Processing {len(unique_proposers)} unique proposers from {len(eligible_slots)} slots")
    if unique_proposers:
        logger.info(f"Sample proposers: {list(unique_proposers)[:10]}")
    
    selects = []
    validator_indices = list(validator_to_node.keys())
    if not validator_indices:
        logger.error("No validator indices found in network spec")
        return ""
    
    unknown_count = 0
    for proposer_index in unique_proposers:
        # If proposer not in our validator mapping, mark as unknown
        if proposer_index not in validator_to_node:
            unknown_count += 1
            logger.warning(f"Proposer {proposer_index} not in network spec validators (total validators: {len(validator_to_node)})")
            if unknown_count <= 5:  # Log first 5 for debugging
                logger.warning(f"Sample validator indices in spec: {list(validator_to_node.keys())[:10]}")
            select_sql = f"SELECT {proposer_index} AS proposer_index, 'unknown' AS node_type, 'unknown' AS cl_client, 'unknown' AS el_client"
            selects.append(select_sql)
            continue
            
        node_name = validator_to_node[proposer_index]
        
        # Get node characteristics (no caching in multi-threaded context)
        node_info = network_spec.get_node_info(node_name) or {}
        tags = network_spec.get_node_tags(node_name) or []
        node_is_supernode = 'supernode' in tags or node_info.get('attributes', {}).get('supernode', False)
        
        # Extract clients from tags
        cl = 'unknown'
        el = 'unknown'
        for tag in tags:
            if tag.startswith('cl:') and len(tag.split(':')) == 2:
                cl = tag.split(':')[1]
            elif tag.startswith('el:') and len(tag.split(':')) == 2:
                el = tag.split(':')[1]
        
        node_type = 'supernode' if node_is_supernode else 'regular'
        
        # Build SELECT for this proposer
        select_sql = f"SELECT {proposer_index} AS proposer_index, '{node_type}' AS node_type, '{cl}' AS cl_client, '{el}' AS el_client"
        selects.append(select_sql)
    
    if unknown_count > 0:
        logger.warning(f"Total unknown proposers: {unknown_count} out of {len(unique_proposers)}")
    
    logger.info(f"Built proposer map for {len(selects)} unique proposers")
    result = "\nUNION ALL\n".join(selects)
    return result


def load_reorg_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    eligible_slots: List[int],
    slot_to_block: Dict[int, str],
    slot_to_proposer: Dict[int, int] = None,
    mev_slots: List[int] = None,
    max_canonical_slot: int = None,
    proposer_type: Optional[str] = None,
    cl_filter: Optional[List[str]] = None,
    el_filter: Optional[List[str]] = None,
    grouping_dimension: Optional[str] = None,
    cluster_name: Optional[str] = None
) -> pd.DataFrame:
    """
    Load reorg rate data by comparing proposed vs canonical blocks.
    
    For each slot:
    1. Check if the proposed block exists in canonical_beacon_block
    2. If not, mark it as reorged
    3. Calculate reorg rates by group if grouping is specified
    
    Args:
        network: Network name
        start_date: Start of analysis period
        end_date: End of analysis period
        eligible_slots: List of slots to analyze
        slot_to_block: Mapping of slot to proposed block_root
        slot_to_proposer: Mapping of slot to proposer_index
        mev_slots: List of MEV slots for grouping
        max_canonical_slot: Maximum canonical slot (for filtering)
        proposer_type: Filter by proposer node type
        cl_filter: Filter by CL implementations
        el_filter: Filter by EL implementations
        grouping_dimension: Optional grouping dimension
        cluster_name: Optional cluster name
        
    Returns:
        DataFrame with reorg rate data by slot
    """
    logger.info(f"Loading reorg data for {network}, {len(eligible_slots)} slots")
    logger.info(f"Canonical max slot: {max_canonical_slot}")
    logger.info(f"Received {len(mev_slots) if mev_slots else 0} MEV slots for analysis")
    
    if not eligible_slots:
        logger.warning("No eligible slots provided")
        return pd.DataFrame()
    
    if max_canonical_slot is None:
        logger.error("max_canonical_slot is required for reorg analysis")
        return pd.DataFrame()
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return pd.DataFrame()
    
    # Get network spec for validator mapping
    network_spec = get_network_spec(network)
    logger.info(f"Network spec loaded: {network_spec is not None}, nodes: {len(network_spec.get_all_nodes()) if network_spec else 0}")
    
    try:
        params = {
            'network': network,
            'start_date': start_date,
            'end_date': end_date,
            'max_canonical_slot': max_canonical_slot
        }

        if grouping_dimension and grouping_dimension != 'none':
            # Grouping REQUIRES a network spec to work
            if not network_spec:
                st.error(f"""
                ❌ **Cannot use grouping for {network} - no network specification available**
                
                Grouping analysis requires a network specification file that maps validator indices
                to node names and client types. This file is missing for {network}.
                
                **Options:**
                1. Disable grouping to view overall reorg rates (select a different network first, then come back)
                2. Select a different network that has a network spec (e.g., holesky, sepolia, or any devnet)
                3. Contact the team to add a network spec YAML file for {network}
                
                **Note:** Mainnet and Gnosis typically don't have network specs as they're public networks.
                """)
                return pd.DataFrame()
            
            # Process slots in chunks to avoid query size limits with parallelization
            chunk_size = 500  # Process 500 slots at a time
            chunks = [eligible_slots[i:i + chunk_size] for i in range(0, len(eligible_slots), chunk_size)]
            
            # Capture all needed variables and functions in closure properly
            chunk_network = network
            chunk_proposer_type = proposer_type
            chunk_cl_filter = cl_filter
            chunk_el_filter = el_filter
            chunk_cluster_name = cluster_name
            chunk_grouping_dimension = grouping_dimension
            chunk_network_spec = network_spec
            chunk_slot_to_proposer = slot_to_proposer
            
            def process_chunk(chunk_data):
                chunk_idx, slot_chunk = chunk_data
                logger.info(f"Starting to process chunk {chunk_idx + 1} with {len(slot_chunk)} slots")
                
                # Import these outside the try block so they're available for error handling
                import sys
                import os
                import traceback
                
                try:
                    logger.info(f"Chunk {chunk_idx + 1}: Starting processing")
                    
                    # Import what we need - these should already be available since they're imported at the module level
                    # but we import them here for thread safety
                    from pages.analysis.reorg_rates.queries import build_proposer_filter, get_reorg_rates_grouped_query
                    from shared.ethereum.validator_filters import get_filtered_proposer_indices
                    from shared.database import get_database_connection
                    
                    # Import module to access module-level functions
                    logger.info(f"Chunk {chunk_idx + 1}: __name__ = {__name__}")
                    logger.info(f"Chunk {chunk_idx + 1}: Available modules: {list(sys.modules.keys())[:10]}...")
                    
                    # Try to get the current module
                    if __name__ in sys.modules:
                        current_module = sys.modules[__name__]
                    else:
                        # Fallback: import the module explicitly
                        logger.warning(f"Chunk {chunk_idx + 1}: __name__ not in sys.modules, importing explicitly")
                        import pages.analysis.reorg_rates.loader as current_module
                    
                    _build_proposer_map_union_selects_func = getattr(current_module, '_build_proposer_map_union_selects', None)
                    if not _build_proposer_map_union_selects_func:
                        logger.error(f"Chunk {chunk_idx + 1}: Could not find _build_proposer_map_union_selects function")
                        logger.error(f"Chunk {chunk_idx + 1}: Available functions in module: {dir(current_module)[:10]}...")
                        return None
                    
                    # Build proposer map for this chunk
                    logger.info(f"Chunk {chunk_idx + 1}: Building proposer map with network_spec={chunk_network_spec is not None}")
                    proposer_map_sql = _build_proposer_map_union_selects_func(chunk_network_spec, slot_chunk, chunk_slot_to_proposer)
                    logger.info(f"Chunk {chunk_idx + 1}: Proposer map SQL length: {len(proposer_map_sql) if proposer_map_sql else 0}")
                    
                    if not proposer_map_sql:
                        logger.warning(f"No proposer mapping for chunk {chunk_idx + 1} - network spec missing or invalid")
                        # For networks without spec, we can't do grouped analysis
                        logger.error(f"Cannot perform grouped analysis for {chunk_network} without network specification")
                        return None
                    
                    # Verify proposer_map_sql has SELECT statements
                    if 'SELECT' not in proposer_map_sql:
                        logger.error(f"Chunk {chunk_idx + 1}: Invalid proposer map SQL - no SELECT statements found")
                        return None

                    # Use the grouped query
                    sql = get_reorg_rates_grouped_query(group_by=chunk_grouping_dimension)
                    
                    # Replace template placeholders
                    sql = sql.replace('{{proposer_map_union_selects}}', proposer_map_sql)
                    
                    
                    # Apply proposer filter
                    try:
                        logger.info(f"Chunk {chunk_idx + 1}: Getting filtered proposer indices for network={chunk_network}, type={chunk_proposer_type}, cl={chunk_cl_filter}, el={chunk_el_filter}")
                        proposer_indices = get_filtered_proposer_indices(
                            network=chunk_network,
                            proposer_type=chunk_proposer_type,
                            cl_filter=chunk_cl_filter,
                            el_filter=chunk_el_filter
                        )
                        logger.info(f"Chunk {chunk_idx + 1}: Got {len(proposer_indices) if proposer_indices else 0} proposer indices")
                    except Exception as e:
                        logger.error(f"Chunk {chunk_idx + 1}: Error in get_filtered_proposer_indices: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        raise
                    
                    try:
                        chunk_proposer_filter = build_proposer_filter(proposer_indices)
                    except Exception as e:
                        logger.error(f"Chunk {chunk_idx + 1}: Error in build_proposer_filter: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        raise
                    
                    try:
                        # Replace ALL occurrences of {proposer_filter}
                        replacement = f"\n        {chunk_proposer_filter}" if chunk_proposer_filter else ''
                        count = 0
                        while '{{proposer_filter}}' in sql:
                            sql = sql.replace('{{proposer_filter}}', replacement, 1)
                            count += 1
                        if count > 0:
                            logger.info(f"Chunk {chunk_idx + 1}: Replaced {count} proposer_filter placeholder(s)")
                    except Exception as e:
                        logger.error(f"Chunk {chunk_idx + 1}: Error replacing proposer_filter: {e}")
                        logger.error(f"chunk_proposer_filter value: {chunk_proposer_filter}")
                        raise
                    
                    # Debug: Check if query still has unreplaced placeholders
                    if '{' in sql and '}' in sql:
                        logger.warning(f"Chunk {chunk_idx + 1}: Query may have unreplaced placeholders")
                        # Find and log any remaining placeholders
                        import re
                        placeholders = re.findall(r'\{[^}]+\}', sql)
                        if placeholders:
                            logger.error(f"Chunk {chunk_idx + 1}: Unreplaced placeholders found: {placeholders}")
                    
                    # Create new connection for this thread
                    chunk_conn = get_database_connection(chunk_cluster_name)
                    if not chunk_conn:
                        logger.error(f"Failed to get database connection for chunk {chunk_idx + 1}")
                        return None
                    
                    # Log the first part of the SQL for debugging
                    logger.info(f"Chunk {chunk_idx + 1}: Executing SQL with params: {list(params.keys())}")
                    logger.info(f"Chunk {chunk_idx + 1}: params values: {params}")
                    
                    # Check if we still need params - we've already replaced eligible_slots
                    # So we should still have network, start_date, end_date, max_canonical_slot as params
                    
                    # Check for any remaining parameter placeholders in SQL
                    import re
                    param_placeholders = re.findall(r'%\([^)]+\)s', sql)
                    if param_placeholders:
                        logger.info(f"Chunk {chunk_idx + 1}: Found parameter placeholders in SQL: {param_placeholders}")
                        # Check if all placeholders have corresponding params
                        for placeholder in param_placeholders:
                            param_name = placeholder[2:-2]  # Remove %( and )s
                            if param_name not in params:
                                logger.error(f"Chunk {chunk_idx + 1}: Missing param for placeholder: {placeholder}")
                    
                    logger.debug(f"Chunk {chunk_idx + 1}: First 1000 chars of SQL:\n{sql[:1000]}")
                    
                    # Check if SQL has any Python string formatting issues
                    try:
                        # Check for any remaining template placeholders that shouldn't be there
                        if '{{proposer_filter}}' in sql:
                            logger.error(f"Chunk {chunk_idx + 1}: CRITICAL - Unreplaced {{proposer_filter}} found in SQL!")
                            logger.error(f"SQL snippet around placeholder: {sql[max(0, sql.find('{{proposer_filter}}')-100):sql.find('{{proposer_filter}}')+100]}")
                            raise ValueError(f"Unreplaced {{proposer_filter}} placeholder in SQL")
                        
                        # Execute the SQL
                        chunk_df = pd.read_sql(sql, chunk_conn, params=params)
                    except NameError as ne:
                        logger.error(f"Chunk {chunk_idx + 1}: NameError during SQL execution: {ne}")
                        logger.error(f"SQL query first 2000 chars:\n{sql[:2000]}")
                        logger.error(f"Params: {params}")
                        raise
                    except Exception as e:
                        logger.error(f"Chunk {chunk_idx + 1}: Error during SQL execution: {e}")
                        if "proposer_filter" in str(e).lower():
                            logger.error(f"The error mentions 'proposer_filter' - checking SQL for unreplaced placeholders")
                            if '{{proposer_filter}}' in sql:
                                logger.error(f"Found unreplaced {{proposer_filter}} in SQL!")
                        raise
                    logger.info(f"Chunk {chunk_idx + 1} returned {len(chunk_df)} rows")
                    
                    return chunk_df if not chunk_df.empty else None
                    
                except NameError as e:
                    # Handle the undefined variable error with detailed traceback
                    error_msg = f"NameError in chunk {chunk_idx + 1}: {str(e)}"
                    logger.error(error_msg)
                    tb = traceback.format_exc()
                    logger.error(f"Chunk {chunk_idx + 1} full traceback:\n{tb}")
                    
                    # Log the SQL to understand what caused the error
                    logger.error(f"Chunk {chunk_idx + 1}: SQL when error occurred (first 3000 chars):\n{sql[:3000] if 'sql' in locals() else 'SQL not yet defined'}")
                    
                    # Try to identify which line caused the error
                    import sys
                    exc_info = sys.exc_info()
                    if exc_info[2]:
                        tb_frame = exc_info[2].tb_frame
                        logger.error(f"Error occurred in function: {tb_frame.f_code.co_name}")
                        logger.error(f"Local variables at error: {list(tb_frame.f_locals.keys())}")
                    
                    # Check if it's actually a SQL error disguised as NameError
                    if "proposer_filter" in str(e):
                        logger.error("This looks like a SQL template error, not a Python NameError")
                        logger.error(f"Check if the SQL has unreplaced {{proposer_filter}} placeholders")
                    
                    return {'error': error_msg, 'chunk': chunk_idx + 1, 'traceback': tb}
                except ImportError as e:
                    error_msg = f"ImportError: {str(e)}"
                    logger.error(f"Chunk {chunk_idx + 1} failed with import error: {error_msg}")
                    logger.error(f"Chunk {chunk_idx + 1} import traceback: {traceback.format_exc()}")
                    logger.error(f"sys.path: {sys.path}")
                    return {'error': error_msg, 'chunk': chunk_idx + 1, 'traceback': traceback.format_exc()}
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Chunk {chunk_idx + 1} failed with error: {error_msg}")
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
                        logger.error(f"Exception type: {type(e).__name__}")
                        logger.error(f"Full exception: {repr(e)}")
                        import traceback
                        logger.error(f"Future error traceback: {traceback.format_exc()}")
                        sql_errors.append({'error': str(e), 'chunk': chunk_idx + 1})
                
                # Show SQL errors if any
                if sql_errors:
                    for err in sql_errors[:1]:  # Show first error only to avoid spam
                        st.error(f"""
                        ❌ **SQL Query Error in chunk {err['chunk']}**
                        
                        {err['error']}
                        
                        This is likely due to missing data or a query issue.
                        """)
            
            if not all_dfs:
                return pd.DataFrame()
            
            # Combine all chunks
            df = pd.concat(all_dfs, ignore_index=True)
            logger.info(f"Combined {len(chunks)} chunks: {len(df)} total rows")

            # Add labels for grouping
            df['group_key'] = df['group_key'].astype(str)
            # Replace empty strings, None values, and '-' with 'unknown'
            df.loc[df['group_key'] == '', 'group_key'] = 'unknown'
            df.loc[df['group_key'] == 'None', 'group_key'] = 'unknown'
            df.loc[df['group_key'] == '-', 'group_key'] = 'unknown'
            df.loc[df['group_key'].isna(), 'group_key'] = 'unknown'
            
            if grouping_dimension == 'block_building':
                df['group_label'] = df['group_key'].map({'mev': 'Via MEV Relay', 'non-mev': 'Locally Built'}).fillna(df['group_key'])
            elif grouping_dimension == 'node_type':
                df['group_label'] = df['group_key'].map({
                    'supernode': 'Supernode', 
                    'regular': 'Regular Node',
                    'unknown': 'Unknown'
                }).fillna('Unknown')
            elif grouping_dimension == 'cl_client':
                df['group_label'] = df['group_key'].apply(lambda x: 'Unknown' if x in ['', 'unknown', 'None', '-', None] else x.title())
            elif grouping_dimension == 'el_client':
                df['group_label'] = df['group_key'].apply(lambda x: 'Unknown' if x in ['', 'unknown', 'None', '-', None] else x.title())
            elif grouping_dimension == 'cl_el_combined':
                def format_cl_el_combined(s):
                    if s in ['', 'unknown', 'None', '-', None]:
                        return 'Unknown'
                    if isinstance(s, str) and '-' in s:
                        return ' + '.join([p.title() for p in s.split('-')])
                    return 'Unknown'
                df['group_label'] = df['group_key'].apply(format_cl_el_combined)
            elif grouping_dimension == 'cl_node_type':
                def format_cl_node_type(s):
                    if s in ['', 'unknown', 'None', '-', None]:
                        return 'Unknown'
                    if isinstance(s, str) and '-' in s:
                        parts = s.split('-')
                        if len(parts) == 2:
                            cl, node_type = parts
                            node_type_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                            return f"{cl.title()} + {node_type_label}"
                    return 'Unknown'
                df['group_label'] = df['group_key'].apply(format_cl_node_type)
            elif grouping_dimension == 'node_type_mev':
                def format_node_type_mev(s):
                    if s in ['', 'unknown', 'None', '-', None]:
                        return 'Unknown'
                    if isinstance(s, str):
                        if s.endswith('-non-mev'):
                            node_type = s[:-8]  # Remove '-non-mev'
                            node_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                            return f"{node_label} (Locally built)"
                        elif s.endswith('-mev'):
                            node_type = s[:-4]  # Remove '-mev'
                            node_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                            return f"{node_label} (Via MEV)"
                    return 'Unknown'
                df['group_label'] = df['group_key'].apply(format_node_type_mev)
            elif grouping_dimension == 'cl_node_type_mev':
                def format_cl_node_type_mev(s):
                    if s in ['', 'unknown', 'None', '-', None]:
                        return 'Unknown'
                    if isinstance(s, str):
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
                    return 'Unknown'
                df['group_label'] = df['group_key'].apply(format_cl_node_type_mev)
            else:
                df['group_label'] = df['group_key'].apply(lambda x: 'Unknown' if x in ['', 'unknown', 'None', '-', None] else x)

            return df
        else:
            # Non-grouped per-slot computation
            proposer_indices = get_filtered_proposer_indices(
                network=network,
                proposer_type=proposer_type,
                cl_filter=cl_filter,
                el_filter=el_filter
            )
            proposer_filter = build_proposer_filter(proposer_indices)
            
            # Use the per-slot query
            sql = get_reorg_rates_query()
            replacement = f"\n        {proposer_filter}" if proposer_filter else ""
            sql = sql.replace("{{proposer_filter}}", replacement)
            
            df = pd.read_sql(sql, conn, params=params)

            if df.empty:
                st.warning("No reorg data found for the selected time range and filters.")
                return pd.DataFrame()

            return df

    except Exception as e:
        logger.error(f"Error loading reorg data: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return pd.DataFrame()


def validate_canonical_data_availability(
    network: str,
    start_date: datetime,
    end_date: datetime,
    cluster_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Check if canonical block data is available for the given time range.
    
    Returns:
        Dictionary with availability info and warnings about canonical table lag
    """
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return {'available': False, 'error': 'Database connection failed'}
    
    availability = {'available': True, 'warnings': []}
    
    # Check canonical blocks availability
    try:
        query = """
        SELECT 
            COUNT(*) as count,
            MIN(slot) as min_slot,
            MAX(slot) as max_slot,
            MAX(slot_start_date_time) as latest_time
        FROM canonical_beacon_block
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        """
        result = pd.read_sql(query, conn, params={'network': network, 'start_date': start_date, 'end_date': end_date})
        
        if result.empty or result['count'].iloc[0] == 0:
            availability['available'] = False
            availability['error'] = 'No canonical block data found for the selected time range'
        else:
            availability['canonical_blocks'] = result['count'].iloc[0]
            availability['slot_range'] = (result['min_slot'].iloc[0], result['max_slot'].iloc[0])
            availability['latest_canonical_time'] = result['latest_time'].iloc[0]
            
            # Calculate lag time
            if pd.notna(availability['latest_canonical_time']):
                latest_canonical = pd.to_datetime(availability['latest_canonical_time'])
                now = datetime.utcnow()
                lag_minutes = (now - latest_canonical).total_seconds() / 60
                availability['canonical_lag_minutes'] = lag_minutes
                
                if lag_minutes > 30:
                    availability['warnings'].append(f"Canonical data is {lag_minutes:.0f} minutes behind current time")
    except Exception as e:
        logger.warning(f"Failed to check canonical availability: {e}")
        availability['available'] = False
        availability['error'] = f'Error checking canonical data: {e}'
    
    # Check beacon API blocks availability
    try:
        query = """
        SELECT COUNT(*) as count
        FROM beacon_api_eth_v2_beacon_block
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        """
        result = pd.read_sql(query, conn, params={'network': network, 'start_date': start_date, 'end_date': end_date})
        availability['proposed_blocks'] = result['count'].iloc[0] if not result.empty else 0
    except Exception as e:
        logger.warning(f"Failed to check proposed blocks availability: {e}")
        availability['proposed_blocks'] = 0
    
    return availability