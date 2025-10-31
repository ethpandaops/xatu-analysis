"""
Data loader for PeerDAS analysis.

This module loads aggregated data directly from ClickHouse,
using the correct per-client, per-slot aggregation method.
"""

import pandas as pd
import streamlit as st
from datetime import datetime
from typing import Optional, Dict, Any
import logging

from shared.database import get_database_connection
from pages.analysis.peerdas_analysis.queries import (
    get_peerdas_query, 
    get_node_classification_raw_query, 
    get_max_blob_count_query,
    get_unique_clients_query
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@st.cache_data(ttl=300, show_spinner=False, persist=False)  # Cache for 5 minutes  
def load_peerdas_aggregated_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    data_source: str,
    aggregation: str = "p90",
    custody_filter: int = 128,
    cluster_name: Optional[str] = None,
    group_by: str = "blob_count",
    client_filter: Optional[list] = None
) -> pd.DataFrame:
    """
    Load pre-aggregated PeerDAS data with CORRECT per-client, per-slot calculation.
    
    Args:
        network: Network name
        start_date: Start of analysis period
        end_date: End of analysis period
        data_source: 'libp2p' or 'beacon_api'
        aggregation: Aggregation function ('mean', 'p50', 'p90', 'p95', 'p99')
        custody_filter: Maximum custody count to include
        cluster_name: Optional cluster name
        group_by: Metric to group by ('blob_count' or 'custody_count')
        client_filter: Optional list of client names to include
        
    Returns:
        DataFrame with columns: [metric], data_available_time, sample_count
    """
    
    logger.info(f"CACHE MISS - Loading PeerDAS data for {network}")
    logger.info(f"Period: {start_date} to {end_date}")
    logger.info(f"Data source: {data_source}, Aggregation: {aggregation}, Group by: {group_by}")
    logger.info(f"Custody filter: {custody_filter}, Cluster: {cluster_name}")
    
    try:
        # Get database connection
        conn = get_database_connection(cluster_name)
        
        # Get THE query (there's only one correct way)
        query = get_peerdas_query(data_source, aggregation, group_by, client_filter)
        
        # Query parameters
        params = {
            'network': network,
            'start_date': start_date,
            'end_date': end_date,
            'max_propagation': 12000,  # 12 seconds max propagation
            'custody_filter': custody_filter
        }
        
        # Add client filter to params if provided
        if client_filter:
            params['client_filter'] = tuple(client_filter)  # ClickHouse needs tuple for IN clause

        # Execute query
        logger.info("Executing PeerDAS query with per-client/per-slot aggregation...")
        df = pd.read_sql(query, conn, params=params)
        
        # Determine expected columns based on group_by
        metric_col = 'custody_count' if group_by == 'custody_count' else 'blob_count'
        
        if df.empty:
            logger.warning("No data returned from query")
            return pd.DataFrame(columns=[metric_col, 'data_available_time', 'sample_count'])
        
        # Rename aggregated_time to data_available_time for consistency
        if 'aggregated_time' in df.columns:
            df = df.rename(columns={'aggregated_time': 'data_available_time'})
        
        # Fill missing values
        df['sample_count'] = df['sample_count'].fillna(0)
        
        logger.info(f"Loaded {len(df)} rows")
        logger.info(f"{metric_col} values found: {sorted(df[metric_col].tolist())}")
        logger.info(f"Total samples: {df['sample_count'].sum():,}")
        
        return df
        
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        st.error(f"Failed to load data: {str(e)}")
        return pd.DataFrame()


@st.cache_data(ttl=300, persist=False, show_spinner=False)  # Cache for 5 minutes
def load_node_classification_raw_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    data_source: str,
    custody_filter: int = 128,
    cluster_name: Optional[str] = None,
    client_filter: Optional[list] = None
) -> pd.DataFrame:
    """
    Load raw PeerDAS data with node classification for box plots.
    
    Args:
        network: Network name
        start_date: Start of analysis period
        end_date: End of analysis period
        data_source: 'libp2p' or 'beacon_api'
        custody_filter: Maximum custody count to include
        cluster_name: Optional cluster name
        client_filter: Optional list of client names to include
        
    Returns:
        DataFrame with columns: blob_count, node_class, custody_count, data_available_time, meta_client_name
    """
    
    logger.info(f"CACHE MISS - Loading raw node classification data for {network}")
    logger.info(f"Period: {start_date} to {end_date}")
    logger.info(f"Data source: {data_source}, Custody filter: {custody_filter}, Cluster: {cluster_name}")
    
    try:
        # Get database connection
        conn = get_database_connection(cluster_name)
        
        # Get the raw query
        query = get_node_classification_raw_query(data_source, client_filter)
        
        # Query parameters
        params = {
            'network': network,
            'start_date': start_date,
            'end_date': end_date,
            'max_propagation': 12000,  # 12 seconds max propagation
            'custody_filter': custody_filter
        }
        
        # Add client filter to params if provided
        if client_filter:
            params['client_filter'] = tuple(client_filter)  # ClickHouse needs tuple for IN clause

        # Execute query
        logger.info("Executing raw node classification query...")
        df = pd.read_sql(query, conn, params=params)
        
        if df.empty:
            logger.warning("No data returned from query")
            return pd.DataFrame(columns=['blob_count', 'node_class', 'custody_count', 'data_available_time', 'meta_client_name'])
        
        logger.info(f"Loaded {len(df)} raw data points")
        logger.info(f"Node classes found: {df['node_class'].unique()}")
        logger.info(f"Blob counts found: {sorted(df['blob_count'].unique())}")
        
        return df
        
    except Exception as e:
        logger.error(f"Error loading raw data: {e}")
        st.error(f"Failed to load raw data: {str(e)}")
        return pd.DataFrame()


