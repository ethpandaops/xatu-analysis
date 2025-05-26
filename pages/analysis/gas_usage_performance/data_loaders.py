"""
Data loading utilities for gas usage performance analysis.

This module handles loading and caching data from ClickHouse databases
for gas usage vs performance analysis.
"""

import pandas as pd
import streamlit as st
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
import logging

from shared.database import get_database_connection
from config_utils import get_analysis_config


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@st.cache_data(ttl=3600)  # 1 hour cache
def load_block_gossip_data(
    network: str, 
    start_date: datetime, 
    end_date: datetime
) -> pd.DataFrame:
    """
    Load block gossip propagation data from ClickHouse.
    
    Args:
        network: Network name (mainnet, holesky, sepolia)
        start_date: Analysis start date
        end_date: Analysis end date
        
    Returns:
        DataFrame with block gossip timing data
    """
    conn = get_database_connection()
    config = get_analysis_config()
    
    query = """
    SELECT
        slot,
        slot_start_date_time,
        propagation_slot_start_diff as block_gossip_time,
        meta_client_name,
        meta_consensus_implementation,
        meta_client_geo_continent_code
    FROM beacon_api_eth_v1_events_block_gossip FINAL
    WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND meta_client_name != '' AND meta_client_name IS NOT NULL
        AND propagation_slot_start_diff < %(max_propagation)s
        AND propagation_slot_start_diff >= 0
    ORDER BY slot_start_date_time
    """
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
        'max_propagation': config['max_propagation_time_ms']
    }
    
    logger.info(f"Loading block gossip data for {network} from {start_date} to {end_date}")
    
    try:
        df = pd.read_sql(query, conn, params=params)
        logger.info(f"Loaded {len(df)} block gossip records")
        return df
    except Exception as e:
        logger.error(f"Error loading block gossip data: {e}")
        st.error(f"Failed to load block gossip data: {str(e)}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)  # 1 hour cache
def load_head_time_data(
    network: str, 
    start_date: datetime, 
    end_date: datetime
) -> pd.DataFrame:
    """
    Load head time data using complex CTE query from multiple event tables.
    This represents the maximum propagation time across all event types per client.
    
    Args:
        network: Network name
        start_date: Analysis start date  
        end_date: Analysis end date
        
    Returns:
        DataFrame with head timing data
    """
    conn = get_database_connection()
    config = get_analysis_config()
    
    query = """
    WITH head_events AS (
        SELECT
            slot,
            slot_start_date_time,
            propagation_slot_start_diff as arrival_time,
            meta_client_name,
            meta_consensus_implementation,
            meta_client_geo_continent_code
        FROM beacon_api_eth_v1_events_head FINAL
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND meta_client_name != '' AND meta_client_name IS NOT NULL
            AND propagation_slot_start_diff < %(max_propagation)s
            AND propagation_slot_start_diff >= 0
    ),
    block_events AS (
        SELECT
            slot,
            slot_start_date_time,
            propagation_slot_start_diff as arrival_time,
            meta_client_name,
            meta_consensus_implementation,
            meta_client_geo_continent_code
        FROM beacon_api_eth_v1_events_block FINAL
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND meta_client_name != '' AND meta_client_name IS NOT NULL
            AND propagation_slot_start_diff < %(max_propagation)s
            AND propagation_slot_start_diff >= 0
    ),
    blob_events AS (
        SELECT
            slot,
            slot_start_date_time,
            MAX(propagation_slot_start_diff) as arrival_time,
            meta_client_name,
            meta_consensus_implementation,
            meta_client_geo_continent_code
        FROM beacon_api_eth_v1_events_blob_sidecar FINAL
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND meta_client_name != '' AND meta_client_name IS NOT NULL
            AND propagation_slot_start_diff < %(max_propagation)s
            AND propagation_slot_start_diff >= 0
        GROUP BY slot, slot_start_date_time, meta_client_name, 
                 meta_consensus_implementation, meta_client_geo_continent_code
    ),
    all_events AS (
        SELECT * FROM head_events
        UNION ALL
        SELECT * FROM block_events  
        UNION ALL
        SELECT * FROM blob_events
    )
    SELECT
        slot,
        slot_start_date_time,
        MAX(arrival_time) as head_time,
        meta_client_name,
        meta_consensus_implementation,
        meta_client_geo_continent_code
    FROM all_events
    GROUP BY slot, slot_start_date_time, meta_client_name,
             meta_consensus_implementation, meta_client_geo_continent_code
    ORDER BY slot_start_date_time
    """
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
        'max_propagation': config['max_propagation_time_ms']
    }
    
    logger.info(f"Loading head time data for {network} from {start_date} to {end_date}")
    
    try:
        df = pd.read_sql(query, conn, params=params)
        logger.info(f"Loaded {len(df)} head time records")
        return df
    except Exception as e:
        logger.error(f"Error loading head time data: {e}")
        st.error(f"Failed to load head time data: {str(e)}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)  # 1 hour cache
def load_canonical_block_data(
    network: str, 
    start_date: datetime, 
    end_date: datetime
) -> pd.DataFrame:
    """
    Load canonical block data including gas usage information.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        
    Returns:
        DataFrame with block and gas usage data
    """
    conn = get_database_connection()
    
    query = """
    SELECT
        slot,
        slot_start_date_time,
        epoch,
        proposer_index,
        execution_payload_gas_used as gas_used,
        execution_payload_gas_limit as gas_limit,
        execution_payload_blob_gas_used as blob_gas_used,
        execution_payload_excess_blob_gas as excess_blob_gas,
        execution_payload_transactions_count as transaction_count,
        execution_payload_block_hash as block_hash
    FROM canonical_beacon_block FINAL
    WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND execution_payload_gas_used IS NOT NULL
        AND execution_payload_gas_limit IS NOT NULL
        AND execution_payload_gas_used > 0
    ORDER BY slot_start_date_time
    """
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date
    }
    
    logger.info(f"Loading canonical block data for {network} from {start_date} to {end_date}")
    
    try:
        df = pd.read_sql(query, conn, params=params)
        logger.info(f"Loaded {len(df)} canonical block records")
        
        # Calculate derived metrics
        if not df.empty:
            df['gas_utilization'] = (df['gas_used'] / df['gas_limit'] * 100).round(2)
            
        return df
    except Exception as e:
        logger.error(f"Error loading canonical block data: {e}")
        st.error(f"Failed to load canonical block data: {str(e)}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)  # 1 hour cache
def load_blob_sidecar_counts(
    network: str, 
    start_date: datetime, 
    end_date: datetime
) -> pd.DataFrame:
    """
    Load blob sidecar count data for blocks.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        
    Returns:
        DataFrame with blob counts per slot
    """
    conn = get_database_connection()
    
    query = """
    SELECT
        slot,
        COUNT(*) as blob_count
    FROM beacon_api_eth_v1_events_blob_sidecar FINAL
    WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
    GROUP BY slot
    ORDER BY slot
    """
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date
    }
    
    logger.info(f"Loading blob sidecar counts for {network} from {start_date} to {end_date}")
    
    try:
        df = pd.read_sql(query, conn, params=params)
        logger.info(f"Loaded blob counts for {len(df)} slots")
        return df
    except Exception as e:
        logger.error(f"Error loading blob sidecar counts: {e}")
        st.warning(f"Could not load blob sidecar data: {str(e)}")
        return pd.DataFrame()


