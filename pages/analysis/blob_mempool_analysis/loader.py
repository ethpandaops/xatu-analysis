"""
Data loader for Blob Mempool Analysis.

This module handles loading and processing blob and mempool transaction data,
with caching and error handling for optimal performance.
"""

import pandas as pd
import polars as pl
import streamlit as st
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
import logging

from shared.database import get_database_connection
from shared.network_spec import get_network_spec
from pages.analysis.blob_mempool_analysis.queries import (
    get_canonical_blob_data_query,
    get_mempool_blob_data_query,
    get_combined_blob_analysis_query,
    get_blob_sidecar_data_query,
    get_client_list_query
)
from pages.analysis.blob_mempool_analysis.config_utils import get_analysis_config

# Configure logging
import os
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _calculate_slot_range(start_date: datetime, end_date: datetime, network: str) -> Tuple[int, int]:
    """
    Calculate slot range from datetime range.
    
    Args:
        start_date: Start datetime
        end_date: End datetime  
        network: Network name for genesis time
        
    Returns:
        Tuple of (start_slot, end_slot)
    """
    try:
        network_spec = get_network_spec(network)
        genesis_time = network_spec.get('genesis_time', 1606824023)  # Default to mainnet
        slot_duration = network_spec.get('slot_duration', 12)  # Default to 12 seconds
        
        start_slot = int((start_date.timestamp() - genesis_time) / slot_duration)
        end_slot = int((end_date.timestamp() - genesis_time) / slot_duration)
        
        return max(0, start_slot), max(start_slot, end_slot)
    except Exception as e:
        logger.warning(f"Error calculating slot range: {e}, using approximate calculation")
        # Fallback calculation
        duration_seconds = (end_date - start_date).total_seconds()
        slots_in_range = int(duration_seconds / 12)
        # Approximate current slot (this is rough)
        current_slot = int((datetime.utcnow().timestamp() - 1606824023) / 12)
        return max(0, current_slot - slots_in_range), current_slot


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_eligible_slots(
    network: str,
    start_date: datetime,
    end_date: datetime,
    cluster_name: Optional[str] = None
) -> List[int]:
    """
    Load eligible slots for the given time range.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        cluster_name: Database cluster name
        
    Returns:
        List of eligible slot numbers
    """
    logger.info(f"Loading eligible slots for network={network}")
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return []
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date
    }
    
    try:
        # Simple query to get slots
        query = """
        SELECT DISTINCT slot
        FROM beacon_api_eth_v2_beacon_block
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        ORDER BY slot
        """
        
        df = pd.read_sql(query, conn, params=params)
        if df.empty:
            logger.info(f"No eligible slots found for network {network}")
            return []
        
        slots = df['slot'].tolist()
        logger.info(f"Loaded {len(slots)} eligible slots")
        return slots
        
    except Exception as e:
        logger.error(f"Error loading eligible slots: {e}")
        st.warning(f"Could not load eligible slots: {str(e)}")
        return []


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_available_clients(
    network: str,
    start_date: datetime,
    end_date: datetime,
    cluster_name: Optional[str] = None
) -> List[str]:
    """
    Load available clients from mempool transaction data.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        cluster_name: Database cluster name
        
    Returns:
        List of available client names
    """
    logger.info(f"Loading available clients for network={network}")
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return []
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date
    }
    
    try:
        df = pd.read_sql(get_client_list_query(), conn, params=params)
        if df.empty:
            logger.info(f"No clients found for network {network}")
            return []
        
        clients = df['meta_client_name'].tolist()
        logger.info(f"Found {len(clients)} available clients")
        return clients
        
    except Exception as e:
        logger.error(f"Error loading available clients: {e}")
        st.warning(f"Could not load client list: {str(e)}")
        return []


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_canonical_blob_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    cluster_name: Optional[str] = None
) -> pd.DataFrame:
    """
    Load canonical blob data from beacon blocks.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        cluster_name: Database cluster name
        
    Returns:
        DataFrame with canonical blob data
    """
    logger.info(f"Loading canonical blob data for network={network}")
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return pd.DataFrame()
    
    start_slot, end_slot = _calculate_slot_range(start_date, end_date, network)
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
        'start_slot': start_slot,
        'end_slot': end_slot
    }
    
    try:
        df = pd.read_sql(get_canonical_blob_data_query(), conn, params=params)
        if df.empty:
            logger.info(f"No canonical blob data found for network {network}")
            return pd.DataFrame()
        
        logger.info(f"Loaded canonical blob data for {len(df)} slots")
        return df
        
    except Exception as e:
        logger.error(f"Error loading canonical blob data: {e}")
        st.warning(f"Could not load canonical blob data: {str(e)}")
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_mempool_blob_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    client_names: List[str],
    cluster_name: Optional[str] = None
) -> pd.DataFrame:
    """
    Load mempool blob transaction data.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        client_names: List of client names to include
        cluster_name: Database cluster name
        
    Returns:
        DataFrame with mempool blob data
    """
    logger.info(f"Loading mempool blob data for network={network}, clients={client_names}")
    
    if not client_names:
        logger.warning("No clients selected for mempool data")
        return pd.DataFrame()
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return pd.DataFrame()
    
    start_slot, end_slot = _calculate_slot_range(start_date, end_date, network)
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
        'start_slot': start_slot,
        'end_slot': end_slot,
        'client_names': tuple(client_names)  # ClickHouse expects tuple for IN clause
    }
    
    try:
        df = pd.read_sql(get_mempool_blob_data_query(), conn, params=params)
        if df.empty:
            logger.info(f"No mempool blob data found for network {network}")
            return pd.DataFrame()
        
        logger.info(f"Loaded mempool blob data for {len(df)} slot-client combinations")
        return df
        
    except Exception as e:
        logger.error(f"Error loading mempool blob data: {e}")
        st.warning(f"Could not load mempool blob data: {str(e)}")
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_combined_blob_analysis(
    network: str,
    start_date: datetime,
    end_date: datetime,
    client_names: List[str],
    cluster_name: Optional[str] = None
) -> pd.DataFrame:
    """
    Load combined blob analysis data (canonical + mempool).
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        client_names: List of client names to include
        cluster_name: Database cluster name
        
    Returns:
        DataFrame with combined analysis data
    """
    logger.info(f"Loading combined blob analysis for network={network}")
    
    if not client_names:
        logger.warning("No clients selected for analysis")
        return pd.DataFrame()
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return pd.DataFrame()
    
    start_slot, end_slot = _calculate_slot_range(start_date, end_date, network)
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
        'start_slot': start_slot,
        'end_slot': end_slot,
        'client_names': tuple(client_names)
    }
    
    try:
        # Debug: Log parameters
        logger.info(f"Debug - Network: {network}, Start: {start_date}, End: {end_date}")
        logger.info(f"Debug - Start slot: {start_slot}, End slot: {end_slot}")
        logger.info(f"Debug - Client names: {client_names}")
        
        # Load canonical data
        canonical_params = {
            'network': network,
            'start_date': start_date,
            'end_date': end_date,
            'start_slot': start_slot,
            'end_slot': end_slot
        }
        
        # First, check what data is available in the database
        logger.info("Debug - Checking available data in database...")
        availability_query = """
        SELECT 
            COUNT(*) as total_blocks,
            MIN(slot) as min_slot,
            MAX(slot) as max_slot,
            MIN(slot_start_date_time) as min_time,
            MAX(slot_start_date_time) as max_time
        FROM beacon_api_eth_v2_beacon_block
        WHERE meta_network_name = %(network)s
        """
        availability_df = pd.read_sql(availability_query, conn, params={'network': network})
        logger.info(f"Debug - Database availability: {availability_df.to_dict('records')}")
        
        # Check if there are any blocks in a wider time range around our target
        wider_query = """
        SELECT 
            COUNT(*) as blocks_in_wider_range,
            MIN(slot) as min_slot,
            MAX(slot) as max_slot
        FROM beacon_api_eth_v2_beacon_block
        WHERE meta_network_name = %(network)s
            AND slot BETWEEN %(start_slot)s - 1000 AND %(end_slot)s + 1000
        """
        wider_params = {
            'network': network,
            'start_slot': start_slot,
            'end_slot': end_slot
        }
        wider_df = pd.read_sql(wider_query, conn, params=wider_params)
        logger.info(f"Debug - Blocks in wider range (±1000 slots): {wider_df.to_dict('records')}")
        
        logger.info("Debug - Executing canonical data query...")
        canonical_query = get_combined_blob_analysis_query()
        logger.info(f"Debug - Canonical query: {canonical_query}")
        logger.info(f"Debug - Canonical params: {canonical_params}")
        
        # Test with a simple query first to verify parameters work
        test_query = """
        SELECT COUNT(*) as block_count
        FROM beacon_api_eth_v2_beacon_block
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND slot BETWEEN %(start_slot)s AND %(end_slot)s
        """
        test_df = pd.read_sql(test_query, conn, params=canonical_params)
        logger.info(f"Debug - Test query result: {test_df.to_dict('records')}")
        
        # Show what the query would look like with substituted parameters (for debugging)
        substituted_query = canonical_query
        for key, value in canonical_params.items():
            if isinstance(value, str):
                substituted_query = substituted_query.replace(f'%({key})s', f"'{value}'")
            else:
                substituted_query = substituted_query.replace(f'%({key})s', str(value))
        logger.info(f"Debug - Query with substituted params: {substituted_query}")
        
        canonical_df = pd.read_sql(canonical_query, conn, params=canonical_params)
        logger.info(f"Debug - Canonical data query returned {len(canonical_df)} records")
        
        if not canonical_df.empty:
            logger.info(f"Debug - Canonical data columns: {canonical_df.columns.tolist()}")
            logger.info(f"Debug - Canonical data sample: {canonical_df.head(2).to_dict('records')}")
            logger.info(f"Debug - Canonical slot range: {canonical_df['slot'].min()} to {canonical_df['slot'].max()}")
        else:
            logger.info(f"No canonical blob data found")
            return pd.DataFrame()
        
        # Load blob sidecar data
        logger.info("Debug - Executing blob sidecar data query...")
        blob_sidecar_query = get_blob_sidecar_data_query()
        logger.info(f"Debug - Blob sidecar query: {blob_sidecar_query}")
        logger.info(f"Debug - Blob sidecar params: {canonical_params}")
        
        blob_sidecar_df = pd.read_sql(blob_sidecar_query, conn, params=canonical_params)
        logger.info(f"Debug - Blob sidecar data query returned {len(blob_sidecar_df)} records")
        
        if not blob_sidecar_df.empty:
            logger.info(f"Debug - Blob sidecar data columns: {blob_sidecar_df.columns.tolist()}")
            logger.info(f"Debug - Blob sidecar data sample: {blob_sidecar_df.head(2).to_dict('records')}")
            logger.info(f"Debug - Blob sidecar slot range: {blob_sidecar_df['slot'].min()} to {blob_sidecar_df['slot'].max()}")
            logger.info(f"Debug - Blob sidecar total blob count: {blob_sidecar_df['blob_count'].sum()}")
        else:
            logger.warning("Debug - No blob sidecar data found!")
        
        # Merge blob sidecar data with canonical data
        if not blob_sidecar_df.empty:
            # Group blob data by slot and aggregate
            blob_agg = blob_sidecar_df.groupby('slot').agg({
                'blob_count': 'sum',
                'blob_hashes': lambda x: [item for sublist in x for item in sublist]  # Flatten lists
            }).reset_index()
            
            # Merge with canonical data
            canonical_df = canonical_df.merge(blob_agg, on='slot', how='left')
            canonical_df['canonical_blob_count'] = canonical_df['blob_count'].fillna(0)
            canonical_df['canonical_blob_hashes'] = canonical_df['blob_hashes'].fillna([])
            canonical_df = canonical_df.drop(['blob_count', 'blob_hashes'], axis=1)
            logger.info(f"Found blob data for {len(blob_agg)} slots")
        else:
            logger.info("No blob sidecar data found")
        
        # Load mempool data
        mempool_params = {
            'network': network,
            'start_date': start_date,
            'end_date': end_date
        }
        
        logger.info("Debug - Executing mempool data query...")
        mempool_query = get_mempool_blob_data_query(client_names)
        logger.info(f"Debug - Mempool query: {mempool_query}")
        logger.info(f"Debug - Mempool params: {mempool_params}")
        
        mempool_df = pd.read_sql(mempool_query, conn, params=mempool_params)
        logger.info(f"Debug - Mempool data query returned {len(mempool_df)} records")
        
        if not mempool_df.empty:
            logger.info(f"Debug - Mempool data columns: {mempool_df.columns.tolist()}")
            logger.info(f"Debug - Mempool data sample: {mempool_df.head(2).to_dict('records')}")
            logger.info(f"Debug - Mempool clients: {mempool_df['meta_client_name'].unique().tolist()}")
            logger.info(f"Debug - Mempool total transactions: {mempool_df['mempool_tx_count'].sum()}")
            logger.info(f"Debug - Mempool total blobs: {mempool_df['total_mempool_blobs'].sum()}")
        else:
            logger.warning("Debug - No mempool data found!")
        
        # Combine the data
        combined_data = []
        logger.info(f"Debug - Starting data combination: {len(canonical_df)} canonical rows × {len(mempool_df)} mempool rows")
        
        # If no mempool data, we still want to show canonical data
        if mempool_df.empty:
            logger.info("Debug - No mempool data, creating canonical-only records")
            for i, canonical_row in canonical_df.iterrows():
                combined_row = {
                    'slot': canonical_row['slot'],
                    'slot_start_date_time': canonical_row['slot_start_date_time'],
                    'block_root': canonical_row['block_root'],
                    'proposer_index': canonical_row['proposer_index'],
                    'canonical_blob_count': canonical_row.get('canonical_blob_count', 0),
                    'canonical_blob_hashes': canonical_row.get('canonical_blob_hashes', []),
                    'client_name': 'No Mempool Data',
                    'mempool_tx_count': 0,
                    'mempool_blob_count': 0,
                    'mempool_blob_hashes': [],
                    'avg_blob_gas': 0,
                    'avg_blob_gas_fee_cap': 0,
                    'total_blob_sidecars_size': 0,
                    'matching_blob_hashes': [],
                    'matching_blob_count': 0,
                    'match_percentage': 0
                }
                combined_data.append(combined_row)
        else:
            # Original combination logic
            for i, canonical_row in canonical_df.iterrows():
                for j, mempool_row in mempool_df.iterrows():
                    # Calculate matching blob hashes
                    canonical_hashes = canonical_row.get('canonical_blob_hashes', [])
                    mempool_hashes = mempool_row.get('all_mempool_blob_hashes', [])
                    
                    # Convert to sets for intersection
                    if isinstance(canonical_hashes, str):
                        canonical_hashes = eval(canonical_hashes) if canonical_hashes.startswith('[') else []
                    if isinstance(mempool_hashes, str):
                        mempool_hashes = eval(mempool_hashes) if mempool_hashes.startswith('[') else []
                    
                    matching_hashes = list(set(canonical_hashes) & set(mempool_hashes))
                    matching_count = len(matching_hashes)
                    
                    # Calculate match percentage
                    canonical_count = canonical_row.get('canonical_blob_count', 0)
                    match_percentage = (matching_count * 100.0 / canonical_count) if canonical_count > 0 else 0
                    
                    combined_row = {
                        'slot': canonical_row['slot'],
                        'slot_start_date_time': canonical_row['slot_start_date_time'],
                        'block_root': canonical_row['block_root'],
                        'proposer_index': canonical_row['proposer_index'],
                        'canonical_blob_count': canonical_count,
                        'canonical_blob_hashes': canonical_hashes,
                        'client_name': mempool_row['meta_client_name'],
                        'mempool_tx_count': mempool_row['mempool_tx_count'],
                        'mempool_blob_count': mempool_row['total_mempool_blobs'],
                        'mempool_blob_hashes': mempool_hashes,
                        'avg_blob_gas': mempool_row['avg_blob_gas'],
                        'avg_blob_gas_fee_cap': mempool_row['avg_blob_gas_fee_cap'],
                        'total_blob_sidecars_size': mempool_row['total_blob_sidecars_size'],
                        'matching_blob_hashes': matching_hashes,
                        'matching_blob_count': matching_count,
                        'match_percentage': match_percentage
                    }
                    combined_data.append(combined_row)
        
        logger.info(f"Debug - Generated {len(combined_data)} combined records")
        
        if not combined_data:
            logger.info(f"No combined data generated")
            return pd.DataFrame()
        
        df = pd.DataFrame(combined_data)
        
        # Convert datetime column
        if 'slot_start_date_time' in df.columns:
            df['slot_start_date_time'] = pd.to_datetime(df['slot_start_date_time'])
        
        logger.info(f"Debug - Final DataFrame shape: {df.shape}")
        logger.info(f"Debug - Final DataFrame columns: {df.columns.tolist()}")
        
        if not df.empty:
            logger.info(f"Debug - Final data sample: {df.head(2).to_dict('records')}")
            logger.info(f"Debug - Final slot range: {df['slot'].min()} to {df['slot'].max()}")
            logger.info(f"Debug - Final client names: {df['client_name'].unique().tolist()}")
            logger.info(f"Debug - Final canonical blob counts: {df['canonical_blob_count'].sum()}")
            logger.info(f"Debug - Final mempool blob counts: {df['mempool_blob_count'].sum()}")
            logger.info(f"Debug - Final matching blob counts: {df['matching_blob_count'].sum()}")
        else:
            logger.warning("Debug - Final DataFrame is empty!")
            
        logger.info(f"Loaded {len(df)} combined blob analysis records")
        return df
        
    except Exception as e:
        logger.error(f"Error loading combined blob analysis data: {e}")
        st.warning(f"Could not load blob analysis data: {str(e)}")
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_blob_inclusion_summary(
    network: str,
    start_date: datetime,
    end_date: datetime,
    client_names: List[str],
    cluster_name: Optional[str] = None
) -> pd.DataFrame:
    """
    Load blob inclusion summary statistics.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        client_names: List of client names to include
        cluster_name: Database cluster name
        
    Returns:
        DataFrame with summary statistics
    """
    logger.info(f"Loading blob inclusion summary for network={network}")
    
    if not client_names:
        logger.warning("No clients selected for summary")
        return pd.DataFrame()
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return pd.DataFrame()
    
    start_slot, end_slot = _calculate_slot_range(start_date, end_date, network)
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
        'start_slot': start_slot,
        'end_slot': end_slot,
        'client_names': tuple(client_names)
    }
    
    try:
        # Calculate summary statistics from combined data
        # This function is called after load_combined_blob_analysis, so we need to get the data
        # For now, return empty DataFrame - summary will be calculated in the main dashboard
        logger.info("Summary statistics will be calculated from combined data in main dashboard")
        return pd.DataFrame()
        
    except Exception as e:
        logger.error(f"Error loading inclusion summary: {e}")
        st.warning(f"Could not load summary data: {str(e)}")
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_blob_timeline_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    client_names: List[str],
    cluster_name: Optional[str] = None
) -> pd.DataFrame:
    """
    Load blob timeline data for visualization.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        client_names: List of client names to include
        cluster_name: Database cluster name
        
    Returns:
        DataFrame with timeline data
    """
    logger.info(f"Loading blob timeline data for network={network}")
    
    if not client_names:
        logger.warning("No clients selected for timeline")
        return pd.DataFrame()
    
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return pd.DataFrame()
    
    start_slot, end_slot = _calculate_slot_range(start_date, end_date, network)
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
        'start_slot': start_slot,
        'end_slot': end_slot,
        'client_names': tuple(client_names)
    }
    
    try:
        # For now, return empty DataFrame since we'll calculate timeline from combined data
        logger.info("Timeline will be calculated from combined data")
        return pd.DataFrame()
        
    except Exception as e:
        logger.error(f"Error loading timeline data: {e}")
        st.warning(f"Could not load timeline data: {str(e)}")
        return pd.DataFrame()


def validate_data_availability(
    network: str,
    start_date: datetime,
    end_date: datetime,
    cluster_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate data availability for the given parameters.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        cluster_name: Database cluster name
        
    Returns:
        Dictionary with availability status and details
    """
    logger.info(f"Validating data availability for network={network}")
    
    result = {
        "has_canonical_data": False,
        "has_mempool_data": False,
        "eligible_slots": 0,
        "available_clients": 0,
        "errors": []
    }
    
    try:
        # Check for eligible slots
        slots = load_eligible_slots(network, start_date, end_date, cluster_name)
        result["eligible_slots"] = len(slots)
        result["has_canonical_data"] = len(slots) > 0
        
        # Check for available clients
        clients = load_available_clients(network, start_date, end_date, cluster_name)
        result["available_clients"] = len(clients)
        result["has_mempool_data"] = len(clients) > 0
        
        if not result["has_canonical_data"]:
            result["errors"].append("No canonical blob data available for this time range")
        
        if not result["has_mempool_data"]:
            result["errors"].append("No mempool blob data available for this time range")
            
    except Exception as e:
        logger.error(f"Error validating data availability: {e}")
        result["errors"].append(f"Validation error: {str(e)}")
    
    return result

