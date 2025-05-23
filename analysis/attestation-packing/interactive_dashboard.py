#!/usr/bin/env python3
"""
Interactive Attestation Packing Analysis Dashboard

This Streamlit app provides an interactive interface for analyzing attestation packing metrics
from the Ethereum beacon chain. Users can select different parameters and view metrics dynamically.

Run with: streamlit run interactive_dashboard.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import os
import requests
import hashlib
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from pathlib import Path
import dotenv

# Load environment variables
dotenv.load_dotenv()

# Set page configuration with light theme
st.set_page_config(
    page_title="Attestation Packing Analysis",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for minimal branding (working with Streamlit's default light theme)
st.markdown("""
<style>
    
    /* Main header styling */
    .main-header {
        text-align: center;
        color: #1e40af;
        border-bottom: 3px solid #3b82f6;
        padding-bottom: 1rem;
        margin-bottom: 2rem;
    }
    
    /* Metric cards */
    .metric-card {
        background: #f8fafc;
        padding: 1.5rem;
        border-radius: 10px;
        border: 1px solid #e2e8f0;
        margin: 0.5rem 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    /* Metric description box */
    .metric-description {
        background: #eff6ff;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
        border-left: 4px solid #3b82f6;
    }
    
    .metric-title {
        font-size: 1.2rem;
        font-weight: 600;
        color: #1e40af;
        margin-bottom: 0.5rem;
    }
    
    .metric-subtitle {
        color: #475569;
        line-height: 1.5;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False
if 'slot_metrics_df' not in st.session_state:
    st.session_state.slot_metrics_df = None
if 'validators' not in st.session_state:
    st.session_state.validators = {}
if 'last_config' not in st.session_state:
    st.session_state.last_config = None

def get_cache_dir():
    """Get the cache directory for parquet files."""
    cache_dir = Path(".cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

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

def add_ethpandaops_logo(fig):
    """Add EthPandaOps logo to a plotly figure."""
    # Logo functionality disabled
    return fig

def get_metric_info(metric_name):
    """Get human-readable title and description for metrics."""
    metric_info = {
        "unique_validator_indexes": {
            "title": "Unique Validators Per Block",
            "subtitle": "Total number of unique validators that submitted attestations included in each block. Higher values indicate better validator participation and network health."
        },
        "first_seen_attestations": {
            "title": "Fresh Attestations",
            "subtitle": "Number of attestations the client included in the block that had never been seen before. Measures how much 'new' attestation data each block contributes to the chain."
        },
        "avg_attestation_inclusion_delay": {
            "title": "Average Inclusion Delay",
            "subtitle": "Average number of slots between when an attestation was supposed to be included (slot + 1) and when it actually appeared in a block. Lower is better for network efficiency."
        },
        "optimal_inclusion_rate": {
            "title": "Optimal Inclusion Rate",
            "subtitle": "Percentage of validators whose attestations were included with just 1-slot delay (optimal timing). Higher rates indicate better network performance and proposer efficiency."
        },
        "min_attestation_inclusion_delay": {
            "title": "Minimum Inclusion Delay",
            "subtitle": "The shortest delay for any attestation in the block. Shows the best-case inclusion performance for that block."
        },
        "p50_attestation_inclusion_delay": {
            "title": "Median Inclusion Delay",
            "subtitle": "The middle value (50th percentile) of all inclusion delays in the block. Provides a robust measure of typical inclusion performance."
        },
        "p95_attestation_inclusion_delay": {
            "title": "95th Percentile Inclusion Delay",
            "subtitle": "The delay below which 95% of attestations fall. Helps identify outliers and worst-case inclusion scenarios."
        },
        "max_attestation_inclusion_delay": {
            "title": "Maximum Inclusion Delay",
            "subtitle": "The longest delay for any attestation in the block. Shows worst-case inclusion performance and potential network issues."
        },
        "aggregation_efficiency": {
            "title": "Aggregation Efficiency",
            "subtitle": "Ratio of unique validators to total attestations. Higher values mean better aggregation - fewer attestation objects needed to represent the same validator participation."
        },
        "total_attestations": {
            "title": "Total Attestations",
            "subtitle": "Total number of attestation objects included in each block. Lower numbers (with same validator participation) indicate better aggregation."
        },
        "avg_validators_per_attestation": {
            "title": "Average Validators Per Attestation",
            "subtitle": "Average number of validators represented by each attestation object. Higher values indicate better signature aggregation efficiency."
        },
        "optimal_inclusion_validators": {
            "title": "Optimal Inclusion Validators",
            "subtitle": "Number of validators whose attestations were included with optimal 1-slot delay. Measures absolute count (not percentage) of well-included validators."
        }
    }
    
    return metric_info.get(metric_name, {
        "title": metric_name.replace('_', ' ').title(),
        "subtitle": "No description available for this metric."
    })

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

def calculate_first_seen_attestations(df):
    """
    Calculate first_seen_attestations for each block using a rolling window approach.
    Maintains a 65-slot rolling window to track previously seen validator attestations.
    """
    print("🔍 Calculating first seen attestations with rolling window...")
    
    # Sort by block_slot and slot for chronological processing
    df_sorted = df.sort_values(['block_slot', 'slot']).copy()
    
    # Dictionary to track seen attestations: {slot: {validator_index: True}}
    seen_attestations = {}
    
    # Dictionary to store first seen counts per block
    block_first_seen = {}
    
    # Process each attestation chronologically
    for _, row in df_sorted.iterrows():
        block_slot = row['block_slot']
        attestation_slot = row['slot']
        validator_indexes = row['validators']
        
        # Parse validators column if needed
        if isinstance(validator_indexes, str) and validator_indexes.startswith('['):
            import ast
            try:
                validator_indexes = ast.literal_eval(validator_indexes)
            except:
                validator_indexes = []
        elif not isinstance(validator_indexes, list):
            validator_indexes = list(validator_indexes) if hasattr(validator_indexes, '__iter__') else []
        
        # Clean up old slots (keep only last 65 slots)
        current_slots = list(seen_attestations.keys())
        for slot in current_slots:
            if block_slot - slot > 65:
                del seen_attestations[slot]
        
        # Count validators in this attestation not seen before for this slot
        first_seen_count = 0
        for validator_idx in validator_indexes:
            if attestation_slot not in seen_attestations or validator_idx not in seen_attestations[attestation_slot]:
                first_seen_count += 1
                # Initialize the slot dictionary if needed
                if attestation_slot not in seen_attestations:
                    seen_attestations[attestation_slot] = {}
                # Mark this validator as having attested for this slot
                seen_attestations[attestation_slot][validator_idx] = True
        
        # Add to block's first seen count
        if block_slot not in block_first_seen:
            block_first_seen[block_slot] = 0
        block_first_seen[block_slot] += first_seen_count
    
    print(f"✅ Calculated first seen attestations for {len(block_first_seen)} blocks")
    return block_first_seen

def calculate_slot_metrics(group):
    """Calculate metrics for a single block slot."""
    if group.empty:
        return pd.Series({
            'unique_validator_indexes': 0,
            'unique_committees': 0,
            'total_attestations': 0,
            'optimal_inclusion_validators': 0,
            'optimal_inclusion_rate': 0,
            'avg_validators_per_attestation': np.nan,
            'max_validators_per_attestation': np.nan,
            'min_attestation_inclusion_delay': np.nan,
            'avg_attestation_inclusion_delay': np.nan,
            'p50_attestation_inclusion_delay': np.nan,
            'p95_attestation_inclusion_delay': np.nan,
            'max_attestation_inclusion_delay': np.nan,
            'aggregation_efficiency': np.nan,
            'first_seen_attestations': 0,
            'block_slot_start_date_time': pd.NaT
        })

    # Get block_slot from the group's name (since it was the grouping key)
    block_slot = group.name if hasattr(group, 'name') else group['block_slot'].iloc[0]
    
    # Calculate temporary series needed for metrics
    attestation_delay = block_slot - group['slot']

    # Explode validators for unique count
    validators_list = group['validators'].tolist()
    flat_validators = []
    
    for validator_array in validators_list:
        if isinstance(validator_array, (list, np.ndarray)):
            flat_validators.extend(validator_array)
        elif isinstance(validator_array, str) and validator_array.startswith('['):
            import ast
            try:
                parsed = ast.literal_eval(validator_array)
                if isinstance(parsed, list):
                    flat_validators.extend(parsed)
            except:
                pass
    
    all_validators_in_slot = np.unique(np.array(flat_validators))
    unique_validator_count = len(all_validators_in_slot)

    # optimal_inclusion_validators - count unique validators with delay=1
    optimal_inclusion_mask = attestation_delay == 1
    optimal_inclusion_group = group[optimal_inclusion_mask]
    
    optimal_inclusion_validators_list = []
    for validator_array in optimal_inclusion_group['validators'].tolist():
        if isinstance(validator_array, (list, np.ndarray)):
            optimal_inclusion_validators_list.extend(validator_array)
        elif isinstance(validator_array, str) and validator_array.startswith('['):
            import ast
            try:
                parsed = ast.literal_eval(validator_array)
                if isinstance(parsed, list):
                    optimal_inclusion_validators_list.extend(parsed)
            except:
                pass
    
    optimal_inclusion_validators = len(np.unique(np.array(optimal_inclusion_validators_list))) if optimal_inclusion_validators_list else 0
    optimal_inclusion_rate = optimal_inclusion_validators / unique_validator_count if unique_validator_count > 0 else 0

    num_signatures = group['validators'].apply(len)
    total_attestations_count = len(group)

    metrics = {
        'unique_validator_indexes': unique_validator_count,
        'unique_committees': group['committee_index'].nunique(),
        'total_attestations': total_attestations_count,
        'optimal_inclusion_validators': optimal_inclusion_validators,
        'optimal_inclusion_rate': optimal_inclusion_rate,
        'avg_validators_per_attestation': num_signatures.mean(),
        'max_validators_per_attestation': num_signatures.max(),
        'min_attestation_inclusion_delay': attestation_delay.min(),
        'avg_attestation_inclusion_delay': attestation_delay.mean(),
        'p50_attestation_inclusion_delay': attestation_delay.quantile(0.50),
        'p95_attestation_inclusion_delay': attestation_delay.quantile(0.95),
        'max_attestation_inclusion_delay': attestation_delay.max(),
        'first_seen_attestations': 0,  # Will be populated separately
        'block_slot_start_date_time': group['block_slot_start_date_time'].iloc[0]
    }

    # Derived metric
    if total_attestations_count > 0:
        metrics['aggregation_efficiency'] = unique_validator_count / total_attestations_count
    else:
        metrics['aggregation_efficiency'] = np.nan

    return pd.Series(metrics)

def create_before_after_comparison(data, metric, clients, event_date):
    """Create a before/after comparison plot using Plotly."""
    temp_df = data.copy()
    temp_df = temp_df[temp_df['client'].isin(clients)]
    
    # Get metric info for better titles
    metric_info = get_metric_info(metric)
    
    # Add period information
    temp_df['datetime'] = pd.to_datetime(temp_df['block_slot_start_date_time'])
    event_date_naive = pd.Timestamp(event_date).tz_localize(None) if hasattr(event_date, 'tzinfo') and event_date.tzinfo is not None else event_date
    temp_df['period'] = np.where(temp_df['datetime'] < event_date_naive, 'Before', 'After')
    
    # Calculate mean for each client and period
    client_metrics = temp_df.groupby(['client', 'period'])[metric].mean().reset_index()
    
    # Create the plot with simple styling
    fig = px.bar(
        client_metrics, 
        x='client', 
        y=metric, 
        color='period',
        barmode='group',
        title=f'{metric_info["title"]} - Before vs After Comparison<br><sub>{metric_info["subtitle"]}</sub>',
        labels={'client': 'Consensus Client', metric: metric_info["title"]}
    )
    
    # Minimal layout updates
    fig.update_layout(
        xaxis_tickangle=-45,
        height=500,
        showlegend=True,
        title={'font': {'size': 16}}
    )
    
    # Add EthPandaOps logo
    return add_ethpandaops_logo(fig)

def create_distribution_plot(data, metric, clients, event_date):
    """Create a before/after distribution plot using Plotly."""
    temp_df = data[data['client'].isin(clients)].copy()
    
    # Get metric info for better titles
    metric_info = get_metric_info(metric)
    
    # Add period information
    temp_df['datetime'] = pd.to_datetime(temp_df['block_slot_start_date_time'])
    event_date_naive = pd.Timestamp(event_date).tz_localize(None) if hasattr(event_date, 'tzinfo') and event_date.tzinfo is not None else event_date
    temp_df['period'] = np.where(temp_df['datetime'] < event_date_naive, 'Before', 'After')
    
    fig = px.box(
        temp_df, 
        x='client', 
        y=metric,
        color='period',
        title=f'{metric_info["title"]} - Distribution Analysis<br><sub>{metric_info["subtitle"]}</sub>',
        labels={'client': 'Consensus Client', metric: metric_info["title"]}
    )
    
    # Minimal layout updates
    fig.update_layout(
        xaxis_tickangle=-45,
        height=500,
        title={'font': {'size': 16}}
    )
    
    # Add EthPandaOps logo
    return add_ethpandaops_logo(fig)

def create_time_series_plot(data, metric, clients, event_date):
    """Create a time series plot using Plotly."""
    temp_df = data[data['client'].isin(clients)].copy()
    temp_df['datetime'] = pd.to_datetime(temp_df['block_slot_start_date_time'])
    
    # Get metric info for better titles
    metric_info = get_metric_info(metric)
    
    fig = px.scatter(
        temp_df, 
        x='datetime', 
        y=metric, 
        color='client',
        title=f'{metric_info["title"]} - Time Series Analysis<br><sub>{metric_info["subtitle"]}</sub>',
        labels={'datetime': 'Date/Time', metric: metric_info["title"]}
    )
    
    # Add vertical line for event date
    # Convert to datetime object that plotly can handle
    try:
        if hasattr(event_date, 'tzinfo') and event_date.tzinfo is not None:
            event_date_dt = event_date.replace(tzinfo=None)
        else:
            event_date_dt = pd.to_datetime(event_date)
            if hasattr(event_date_dt, 'tz_localize'):
                event_date_dt = event_date_dt.tz_localize(None)
        
        fig.add_vline(x=event_date_dt, line_dash="dash", line_color="red", 
                      annotation_text="Event Date")
    except Exception as e:
        # If datetime conversion fails, skip the vertical line
        st.warning(f"Could not add event date line: {e}")
    
    # Minimal layout updates
    fig.update_layout(
        height=500,
        title={'font': {'size': 16}}
    )
    
    # Add EthPandaOps logo
    return add_ethpandaops_logo(fig)

def create_inclusion_distance_distribution(data, clients, event_date):
    """Create an inclusion distance distribution plot similar to the blog post."""
    temp_df = data[data['client'].isin(clients)].copy()
    
    # Add period information
    temp_df['datetime'] = pd.to_datetime(temp_df['block_slot_start_date_time'])
    event_date_naive = pd.Timestamp(event_date).tz_localize(None) if hasattr(event_date, 'tzinfo') and event_date.tzinfo is not None else event_date
    temp_df['period'] = np.where(temp_df['datetime'] < event_date_naive, 'Before', 'After')
    
    # Create histogram data for different inclusion delays
    delay_metrics = [col for col in temp_df.columns if col.startswith('delay_') and col.endswith('_count')]
    
    # Create description for inclusion delay distribution
    delay_description = "Shows the distribution of how many slots elapsed between when attestations should have been included (slot + 1) and when they actually appeared in blocks. Lower delays indicate better network performance."
    
    if not delay_metrics:
        # If we don't have delay count metrics, create a simple distribution
        fig = px.histogram(
            temp_df, 
            x='avg_attestation_inclusion_delay', 
            color='period',
            nbins=20,
            title=f'Attestation Inclusion Delay Distribution<br><sub>{delay_description}</sub>',
            labels={'avg_attestation_inclusion_delay': 'Average Inclusion Delay (slots)'}
        )
    else:
        # Create a more detailed delay distribution
        delay_data = []
        for period in ['Before', 'After']:
            period_data = temp_df[temp_df['period'] == period]
            for delay_col in delay_metrics:
                delay_num = int(delay_col.split('_')[1])
                count = period_data[delay_col].sum()
                if count > 0:
                    delay_data.append({
                        'period': period,
                        'inclusion_delay': delay_num,
                        'count': count
                    })
        
        if delay_data:
            delay_df = pd.DataFrame(delay_data)
            fig = px.bar(
                delay_df,
                x='inclusion_delay',
                y='count',
                color='period',
                barmode='group',
                title=f'Attestation Inclusion Delay Distribution<br><sub>{delay_description}</sub>',
                labels={'inclusion_delay': 'Inclusion Delay (slots)', 'count': 'Number of Attestations'}
            )
        else:
            # Fallback to simple histogram
            fig = px.histogram(
                temp_df, 
                x='avg_attestation_inclusion_delay', 
                color='period',
                nbins=20,
                title=f'Attestation Inclusion Delay Distribution<br><sub>{delay_description}</sub>',
                labels={'avg_attestation_inclusion_delay': 'Average Inclusion Delay (slots)'}
            )
    
    # Minimal layout updates
    fig.update_layout(
        height=500,
        title={'font': {'size': 16}}
    )
    
    # Add EthPandaOps logo
    return add_ethpandaops_logo(fig)

def main():
    
    # Header
    st.markdown('<h1 class="main-header">🔍 Attestation Packing Analysis Dashboard</h1>', unsafe_allow_html=True)
    
    # Sidebar configuration
    st.sidebar.header("⚙️ Configuration")
    
    # Network selection
    network = st.sidebar.selectbox(
        "Select Network",
        ["mainnet", "holesky", "sepolia"],
        index=0
    )
    
    # Time range configuration
    st.sidebar.subheader("Time Range Configuration")
    
    # Predefined time ranges
    time_range_option = st.sidebar.selectbox(
        "Select Time Range",
        ["Custom", "Mainnet Electra Fork Analysis (May 2025)", "Recent Week", "Recent Month"]
    )
    
    if time_range_option == "Mainnet Electra Fork Analysis (May 2025)":
        time_ranges = [
            ("2025-05-01T12:10:00Z", "2025-05-01T18:10:00Z"),  # Pre-Electra
            ("2025-05-20T12:10:00Z", "2025-05-20T18:10:00Z")   # Post-Electra
        ]
        event_date = pd.to_datetime("2025-05-07T10:00:00Z", utc=True)
    elif time_range_option == "Custom":
        st.sidebar.info("⚠️ Custom ranges download ALL days between start/end. For analysis, use 2 separate short periods.")
        
        custom_type = st.sidebar.radio(
            "Custom Range Type",
            ["Single Period", "Before/After Analysis"]
        )
        
        if custom_type == "Single Period":
            col1, col2 = st.sidebar.columns(2)
            with col1:
                start_date = st.date_input("Start Date")
                start_time = st.time_input("Start Time")
            with col2:
                end_date = st.date_input("End Date")
                end_time = st.time_input("End Time")
            
            start_datetime = datetime.combine(start_date, start_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            end_datetime = datetime.combine(end_date, end_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            time_ranges = [(start_datetime, end_datetime)]
            
            event_date_input = st.sidebar.date_input("Event Date (for Before/After)")
            event_time_input = st.sidebar.time_input("Event Time")
            event_date = pd.to_datetime(datetime.combine(event_date_input, event_time_input), utc=True)
        
        else:  # Before/After Analysis
            st.sidebar.write("**Before Period:**")
            col1, col2 = st.sidebar.columns(2)
            with col1:
                before_start_date = st.date_input("Before Start Date")
                before_start_time = st.time_input("Before Start Time")
            with col2:
                before_end_date = st.date_input("Before End Date")
                before_end_time = st.time_input("Before End Time")
            
            st.sidebar.write("**After Period:**")
            col1, col2 = st.sidebar.columns(2)
            with col1:
                after_start_date = st.date_input("After Start Date")
                after_start_time = st.time_input("After Start Time")
            with col2:
                after_end_date = st.date_input("After End Date")
                after_end_time = st.time_input("After End Time")
            
            before_start = datetime.combine(before_start_date, before_start_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            before_end = datetime.combine(before_end_date, before_end_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            after_start = datetime.combine(after_start_date, after_start_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            after_end = datetime.combine(after_end_date, after_end_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            time_ranges = [(before_start, before_end), (after_start, after_end)]
            
            # Event date is between the two periods
            event_date = pd.to_datetime(datetime.combine(after_start_date, after_start_time), utc=True)
    else:
        st.sidebar.warning("Other time ranges not implemented yet. Using Mainnet Electra Fork Analysis.")
        time_ranges = [
            ("2025-05-01T12:10:00Z", "2025-05-01T18:10:00Z"),  # Pre-Electra
            ("2025-05-20T12:10:00Z", "2025-05-20T18:10:00Z")   # Post-Electra
        ]
        event_date = pd.to_datetime("2025-05-07T10:00:00Z", utc=True)
    
    # Data loading section
    st.sidebar.subheader("Data Loading")
    
    # Add cache management
    cache_dir = get_cache_dir()
    
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("🗑️ Clear Cache"):
            st.cache_data.clear()
            # Also clear parquet file cache
            import shutil
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
                cache_dir.mkdir(parents=True, exist_ok=True)
            st.sidebar.success("Cache cleared!")
    
    with col2:
        # Show cache size
        cache_size = 0
        if cache_dir.exists():
            for file in cache_dir.glob("*.parquet"):
                cache_size += file.stat().st_size
        cache_size_mb = cache_size / (1024 * 1024)
        st.write(f"💾 {cache_size_mb:.1f}MB")
        
    st.sidebar.info("💡 Parquet files cached locally for faster re-use • Data cached for 1 hour")
    
    # Check if configuration changed
    current_config = (network, str(time_ranges), event_date)
    config_changed = st.session_state.last_config != current_config
    
    if config_changed and st.session_state.data_loaded:
        st.sidebar.warning("⚠️ Configuration changed. Click 'Load Data' to refresh.")
        st.session_state.data_loaded = False
    
    if st.sidebar.button("🔄 Load Data", type="primary"):
        with st.spinner("Loading data from Xatu parquet files..."):
            try:
                # Load blockprint clients (cached) - still uses ClickHouse for client mapping
                st.info("Loading blockprint clients...")
                validators = load_blockprint_clients(network)
                st.session_state.validators = validators
                
                # Load attestation data from parquet files (cached)
                st.info("Loading attestation data from parquet files...")
                all_attestations = load_attestation_data_parquet(str(time_ranges), network)
                
                # Load proposer indices from parquet files (cached)
                st.info("Loading proposer indices from parquet files...")
                proposer_indices = fetch_proposer_indices_parquet(str(time_ranges), network)
                
                # Add client information to proposer indices
                proposer_indices['client'] = proposer_indices['proposer_index'].apply(
                    lambda x: validators.get(x, 'unknown')
                )
                
                # Fill any remaining NaN values in client column
                proposer_indices['client'] = proposer_indices['client'].fillna('unknown')
                
                # Calculate basic slot metrics
                st.info("Calculating slot metrics...")
                slot_metrics_df = all_attestations.groupby('block_slot').apply(calculate_slot_metrics, include_groups=False)
                
                # Calculate first seen attestations with rolling window
                st.info("Calculating first seen attestations...")
                first_seen_counts = calculate_first_seen_attestations(all_attestations)
                
                # Reset index and merge with proposer data
                slot_metrics_df = slot_metrics_df.reset_index()
                
                # Add first seen attestations data
                slot_metrics_df['first_seen_attestations'] = slot_metrics_df['block_slot'].map(first_seen_counts).fillna(0)
                
                if len(proposer_indices) > 0:
                    slot_metrics_df = pd.merge(
                        slot_metrics_df,
                        proposer_indices[['slot', 'proposer_index', 'client']],
                        left_on='block_slot',
                        right_on='slot',
                        how='left'
                    )
                    # Drop the duplicate slot column if it exists
                    if 'slot' in slot_metrics_df.columns:
                        slot_metrics_df = slot_metrics_df.drop('slot', axis=1)
                else:
                    # If no proposer indices, add default columns
                    slot_metrics_df['proposer_index'] = None
                    slot_metrics_df['client'] = 'unknown'
                
                slot_metrics_df = slot_metrics_df.set_index('block_slot')
                
                # Fill any NaN values in client column that might have resulted from the merge
                slot_metrics_df['client'] = slot_metrics_df['client'].fillna('unknown')
                
                # Store in session state
                st.session_state.slot_metrics_df = slot_metrics_df
                st.session_state.data_loaded = True
                st.session_state.last_config = current_config
                
                st.success(f"✅ Data loaded successfully! {len(slot_metrics_df)} blocks analyzed.")
                
            except Exception as e:
                st.error(f"Error loading data: {e}")
                import traceback
                st.error(f"Full error: {traceback.format_exc()}")
    
    # Main content area
    if st.session_state.data_loaded and st.session_state.slot_metrics_df is not None:
        data = st.session_state.slot_metrics_df
        
        # Display enhanced data summary
        st.markdown("---")
        st.markdown("### 📊 Data Summary")
        
        # Calculate additional summary stats
        date_range_days = (data['block_slot_start_date_time'].max() - data['block_slot_start_date_time'].min()).days + 1
        avg_blocks_per_hour = len(data) / (date_range_days * 24) if date_range_days > 0 else 0
        
        # Before/After split for analysis
        temp_df = data.copy()
        temp_df['datetime'] = pd.to_datetime(temp_df['block_slot_start_date_time'])
        event_date_naive = pd.Timestamp(event_date).tz_localize(None) if hasattr(event_date, 'tzinfo') and event_date.tzinfo is not None else event_date
        before_count = len(temp_df[temp_df['datetime'] < event_date_naive])
        after_count = len(temp_df[temp_df['datetime'] >= event_date_naive])
        
        # Top row - main metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("🏗️ Total Blocks", f"{len(data):,}", "Analyzed")
            
        with col2:
            st.metric("⚡ Clients", data['client'].nunique(), "Unique consensus clients")
            
        with col3:
            st.metric("🌐 Network", network.upper(), "Ethereum network")
            
        with col4:
            st.metric("📅 Duration", f"{date_range_days} days", "Analysis period")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Second row - analysis-specific metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("📈 Before Event", f"{before_count:,}", "Blocks pre-event")
            
        with col2:
            st.metric("📉 After Event", f"{after_count:,}", "Blocks post-event")
            
        with col3:
            st.metric("⏰ Event Date", event_date.strftime("%b %d, %Y"), "Analysis split point")
            
        with col4:
            st.metric("📊 Block Rate", f"{avg_blocks_per_hour:.1f}/hr", "Average frequency")
        
        # Date range info
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Handle potential NaT values in datetime columns
        min_date = data['block_slot_start_date_time'].dropna().min()
        max_date = data['block_slot_start_date_time'].dropna().max()
        
        if pd.notna(min_date) and pd.notna(max_date):
            date_range_str = f"{min_date.strftime('%Y-%m-%d %H:%M')} to {max_date.strftime('%Y-%m-%d %H:%M')}"
        else:
            date_range_str = "Date range unavailable"
        
        st.markdown("""
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 10px; border-left: 4px solid #1f77b4;">
            <strong>📅 Analysis Time Range:</strong> {} 
            <br><strong>🔄 Data Coverage:</strong> {} blocks across {} days
        </div>
        """.format(
            date_range_str,
            len(data),
            date_range_days
        ), unsafe_allow_html=True)
        
        # Client selection
        st.subheader("🎯 Analysis Configuration")
        
        available_clients = sorted([c for c in data['client'].unique() if pd.notna(c)])
        
        col1, col2 = st.columns(2)
        with col1:
            selected_clients = st.multiselect(
                "Select Clients to Analyze",
                available_clients,
                default=available_clients[:5] if len(available_clients) > 5 else available_clients
            )
        
        with col2:
            selected_metric = st.selectbox(
                "Select Metric",
                [
                    # Core blog post metrics
                    "unique_validator_indexes",
                    "first_seen_attestations", 
                    "avg_attestation_inclusion_delay",
                    "optimal_inclusion_rate",
                    
                    # Additional inclusion delay metrics
                    "min_attestation_inclusion_delay",
                    "p50_attestation_inclusion_delay",
                    "p95_attestation_inclusion_delay",
                    "max_attestation_inclusion_delay",
                    
                    # Aggregation metrics
                    "aggregation_efficiency",
                    "total_attestations",
                    "avg_validators_per_attestation",
                    "optimal_inclusion_validators"
                ]
            )
        
        if selected_clients:
            # Plot selection
            st.subheader("📈 Visualizations")
            
            plot_type = st.selectbox(
                "Select Plot Type",
                ["Before/After Comparison", "Distribution", "Time Series", "Inclusion Distance Distribution"]
            )
            
            if plot_type == "Before/After Comparison":
                fig = create_before_after_comparison(data, selected_metric, selected_clients, event_date)
                st.plotly_chart(fig, use_container_width=True)
                
            elif plot_type == "Distribution":
                fig = create_distribution_plot(data, selected_metric, selected_clients, event_date)
                st.plotly_chart(fig, use_container_width=True)
                
            elif plot_type == "Time Series":
                fig = create_time_series_plot(data, selected_metric, selected_clients, event_date)
                st.plotly_chart(fig, use_container_width=True)
                
            elif plot_type == "Inclusion Distance Distribution":
                fig = create_inclusion_distance_distribution(data, selected_clients, event_date)
                st.plotly_chart(fig, use_container_width=True)
            
            # Statistics table
            st.subheader("📋 Statistics Summary")
            
            filtered_data = data[data['client'].isin(selected_clients)]
            
            # Calculate statistics by client
            stats = filtered_data.groupby('client')[selected_metric].agg([
                'count', 'mean', 'median', 'std', 'min', 'max'
            ]).round(3)
            
            st.dataframe(stats, use_container_width=True)
            
            # Raw data explorer
            st.subheader("🔍 Raw Data Explorer")
            
            if st.checkbox("Show raw data"):
                st.dataframe(
                    filtered_data[['client', 'block_slot_start_date_time', selected_metric]].head(100),
                    use_container_width=True
                )
        
        else:
            st.warning("Please select at least one client to analyze.")
    
    else:
        st.info("👆 Please configure your parameters in the sidebar and click 'Load Data' to begin analysis.")
        
        # Show example/demo data structure
        st.subheader("📝 About This Dashboard")
        
        st.markdown("""
        This interactive dashboard allows you to analyze Ethereum attestation packing metrics across different:
        
        - **Networks**: mainnet, holesky, sepolia
        - **Time Ranges**: Custom or predefined ranges around key events (e.g., Electra fork)
        - **Clients**: Different consensus client implementations (lighthouse, prysm, teku, etc.)
        - **Metrics**: Comprehensive attestation packing and efficiency metrics
        
        ### Key Metrics Available (based on [EthPandaOps blog analysis](https://ethpandaops.io/posts/hoodi-attestation-packing/)):
        
        **🎯 Core Attestation Packing Metrics:**
        - **Unique Validator Indexes**: Number of unique validators per block (blog: "Unique Validators Per Block")
        - **First Seen Attestations**: Fresh attestations not seen in previous blocks (blog: "Fresh Attestations")
        - **Avg Attestation Inclusion Delay**: Average delay in slots (blog: "Inclusion Distance")
        - **Optimal Inclusion Rate**: Percentage of validators included with 1-slot delay (blog: "Optimal Inclusion Distance")
        
        **📊 Additional Analysis Metrics:**
        - **Aggregation Efficiency**: Ratio of unique validators to total attestations
        - **Total Attestations**: Number of attestations per block
        - **Avg Validators per Attestation**: Average aggregation size
        - **Optimal Inclusion Validators**: Count of validators with 1-slot delay
        
        ### Getting Started:
        
        1. Configure your network and time range in the sidebar
        2. Click "Load Data" to fetch from ClickHouse
        3. Select clients and metrics to analyze
        4. Choose visualization type and explore!
        """)

if __name__ == "__main__":
    main()