def combine_performance_data(
    gossip_df: pd.DataFrame,
    head_df: pd.DataFrame,
    block_df: pd.DataFrame,
    blob_df: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """
    Combine all performance data sources into a single client-level dataset.
    This preserves granular data for flexible user-controlled aggregation.
    
    Args:
        gossip_df: Block gossip timing data
        head_df: Head timing data  
        block_df: Canonical block data with gas usage
        blob_df: Optional blob sidecar count data
        
    Returns:
        Combined DataFrame at client/slot level for flexible aggregation
    """
    logger.info("Combining performance data from multiple sources")
    
    if gossip_df.empty or head_df.empty or block_df.empty:
        logger.warning("One or more data sources are empty")
        return pd.DataFrame()
    
    # Sort all input data by slot and time BEFORE combining
    gossip_df = gossip_df.sort_values(['slot', 'slot_start_date_time']).reset_index(drop=True)
    head_df = head_df.sort_values(['slot', 'slot_start_date_time']).reset_index(drop=True) 
    block_df = block_df.sort_values(['slot', 'slot_start_date_time']).reset_index(drop=True)
    if blob_df is not None and not blob_df.empty:
        blob_df = blob_df.sort_values('slot').reset_index(drop=True)
    
    # Start with gossip data as the base (most granular - client level)
    combined_df = gossip_df.copy()
    
    # Ensure we have the right column name for block gossip time
    if 'propagation_slot_start_diff' in combined_df.columns:
        combined_df.rename(columns={'propagation_slot_start_diff': 'block_gossip_time'}, inplace=True)
    elif 'block_gossip_time' not in combined_df.columns:
        logger.error("Missing block gossip time column in gossip data")
        return pd.DataFrame()
    
    # Merge with head time data at client level
    head_client_data = head_df.copy()
    combined_df = combined_df.merge(
        head_client_data[['slot', 'meta_client_name', 'head_time']],
        on=['slot', 'meta_client_name'],
        how='left'
    )
    
    # Add time difference calculation
    combined_df['time_difference'] = combined_df['head_time'] - combined_df['block_gossip_time']
    
    # Merge with block data (one-to-many, block data to client records)
    block_cols = ['slot', 'gas_used', 'gas_limit', 'gas_utilization', 'proposer_index', 'epoch']
    available_block_cols = [col for col in block_cols if col in block_df.columns]
    
    combined_df = combined_df.merge(
        block_df[available_block_cols],
        on='slot',
        how='left'
    )
    
    # Merge with blob data if available
    if blob_df is not None and not blob_df.empty:
        combined_df = combined_df.merge(blob_df, on='slot', how='left')
        combined_df['blob_count'] = combined_df['blob_count'].fillna(0)
    else:
        combined_df['blob_count'] = 0
    
    # Clean up data types and handle missing values
    numeric_columns = ['block_gossip_time', 'head_time', 'time_difference', 'gas_used', 
                       'gas_limit', 'gas_utilization', 'blob_count']
    
    for col in numeric_columns:
        if col in combined_df.columns:
            combined_df[col] = pd.to_numeric(combined_df[col], errors='coerce')
    
    # Add derived columns for analysis
    combined_df['has_gas_data'] = combined_df['gas_used'].notna() & (combined_df['gas_used'] > 0)
    
    # Final sort by time to ensure proper temporal ordering
    combined_df = combined_df.sort_values(['slot', 'slot_start_date_time', 'meta_client_name']).reset_index(drop=True)
    
    logger.info(f"Combined client-level dataset created with {len(combined_df)} records")
    
    # Log column info for debugging
    logger.info(f"Combined dataset columns: {list(combined_df.columns)}")
    if 'gas_used' in combined_df.columns:
        gas_records = combined_df['gas_used'].notna().sum()
        logger.info(f"Records with gas data: {gas_records}/{len(combined_df)}")
    
    return combined_df


@st.cache_data(ttl=3600)  # 1 hour cache
def load_complete_analysis_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    period_name: str = "Analysis Period"
) -> Dict[str, Any]:
    """
    Load complete dataset for gas usage performance analysis.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        period_name: Human-readable period name
        
    Returns:
        Dictionary containing all loaded data and metadata
    """
    logger.info(f"Loading complete analysis data for {period_name}: {network} {start_date} to {end_date}")
    
    # Load all data sources
    gossip_df = load_block_gossip_data(network, start_date, end_date)
    head_df = load_head_time_data(network, start_date, end_date) 
    block_df = load_canonical_block_data(network, start_date, end_date)
    blob_df = load_blob_sidecar_counts(network, start_date, end_date)
    
    # Combine all data
    combined_df = combine_performance_data(gossip_df, head_df, block_df, blob_df)
    
    # Calculate summary statistics (updated for client-level data)
    summary_stats = {}
    if not combined_df.empty:
        summary_stats = {
            'total_blocks': len(combined_df),
            'date_range': f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            'avg_gas_used': combined_df['gas_used'].mean() if 'gas_used' in combined_df.columns and combined_df['gas_used'].notna().sum() > 0 else 0,
            'avg_gas_utilization': combined_df['gas_utilization'].mean() if 'gas_utilization' in combined_df.columns and combined_df['gas_utilization'].notna().sum() > 0 else 0,
            'avg_block_gossip_time': combined_df['block_gossip_time'].mean() if 'block_gossip_time' in combined_df.columns and combined_df['block_gossip_time'].notna().sum() > 0 else 0,
            'avg_head_time': combined_df['head_time'].mean() if 'head_time' in combined_df.columns and combined_df['head_time'].notna().sum() > 0 else 0,
            'unique_slots': combined_df['slot'].nunique() if 'slot' in combined_df.columns else 0,
            'unique_clients': combined_df['meta_client_name'].nunique() if 'meta_client_name' in combined_df.columns else 0
        }
    
    return {
        'combined_data': combined_df,
        'gossip_data': gossip_df,
        'head_data': head_df,
        'block_data': block_df,
        'blob_data': blob_df,
        'summary_stats': summary_stats,
        'period_name': period_name,
        'network': network,
        'start_date': start_date,
        'end_date': end_date
    }