@st.cache_data(ttl=300, persist=False, show_spinner=False)  # Cache for 5 minutes
def get_max_blob_count(
    network: str,
    start_date: datetime,
    end_date: datetime,
    data_source: str,
    cluster_name: Optional[str] = None
) -> int:
    """
    Get the maximum blob count in the dataset.
    
    Args:
        network: Network name
        start_date: Start of analysis period
        end_date: End of analysis period
        data_source: 'libp2p' or 'beacon_api'
        cluster_name: Optional cluster name
        
    Returns:
        Maximum blob count in the dataset
    """
    
    # Check if this is a PeerDAS-enabled network
    if network.lower() == 'mainnet':
        logger.warning("PeerDAS not available on mainnet")
        return 6  # Default fallback
    
    try:
        # Get database connection
        conn = get_database_connection(cluster_name)
        
        # Get the query
        query = get_max_blob_count_query(data_source)
        
        # Query parameters
        params = {
            'network': network,
            'start_date': start_date,
            'end_date': end_date
        }
        
        # Execute query
        result = pd.read_sql(query, conn, params=params)
        
        if result.empty or result['max_blob_count'].iloc[0] is None:
            logger.warning("No blob count data found")
            return 6  # Default fallback
        
        max_count = int(result['max_blob_count'].iloc[0])
        logger.info(f"Max blob count in dataset: {max_count}")
        return max_count
        
    except Exception as e:
        error_msg = str(e)
        if 'UNKNOWN_TABLE' in error_msg or 'Unknown table' in error_msg:
            logger.warning(f"PeerDAS tables not found for {network}")
            return 6  # Default fallback
        logger.error(f"Error getting max blob count: {e}")
        return 6  # Default fallback


@st.cache_data(ttl=300, persist=False, show_spinner=False)  # Cache for 5 minutes
def get_unique_clients(
    network: str,
    start_date: datetime,
    end_date: datetime,
    data_source: str,
    cluster_name: Optional[str] = None
) -> list:
    """
    Get unique client names from the dataset.
    
    Args:
        network: Network name
        start_date: Start of analysis period
        end_date: End of analysis period
        data_source: 'libp2p' or 'beacon_api'
        cluster_name: Optional cluster name
        
    Returns:
        List of unique client names
    """
    
    try:
        # Get database connection
        conn = get_database_connection(cluster_name)
        
        # Get the query
        query = get_unique_clients_query(data_source)
        
        # Query parameters
        params = {
            'network': network,
            'start_date': start_date,
            'end_date': end_date
        }
        
        # Execute query
        result = pd.read_sql(query, conn, params=params)
        
        if result.empty:
            logger.warning("No client names found")
            return []
        
        client_names = result['meta_client_name'].tolist()
        logger.info(f"Found {len(client_names)} unique clients")
        return client_names
        
    except Exception as e:
        logger.error(f"Error getting unique clients: {e}")
        return []


@st.cache_data(ttl=300, persist=False, show_spinner=False)
def validate_data_availability(
    network: str,
    start_date: datetime, 
    end_date: datetime,
    data_source: str,
    cluster_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Quick validation to check if data exists for the selected parameters.
    """
    
    # Check if this is a PeerDAS-enabled network
    # PeerDAS is not available on mainnet yet
    if network.lower() == 'mainnet':
        return {
            'has_data': False,
            'error': 'PeerDAS is not yet available on mainnet. Please select a testnet/devnet that has PeerDAS enabled (e.g., fusaka-devnet-4, pectra-devnet-5).'
        }
    
    if data_source == 'libp2p':
        table = 'libp2p_gossipsub_data_column_sidecar FINAL'
    else:
        table = 'beacon_api_eth_v1_events_data_column_sidecar'
    
    # First check if the table exists
    table_check_query = f"""
    SELECT COUNT(*) as count
    FROM system.tables
    WHERE name = '{table.replace(' FINAL', '')}'
    """
    
    try:
        conn = get_database_connection(cluster_name)
        
        # Check if table exists
        table_result = pd.read_sql(table_check_query, conn)
        if table_result['count'].iloc[0] == 0:
            return {
                'has_data': False,
                'error': f'PeerDAS data not available for {network}. This network may not have PeerDAS enabled yet. Try networks like fusaka-devnet-4 or pectra-devnet-5.'
            }
        
        # If table exists, check for data
        query = f"""
        SELECT 
            COUNT(*) as total_rows,
            COUNT(DISTINCT slot) as unique_slots,
            COUNT(DISTINCT meta_client_name) as unique_clients,
            MIN(slot_start_date_time) as min_time,
            MAX(slot_start_date_time) as max_time
        FROM {table}
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND meta_client_name != ''
        """
        
        params = {
            'network': network,
            'start_date': start_date,
            'end_date': end_date
        }

        result = pd.read_sql(query, conn, params=params)

        return {
            'has_data': result['total_rows'].iloc[0] > 0,
            'total_rows': result['total_rows'].iloc[0],
            'unique_slots': result['unique_slots'].iloc[0],
            'unique_clients': result['unique_clients'].iloc[0],
            'min_time': result['min_time'].iloc[0],
            'max_time': result['max_time'].iloc[0]
        }
        
    except Exception as e:
        error_msg = str(e)
        if 'UNKNOWN_TABLE' in error_msg or 'Unknown table' in error_msg:
            return {
                'has_data': False,
                'error': f'PeerDAS data not available for {network}. This network may not have PeerDAS enabled yet. Try networks like fusaka-devnet-4 or pectra-devnet-5.'
            }
        logger.error(f"Error validating data: {e}")
        return {'has_data': False, 'error': str(e)}