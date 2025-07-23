"""
Attestation data utilities for Ethereum beacon chain analysis

Functions for loading attestation data from both ClickHouse and parquet files.
"""
import ast
import pandas as pd
from sqlalchemy import text
from ..database import get_database_connection
from ..parquet_utils import calculate_parquet_urls, download_and_cache_parquet
from ..filesystem import get_cache_dir


def load_attestation_data(time_ranges_str, network):
    """Load attestation data for the specified time ranges from ClickHouse.
    
    Args:
        time_ranges_str (str): String representation of time ranges list
        network (str): Network name (mainnet, holesky, sepolia)
        
    Returns:
        pd.DataFrame: DataFrame with attestation data
    """
    time_ranges = ast.literal_eval(time_ranges_str)
    
    connection = get_database_connection(network)
    if connection is None:
        return pd.DataFrame()
    
    try:
        all_attestations = pd.DataFrame()
        
        for start_date, end_date in time_ranges:
            attestations_query = text("""
                SELECT
                    block_slot,
                    block_slot_start_date_time,
                    validators,
                    committee_index,
                    slot,
                    slot_start_date_time,
                    epoch,
                    position_in_block
                FROM canonical_beacon_elaborated_attestation
                WHERE
                    block_epoch_start_date_time BETWEEN toDateTime(:start_date, 'UTC') AND toDateTime(:end_date, 'UTC')
                    AND meta_network_name = :network
                ORDER BY block_slot ASC, position_in_block ASC
            """)

            result = connection.execute(attestations_query, {
                "start_date": start_date.replace('Z', ''), 
                "end_date": end_date.replace('Z', ''), 
                "network": network
            })
            
            current_attestations = pd.DataFrame(result.fetchall(), columns=[
                'block_slot', 'block_slot_start_date_time', 
                'validators', 'committee_index', 'slot', 'slot_start_date_time',
                'epoch', 'position_in_block'
            ])
            
            # Parse validators column if it's a string
            if len(current_attestations) > 0 and isinstance(current_attestations['validators'].iloc[0], str):
                current_attestations['validators'] = current_attestations['validators'].apply(
                    lambda x: eval(x) if isinstance(x, str) else x
                )

            all_attestations = pd.concat([all_attestations, current_attestations])
        
        return all_attestations
    finally:
        connection.close()


def load_attestation_data_parquet(time_ranges_str, network, progress_callback=None):
    """Load attestation data from parquet files for the specified time ranges.
    
    Args:
        time_ranges_str (str): String representation of time ranges list
        network (str): Network name (mainnet, holesky, sepolia)
        progress_callback (callable): Optional callback for progress updates (e.g., st.info)
        
    Returns:
        pd.DataFrame: DataFrame with attestation data
    """
    time_ranges = ast.literal_eval(time_ranges_str)
    
    cache_dir = get_cache_dir()
    all_attestations = pd.DataFrame()
    
    def log(message):
        if progress_callback:
            progress_callback(message)
    
    for start_date, end_date in time_ranges:
        log(f"Loading attestation data from {start_date} to {end_date}...")
        
        # Calculate URLs for canonical_beacon_elaborated_attestation table
        urls = calculate_parquet_urls(start_date, end_date, network, "canonical_beacon_elaborated_attestation")
        
        for url, date in urls:
            log(f"Downloading data for {date}...")
            df = download_and_cache_parquet(url, cache_dir)
            
            if not df.empty:
                log(f"Downloaded {len(df)} attestation rows for {date}")
                
                # Filter by network first
                if 'meta_network_name' in df.columns:
                    # Debug: show what network values exist
                    unique_networks = df['meta_network_name'].unique()
                    log(f"Networks in attestation data: {unique_networks}")
                    log(f"Looking for network: '{network}'")
                    
                    # Handle both string and byte string network names
                    network_bytes = network.encode('utf-8')
                    df = df[(df['meta_network_name'] == network) | (df['meta_network_name'] == network_bytes)]
                    log(f"After network filter: {len(df)} rows")
                else:
                    log("No meta_network_name column found in attestations - skipping network filter")
                
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
                        log(f"Data time range: {data_min} to {data_max}")
                        log(f"Filter time range: {start_dt} to {end_dt}")
                    
                    # Apply the time filter
                    df = df[(df['slot_start_date_time'] >= start_dt) & 
                           (df['slot_start_date_time'] <= end_dt)]
                    log(f"After time filter: {len(df)} rows")
                
                # Ensure block_slot_start_date_time is datetime
                if 'block_slot_start_date_time' in df.columns:
                    if pd.api.types.is_numeric_dtype(df['block_slot_start_date_time']):
                        df['block_slot_start_date_time'] = pd.to_datetime(df['block_slot_start_date_time'], unit='s')
                    else:
                        df['block_slot_start_date_time'] = pd.to_datetime(df['block_slot_start_date_time'])
                
                # Convert byte string columns to regular strings
                byte_string_columns = ['committee_index', 'meta_client_implementation']
                for col in byte_string_columns:
                    if col in df.columns and df[col].dtype == 'object':
                        df[col] = df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)
                
                # Select only the columns we need (equivalent to ClickHouse SELECT)
                required_columns = [
                    'block_slot', 'block_slot_start_date_time', 'validators', 
                    'committee_index', 'slot', 'slot_start_date_time', 
                    'epoch', 'position_in_block'
                ]
                
                # Only keep columns that exist in the dataframe
                available_columns = [col for col in required_columns if col in df.columns]
                if available_columns:
                    df = df[available_columns].copy()
                    
                    # Sort equivalent to ClickHouse ORDER BY
                    if 'block_slot' in df.columns and 'position_in_block' in df.columns:
                        df = df.sort_values(['block_slot', 'position_in_block'])
                    
                    all_attestations = pd.concat([all_attestations, df], ignore_index=True)
    
    # Parse validators column if it's a string
    if len(all_attestations) > 0 and 'validators' in all_attestations.columns:
        if isinstance(all_attestations['validators'].iloc[0], str):
            all_attestations['validators'] = all_attestations['validators'].apply(
                lambda x: eval(x) if isinstance(x, str) else x
            )
    
    return all_attestations