def validate_data_quality(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate data quality and return quality metrics.
    
    Args:
        df: Combined analysis DataFrame (now client-level data)
        
    Returns:
        Dictionary with data quality metrics and warnings
    """
    if df.empty:
        return {
            'valid': False,
            'warnings': ['Dataset is empty'],
            'metrics': {}
        }
    
    warnings = []
    metrics = {}
    
    # Check for minimum sample size
    config = get_analysis_config()
    min_samples = config['min_samples_per_analysis']
    
    if len(df) < min_samples:
        warnings.append(f"Dataset has only {len(df)} records, minimum {min_samples} recommended")
    
    # Check for missing critical columns (updated for client-level data)
    critical_columns = ['slot', 'meta_client_name', 'block_gossip_time']
    missing_columns = [col for col in critical_columns if col not in df.columns or df[col].isna().all()]
    
    if missing_columns:
        warnings.append(f"Missing critical data columns: {missing_columns}")
    
    # Calculate data completeness (updated column names)
    key_columns = ['block_gossip_time', 'head_time', 'gas_used']
    for col in key_columns:
        if col in df.columns:
            completeness = (1 - df[col].isna().sum() / len(df)) * 100
            metrics[f'{col}_completeness'] = completeness
            if completeness < 80:
                warnings.append(f"Low data completeness for {col}: {completeness:.1f}%")
    
    # Check for outliers
    if 'gas_used' in df.columns and df['gas_used'].notna().sum() > 0:
        gas_data = df['gas_used'].dropna()
        if len(gas_data) > 0:
            q95 = gas_data.quantile(0.95)
            q05 = gas_data.quantile(0.05)
            outlier_ratio = ((gas_data > q95 * 2) | (gas_data < q05 / 2)).sum() / len(gas_data)
            metrics['gas_outlier_ratio'] = outlier_ratio
            if outlier_ratio > 0.1:
                warnings.append(f"High outlier ratio in gas usage: {outlier_ratio:.1%}")
    
    return {
        'valid': len(warnings) == 0,
        'warnings': warnings,
        'metrics': metrics
    }