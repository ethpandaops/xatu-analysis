"""
Data loading functions for Gossipsub Monitoring - Time-based correlation.
Using time windows instead of message_id joins due to ID mismatch between tables.
"""

import pandas as pd
import polars as pl
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple
import logging
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

from shared.database import get_database_connection
from pages.analysis.gossipsub_monitoring.queries_fixed import get_time_based_gossipsub_query, get_slots_in_range_simple, get_latest_slot_simple
from pages.analysis.gossipsub_monitoring.config_utils import get_continent_from_code

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_slots_in_range(
    start_time: datetime,
    end_time: datetime,
    network: str,
    cluster: Optional[str] = None,
    limit: int = 100
) -> List[int]:
    """Get list of slots in a time range."""
    conn = get_database_connection(cluster)
    if conn is None:
        return []
    
    try:
        query = get_slots_in_range_simple()
        
        result = pd.read_sql(query, conn, params={
            'network': network,
            'start_time': start_time,
            'end_time': end_time,
            'limit': limit
        })
        
        if not result.empty:
            return [int(s) for s in result['slot'].tolist()]
        return []
        
    except Exception as e:
        logger.error(f"Error getting slots: {e}")
        return []
    finally:
        conn.close()


def load_single_slot_data_time_based(
    slot: int,
    network: str,
    cluster: Optional[str] = None
) -> pd.DataFrame:
    """Load gossipsub data for a single slot using time-based correlation."""
    conn = get_database_connection(cluster)
    if conn is None:
        return pd.DataFrame()
    
    try:
        # First get the slot time
        slot_time_query = """
        SELECT slot_start_date_time
        FROM libp2p_gossipsub_beacon_block
        WHERE 
            meta_network_name = %(network)s
            AND slot = %(slot)s
        LIMIT 1
        """
        
        slot_df = pd.read_sql(slot_time_query, conn, params={'network': network, 'slot': int(slot)})
        
        if slot_df.empty:
            logger.info(f"Slot {slot}: No block found")
            return pd.DataFrame()
        
        slot_time = slot_df['slot_start_date_time'].iloc[0]
        
        # Now get IHAVE messages around this time
        query = get_time_based_gossipsub_query()
        params = {
            'network': network,
            'slot': int(slot),
            'slot_time': slot_time
        }
        
        df = pd.read_sql(query, conn, params=params)
        
        if not df.empty:
            logger.info(f"Slot {slot}: Found {len(df)} correlated IHAVE records")
        else:
            logger.info(f"Slot {slot}: No IHAVE data found in time window")
        
        return df
        
    except Exception as e:
        logger.error(f"Error loading slot {slot}: {e}")
        return pd.DataFrame()
    finally:
        conn.close()


@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_gossipsub_data_simplified(
    start_time: datetime,
    end_time: datetime,
    network: str = "mainnet",
    cluster: Optional[str] = None,
    target_slot: Optional[int] = None,
    slot_limit: int = 20  # Reduced default since we're using time correlation
) -> pd.DataFrame:
    """
    Load gossipsub data using time-based correlation.
    
    Args:
        start_time: Start time for data query
        end_time: End time for data query
        network: Network name
        cluster: ClickHouse cluster name
        target_slot: Specific slot to analyze (if None, uses time range)
        slot_limit: Maximum number of slots to analyze
        
    Returns:
        DataFrame with gossipsub propagation data
    """
    
    # If specific slot requested
    if target_slot is not None:
        st.info(f"📦 Loading data for slot {target_slot} using time correlation...")
        df = load_single_slot_data_time_based(target_slot, network, cluster)
        
        if df.empty:
            st.warning(f"No correlated data found for slot {target_slot}")
            return pd.DataFrame()
        
        st.success(f"✅ Found {len(df)} records for slot {target_slot}")
        
    else:
        # Get list of slots in time range
        st.info(f"📦 Getting slots from {start_time.strftime('%H:%M')} to {end_time.strftime('%H:%M')}...")
        slots = get_slots_in_range(start_time, end_time, network, cluster, slot_limit)
        
        if not slots:
            st.warning("No slots found in time range")
            return pd.DataFrame()
        
        st.success(f"✅ Found {len(slots)} slots")
        
        # Load data for each slot
        all_data = []
        
        with st.spinner(f"Loading data for {len(slots)} slots using time correlation..."):
            # Process slots sequentially to avoid overwhelming the database
            progress_bar = st.progress(0)
            
            for idx, slot in enumerate(slots):
                df_slot = load_single_slot_data_time_based(slot, network, cluster)
                if not df_slot.empty:
                    all_data.append(df_slot)
                    logger.info(f"Loaded {len(df_slot)} records for slot {slot}")
                
                progress_bar.progress((idx + 1) / len(slots))
        
        # Combine all data
        if not all_data:
            st.warning("No correlated data found for any slots")
            return pd.DataFrame()
        
        df = pd.concat(all_data, ignore_index=True)
        st.success(f"✅ Loaded {len(df)} total records from {len(all_data)} slots")
    
    # Ensure we have all required columns
    required_columns = ['slot', 'peer_id', 'ihave_time', 'propagation_delay_ms', 'continent']
    
    for col in required_columns:
        if col not in df.columns:
            if col == 'continent':
                df['continent'] = 'Unknown'
            elif col == 'block':
                df['block'] = ''
            elif col == 'message_id':
                df['message_id'] = ''
            elif col == 'block_propagation_time':
                df['block_propagation_time'] = 0
            else:
                logger.error(f"Missing required column: {col}")
    
    return df


