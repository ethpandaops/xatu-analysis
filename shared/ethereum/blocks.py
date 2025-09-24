"""
Block and proposer data utilities for Ethereum beacon chain analysis

Functions for loading block proposer information from both ClickHouse and parquet files.
"""
import ast
import pandas as pd
from sqlalchemy import text
from ..database import get_database_connection
from ..parquet_utils import calculate_parquet_urls, download_and_cache_parquet
from ..filesystem import get_cache_dir


def fetch_proposer_indices(time_ranges_str, network, cluster_name=None):
    """Fetch proposer indices for the time ranges from ClickHouse.
    
    Args:
        time_ranges_str (str): String representation of time ranges list
        network (str): Network name (mainnet, holesky, sepolia)
        cluster_name (str, optional): ClickHouse cluster name. If None, uses default cluster.
        
    Returns:
        pd.DataFrame: DataFrame with columns ['slot', 'proposer_index']
    """
    time_ranges = ast.literal_eval(time_ranges_str)
    
    connection = get_database_connection(cluster_name)
    if connection is None:
        return pd.DataFrame()
    
    try:
        all_proposer_indices = []
        
        for start_date, end_date in time_ranges:
            proposer_indices_query = text("""
                SELECT
                    slot,
                    proposer_index
                FROM canonical_beacon_block FINAL
                WHERE
                    slot_start_date_time BETWEEN toDateTime(:start_date, 'UTC') AND toDateTime(:end_date, 'UTC')
                    AND meta_network_name = :network
                ORDER BY slot ASC
            """)
            
            proposer_indices = pd.DataFrame(
                connection.execute(proposer_indices_query, {
                    "start_date": start_date.replace('Z', ''), 
                    "end_date": end_date.replace('Z', ''), 
                    "network": network
                }).fetchall(),
                columns=['slot', 'proposer_index']
            )
            all_proposer_indices.append(proposer_indices)
        
        return pd.concat(all_proposer_indices, ignore_index=True)
    finally:
        connection.close()


def fetch_proposer_indices_parquet(time_ranges_str, network, progress_callback=None):
    """Fetch proposer indices from parquet files for the time ranges.
    
    Args:
        time_ranges_str (str): String representation of time ranges list
        network (str): Network name (mainnet, holesky, sepolia)
        progress_callback (callable): Optional callback for progress updates (e.g., st.info)
        
    Returns:
        pd.DataFrame: DataFrame with columns ['slot', 'proposer_index']
    """
    time_ranges = ast.literal_eval(time_ranges_str)
    
    cache_dir = get_cache_dir()
    all_proposer_indices = []
    
    def log(message):
        if progress_callback:
            progress_callback(message)
    
    for start_date, end_date in time_ranges:
        log(f"Loading proposer data from {start_date} to {end_date}...")
        
        # Calculate URLs for canonical_beacon_block table
        urls = calculate_parquet_urls(start_date, end_date, network, "canonical_beacon_block")
        
        for url, date in urls:
            log(f"Downloading proposer data for {date}...")
            df = download_and_cache_parquet(url, cache_dir)
            
            if not df.empty:
                log(f"Downloaded {len(df)} rows for {date}")
                
                # Filter by network first
                if 'meta_network_name' in df.columns:
                    # Debug: show what network values exist
                    unique_networks = df['meta_network_name'].unique()
                    log(f"Networks in proposer data: {unique_networks}")
                    log(f"Looking for network: '{network}'")
                    
                    # Handle both string and byte string network names
                    network_bytes = network.encode('utf-8')
                    df = df[(df['meta_network_name'] == network) | (df['meta_network_name'] == network_bytes)]
                    log(f"After network filter: {len(df)} rows")
                else:
                    log("No meta_network_name column found in proposer data - skipping network filter")
                
                # Apply time filtering using slot_start_date_time
                if 'slot_start_date_time' in df.columns:
                    # Check if timestamps are Unix timestamps (numeric)
                    if pd.api.types.is_numeric_dtype(df['slot_start_date_time']):
                        # Convert Unix timestamp to datetime (assuming seconds)
                        df['slot_start_date_time'] = pd.to_datetime(df['slot_start_date_time'], unit='s')
                    else:
                        df['slot_start_date_time'] = pd.to_datetime(df['slot_start_date_time'])
                    
                    start_dt = pd.to_datetime(start_date.replace('Z', ''))
                    end_dt = pd.to_datetime(end_date.replace('Z', ''))
                    
                    # Debug: show date range info
                    if len(df) > 0:
                        data_min = df['slot_start_date_time'].min()
                        data_max = df['slot_start_date_time'].max()
                        log(f"Proposer data time range: {data_min} to {data_max}")
                        log(f"Proposer filter time range: {start_dt} to {end_dt}")
                    
                    df = df[(df['slot_start_date_time'] >= start_dt) & 
                           (df['slot_start_date_time'] <= end_dt)]
                    log(f"After time filter: {len(df)} rows")
                
                # Convert byte string columns to regular strings  
                byte_string_columns = ['proposer_index']
                for col in byte_string_columns:
                    if col in df.columns and df[col].dtype == 'object':
                        df[col] = df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)
                
                # Select only the columns we need
                required_columns = ['slot', 'proposer_index']
                available_columns = [col for col in required_columns if col in df.columns]
                
                if available_columns:
                    df = df[available_columns].copy()
                    
                    # Sort by slot
                    if 'slot' in df.columns:
                        df = df.sort_values('slot')
                    
                    all_proposer_indices.append(df)
    
    if all_proposer_indices:
        return pd.concat(all_proposer_indices, ignore_index=True)
    else:
        return pd.DataFrame(columns=['slot', 'proposer_index'])