import streamlit as st
import pandas as pd
import numpy as np
import os
import requests
import hashlib
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from pathlib import Path
import dotenv


def calculate_parquet_urls(start_date_str, end_date_str, network, table_name):
    """Calculate the parquet file URLs needed for a date range."""
    start_date = datetime.strptime(start_date_str.replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
    end_date = datetime.strptime(end_date_str.replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
    
    urls = []
    current_date = start_date.date()
    end_date_only = end_date.date()
    
    # Show what dates will be downloaded for user awareness
    date_count = (end_date_only - current_date).days + 1
    st.info(f"📅 Will download {date_count} day(s) from {current_date} to {end_date_only}")
    
    while current_date <= end_date_only:
        # Format: https://data.ethpandaops.io/xatu/NETWORK/databases/DATABASE/TABLE/YYYY/M/D.parquet
        url = f"https://data.ethpandaops.io/xatu/{network}/databases/default/{table_name}/{current_date.year}/{current_date.month}/{current_date.day}.parquet"
        urls.append((url, current_date))
        current_date += timedelta(days=1)
    
    return urls

def download_and_cache_parquet(url, cache_dir):
    """Download and cache a parquet file locally."""
    # Create a hash of the URL for the filename
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_file = cache_dir / f"{url_hash}.parquet"
    
    # Check if file exists and is recent (less than 1 day old)
    if cache_file.exists():
        file_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        if file_age < timedelta(days=1):
            try:
                return pd.read_parquet(cache_file)
            except Exception:
                # If file is corrupted, delete and re-download
                cache_file.unlink()
    
    # Download the file
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Save to cache
        with open(cache_file, 'wb') as f:
            f.write(response.content)
        
        # Read and return
        return pd.read_parquet(cache_file)
    except requests.exceptions.RequestException as e:
        st.warning(f"Could not download {url}: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)  # Cache for 1 hour
def load_blockprint_clients(network):
    """Load blockprint client information for validators."""
    connection = get_database_connection()
    if connection is None:
        return {}
        
    try:
        # Electra epoch 364032 = slot 11,649,024. Blockprint is broken after Electra.
        # We use pre-Electra blockprint data for ALL blocks by each validator.
        electra_slot = 364032 * 32  # 11,649,024
        
        blockprint_query = text("""
        WITH pre_electra_blockprint AS (
            SELECT DISTINCT
                proposer_index,
                argMax(best_guess_single, slot) as blockprint_client
            FROM
                default.beacon_block_classification
            WHERE
                slot < :electra_slot
            GROUP BY
                proposer_index
        ),
        all_validators AS (
            SELECT DISTINCT proposer_index
            FROM canonical_beacon_block
            WHERE meta_network_name = :network
        )
        
        SELECT
            av.proposer_index,
            COALESCE(peb.blockprint_client, 'unknown') AS blockprint_client
        FROM
            all_validators av
        LEFT JOIN
            pre_electra_blockprint peb ON peb.proposer_index = av.proposer_index
        """)
        
        result = connection.execute(blockprint_query, {"network": network, "electra_slot": electra_slot}).fetchall()
        
        # Convert to DataFrame
        blockprint_df = pd.DataFrame(result, columns=['proposer_index', 'blockprint_client'])
        
        # Create a dictionary with validator index as key and blockprint client as value
        blockprint_map = {}
        for _, row in blockprint_df.iterrows():
            client = row['blockprint_client']
            if client is None or pd.isna(client) or client == '':
                client = 'unknown'
            blockprint_map[row['proposer_index']] = client
        
        return blockprint_map
    finally:
        connection.close()

@st.cache_data(ttl=3600)  # Cache for 1 hour
def load_attestation_data_parquet(time_ranges_str, network):
    """Load attestation data from parquet files for the specified time ranges."""
    import ast
    time_ranges = ast.literal_eval(time_ranges_str)
    
    cache_dir = get_cache_dir()
    all_attestations = pd.DataFrame()
    
    for start_date, end_date in time_ranges:
        st.info(f"Loading attestation data from {start_date} to {end_date}...")
        
        # Calculate URLs for canonical_beacon_elaborated_attestation table
        urls = calculate_parquet_urls(start_date, end_date, network, "canonical_beacon_elaborated_attestation")
        
        for url, date in urls:
            st.info(f"Downloading data for {date}...")
            df = download_and_cache_parquet(url, cache_dir)
            
            if not df.empty:
                st.info(f"Downloaded {len(df)} attestation rows for {date}")
                
                # Filter by network first
                if 'meta_network_name' in df.columns:
                    # Debug: show what network values exist
                    unique_networks = df['meta_network_name'].unique()
                    st.info(f"Networks in attestation data: {unique_networks}")
                    st.info(f"Looking for network: '{network}'")
                    
                    # Handle both string and byte string network names
                    network_bytes = network.encode('utf-8')
                    df = df[(df['meta_network_name'] == network) | (df['meta_network_name'] == network_bytes)]
                    st.info(f"After network filter: {len(df)} rows")
                else:
                    st.info("No meta_network_name column found in attestations - skipping network filter")
                
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
                        st.info(f"Data time range: {data_min} to {data_max}")
                        st.info(f"Filter time range: {start_dt} to {end_dt}")
                    
                    # Apply the time filter
                    df = df[(df['slot_start_date_time'] >= start_dt) & 
                           (df['slot_start_date_time'] <= end_dt)]
                    st.info(f"After time filter: {len(df)} rows")
                
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

@st.cache_data(ttl=3600)  # Cache for 1 hour
def load_attestation_data(time_ranges_str, network):
    """Load attestation data for the specified time ranges."""
    import ast
    time_ranges = ast.literal_eval(time_ranges_str)
    
    connection = get_database_connection()
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

@st.cache_data(ttl=3600)  # Cache for 1 hour
def fetch_proposer_indices_parquet(time_ranges_str, network):
    """Fetch proposer indices from parquet files for the time ranges."""
    import ast
    time_ranges = ast.literal_eval(time_ranges_str)
    
    cache_dir = get_cache_dir()
    all_proposer_indices = []
    
    for start_date, end_date in time_ranges:
        st.info(f"Loading proposer data from {start_date} to {end_date}...")
        
        # Calculate URLs for canonical_beacon_block table
        urls = calculate_parquet_urls(start_date, end_date, network, "canonical_beacon_block")
        
        for url, date in urls:
            st.info(f"Downloading proposer data for {date}...")
            df = download_and_cache_parquet(url, cache_dir)
            
            if not df.empty:
                st.info(f"Downloaded {len(df)} rows for {date}")
                
                # Filter by network first
                if 'meta_network_name' in df.columns:
                    # Debug: show what network values exist
                    unique_networks = df['meta_network_name'].unique()
                    st.info(f"Networks in proposer data: {unique_networks}")
                    st.info(f"Looking for network: '{network}'")
                    
                    # Handle both string and byte string network names
                    network_bytes = network.encode('utf-8')
                    df = df[(df['meta_network_name'] == network) | (df['meta_network_name'] == network_bytes)]
                    st.info(f"After network filter: {len(df)} rows")
                else:
                    st.info("No meta_network_name column found in proposer data - skipping network filter")
                
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
                        st.info(f"Proposer data time range: {data_min} to {data_max}")
                        st.info(f"Proposer filter time range: {start_dt} to {end_dt}")
                    
                    df = df[(df['slot_start_date_time'] >= start_dt) & 
                           (df['slot_start_date_time'] <= end_dt)]
                    st.info(f"After time filter: {len(df)} rows")
                
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

@st.cache_data(ttl=3600)  # Cache for 1 hour
def fetch_proposer_indices(time_ranges_str, network):
    """Fetch proposer indices for the time ranges."""
    import ast
    time_ranges = ast.literal_eval(time_ranges_str)
    
    connection = get_database_connection()
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

def get_database_connection():
    """Create database connection."""
    try:
        username = os.getenv('XATU_CLICKHOUSE_USERNAME')
        password = os.getenv('XATU_CLICKHOUSE_PASSWORD')
        host = os.getenv('XATU_CLICKHOUSE_HOST')
        
        if not all([username, password, host]):
            st.error("Missing database credentials. Please check your .env file.")
            return None
            
        db_url = f"clickhouse+http://{username}:{password}@{host}:443/default?protocol=https"
        engine = create_engine(db_url)
        return engine.connect()
    except Exception as e:
        st.error(f"Failed to connect to database: {e}")
        return None
@st.cache_data(ttl=3600)  # Cache for 1 hour since entities don't change frequently
def load_validators_from_ethseer(network):
    """Load validators from the ethseer_validator_entity table for the specified network."""
    connection = get_database_connection()
    if connection is None:
        return {}
        
    try:
        # Query to fetch validator entities from ethseer
        proposer_query = text("""
            SELECT 
                `index` as proposer_index,
                entity
            FROM ethseer_validator_entity
            WHERE 
                meta_network_name = :network
        """)
        
        result = connection.execute(proposer_query, {"network": network}).fetchall()
        
        # Convert the result to a pandas DataFrame
        validator_entities_df = pd.DataFrame(result, columns=['proposer_index', 'entity'])
        
        # Convert the dataframe to a dictionary for easier lookup
        validators_map = {}
        for _, row in validator_entities_df.iterrows():
            entity = row['entity']
            if entity is None or pd.isna(entity) or entity == '':
                entity = 'unknown'
            validators_map[row['proposer_index']] = entity
        
        return validators_map
    finally:
        connection.close()

def get_cache_dir():
    """Get the cache directory for parquet files."""
    cache_dir = Path(".cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