@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_latest_slot_simplified(
    network: str = "mainnet",
    cluster: Optional[str] = None
) -> Optional[int]:
    """
    Get the latest slot with block data (from 15 minutes ago to account for IHAVE data delay).
    
    Args:
        network: Network name
        cluster: ClickHouse cluster name
        
    Returns:
        Latest slot number or None
    """
    conn = get_database_connection(cluster)
    if conn is None:
        return None
    
    try:
        # Modified query to get slot from 15 minutes ago
        query = """
        SELECT MAX(slot) as max_slot
        FROM libp2p_gossipsub_beacon_block
        WHERE 
            meta_network_name = %(network)s
            AND slot_start_date_time <= now() - INTERVAL 15 MINUTE
            AND slot_start_date_time >= now() - INTERVAL 1 HOUR
        """
        
        result = pd.read_sql(query, conn, params={'network': network})
        if not result.empty and result['max_slot'].iloc[0] is not None:
            return int(result['max_slot'].iloc[0])
        return None
        
    except Exception as e:
        logger.error(f"Error getting latest slot: {e}")
        return None
    finally:
        conn.close()


def calculate_cdf_by_continent(
    df: pd.DataFrame,
    value_column: str = 'propagation_delay_ms'
) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """
    Calculate CDF curves for each continent.
    Since we're defaulting to 'Unknown', this will typically return one curve.
    """
    cdf_data = {}
    
    if df.empty or 'continent' not in df.columns:
        return cdf_data
    
    # Group by continent (will typically just be 'Unknown')
    for continent in df['continent'].unique():
        if pd.isna(continent):
            continue
            
        continent_data = df[df['continent'] == continent][value_column].dropna()
        
        if len(continent_data) < 5:  # Need minimum data points
            logger.warning(f"Skipping continent {continent} - only {len(continent_data)} data points")
            continue
        
        # Sort values for CDF
        sorted_values = np.sort(continent_data.values)
        
        # Calculate CDF (cumulative probabilities)
        y_values = np.arange(1, len(sorted_values) + 1) / len(sorted_values)
        
        cdf_data[continent] = (sorted_values, y_values)
    
    return cdf_data


def calculate_cdf_by_slot(
    df: pd.DataFrame,
    value_column: str = 'propagation_delay_ms'
) -> Dict[int, Tuple[np.ndarray, np.ndarray]]:
    """Calculate CDF curves for each slot."""
    cdf_data = {}
    
    if df.empty or 'slot' not in df.columns:
        return cdf_data
    
    # Group by slot
    for slot in df['slot'].unique():
        if pd.isna(slot):
            continue
            
        slot_data = df[df['slot'] == slot][value_column].dropna()
        
        if len(slot_data) < 5:  # Need minimum data points
            logger.warning(f"Skipping slot {slot} - only {len(slot_data)} data points")
            continue
        
        # Sort values for CDF
        sorted_values = np.sort(slot_data.values)
        
        # Calculate CDF (cumulative probabilities)
        y_values = np.arange(1, len(sorted_values) + 1) / len(sorted_values)
        
        cdf_data[int(slot)] = (sorted_values, y_values)
    
    return cdf_data


def calculate_percentiles_by_slot(
    df: pd.DataFrame,
    percentiles: List[int] = [50, 75, 90, 95, 99],
    value_column: str = 'propagation_delay_ms'
) -> pd.DataFrame:
    """Calculate percentiles for each slot."""
    if df.empty or 'slot' not in df.columns:
        return pd.DataFrame()
    
    results = []
    
    for slot in df['slot'].unique():
        if pd.isna(slot):
            continue
            
        slot_data = df[df['slot'] == slot][value_column].dropna()
        
        if len(slot_data) < 5:
            continue
        
        row = {'slot': int(slot), 'peer_count': len(slot_data)}
        
        for p in percentiles:
            row[f'p{p}'] = np.percentile(slot_data, p)
        
        results.append(row)
    
    return pd.DataFrame(results).sort_values('slot')


def calculate_percentiles_by_continent(
    df: pd.DataFrame,
    percentiles: List[int] = [50, 75, 90, 95, 99],
    value_column: str = 'propagation_delay_ms'
) -> pd.DataFrame:
    """Calculate percentiles for each continent (typically just 'Unknown')."""
    if df.empty or 'continent' not in df.columns:
        return pd.DataFrame()
    
    results = []
    
    for continent in df['continent'].unique():
        if pd.isna(continent):
            continue
            
        continent_data = df[df['continent'] == continent][value_column].dropna()
        
        if len(continent_data) < 5:
            continue
        
        row = {'continent': continent, 'peer_count': len(continent_data)}
        
        for p in percentiles:
            row[f'p{p}'] = np.percentile(continent_data, p)
        
        results.append(row)
    
    return pd.DataFrame(results)