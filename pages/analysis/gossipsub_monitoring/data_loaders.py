"""
Data loading functions for Gossipsub Monitoring - Simplified.
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
from queries import get_single_slot_complete_query
from config_utils import get_continent_from_code

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
        query = """
        SELECT DISTINCT slot
        FROM libp2p_gossipsub_beacon_block
        WHERE 
            meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_time)s AND %(end_time)s
            AND message_id != ''
        ORDER BY slot DESC
        LIMIT %(limit)s
        """
        
        result = pd.read_sql(query, conn, params={
            'network': network,
            'start_time': start_time,
            'end_time': end_time,
            'limit': limit
        })
        
        if not result.empty:
            return result['slot'].tolist()
        return []
        
    except Exception as e:
        logger.error(f"Error getting slots: {e}")
        return []
    finally:
        conn.close()


def load_single_slot_data(
    slot: int,
    network: str,
    start_time: datetime,
    end_time: datetime,
    cluster: Optional[str] = None
) -> pd.DataFrame:
    """Load gossipsub data for a single slot."""
    conn = get_database_connection(cluster)
    if conn is None:
        return pd.DataFrame()
    
    try:
        # Calculate time windows
        ihave_start_time = start_time - timedelta(seconds=20)
        ihave_end_time = end_time + timedelta(minutes=3)
        peer_start_time = start_time - timedelta(hours=1)
        peer_end_time = end_time + timedelta(hours=1)
        
        query = get_single_slot_complete_query()
        params = {
            'network': network,
            'slot': slot,
            'ihave_start_time': ihave_start_time,
            'ihave_end_time': ihave_end_time,
            'peer_start_time': peer_start_time,
            'peer_end_time': peer_end_time
        }
        
        df = pd.read_sql(query, conn, params=params)
        
        if not df.empty:
            logger.info(f"Slot {slot}: Found {len(df)} IHAVE records")
        
        return df
        
    except Exception as e:
        logger.error(f"Error loading slot {slot}: {e}")
        return pd.DataFrame()
    finally:
        conn.close()


@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_gossipsub_data(
    start_time: datetime,
    end_time: datetime,
    network: str = "mainnet",
    cluster: Optional[str] = None,
    target_slot: Optional[int] = None,
    slot_limit: int = 100
) -> pd.DataFrame:
    """
    Load gossipsub data - simplified approach with per-slot queries.
    
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
        st.info(f"📦 Loading data for slot {target_slot}...")
        df = load_single_slot_data(target_slot, network, start_time, end_time, cluster)
        
        if df.empty:
            st.warning(f"No data found for slot {target_slot}")
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
        
        # Load data for each slot in parallel
        all_data = []
        
        with st.spinner(f"Loading data for {len(slots)} slots..."):
            # Use ThreadPoolExecutor for parallel queries
            with ThreadPoolExecutor(max_workers=5) as executor:
                # Submit all tasks
                future_to_slot = {
                    executor.submit(load_single_slot_data, slot, network, start_time, end_time, cluster): slot 
                    for slot in slots
                }
                
                # Collect results as they complete
                progress_bar = st.progress(0)
                completed = 0
                
                for future in as_completed(future_to_slot):
                    slot = future_to_slot[future]
                    try:
                        df_slot = future.result()
                        if not df_slot.empty:
                            all_data.append(df_slot)
                            logger.info(f"Loaded {len(df_slot)} records for slot {slot}")
                    except Exception as e:
                        logger.error(f"Failed to load slot {slot}: {e}")
                    
                    completed += 1
                    progress_bar.progress(completed / len(slots))
        
        # Combine all data
        if not all_data:
            st.warning("No data found for any slots")
            return pd.DataFrame()
        
        df = pd.concat(all_data, ignore_index=True)
        st.success(f"✅ Loaded {len(df)} total records from {len(all_data)} slots")
    
    # Convert continent codes to names
    if 'continent' in df.columns:
        df['continent'] = df['continent'].apply(get_continent_from_code)
    
    # Ensure we have all required columns
    required_columns = ['slot', 'block', 'message_id', 'peer_id', 'ihave_time', 
                       'block_propagation_time', 'propagation_delay_ms', 'continent']
    
    for col in required_columns:
        if col not in df.columns:
            if col == 'continent':
                df['continent'] = 'Unknown'
            elif col == 'block_propagation_time':
                df['block_propagation_time'] = 0
            else:
                logger.error(f"Missing required column: {col}")
                st.error(f"Missing required column: {col}")
                return pd.DataFrame()
    
    return df


@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_latest_slot(
    network: str = "mainnet",
    cluster: Optional[str] = None
) -> Optional[int]:
    """
    Get the latest slot with block data.
    
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
        query = """
        SELECT MAX(slot) as max_slot
        FROM libp2p_gossipsub_beacon_block FINAL
        WHERE 
            meta_network_name = %(network)s
            AND propagation_slot_start_diff < 30000
            AND message_id != ''
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
    
    Args:
        df: DataFrame with propagation data
        value_column: Column to calculate CDF for
        
    Returns:
        Dictionary mapping continent to (x_values, y_values) for CDF
    """
    cdf_data = {}
    
    if df.empty or 'continent' not in df.columns:
        return cdf_data
    
    # Group by continent
    for continent in df['continent'].unique():
        if pd.isna(continent):
            continue
            
        continent_data = df[df['continent'] == continent][value_column].dropna()
        
        if len(continent_data) < 5:  # Need minimum data points
            logger.warning(f"Skipping continent {continent} - only {len(continent_data)} data points (minimum 5 required)")
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
    """
    Calculate CDF curves for each slot.
    
    Args:
        df: DataFrame with propagation data
        value_column: Column to calculate CDF for
        
    Returns:
        Dictionary mapping slot to (x_values, y_values) for CDF
    """
    cdf_data = {}
    
    if df.empty or 'slot' not in df.columns:
        return cdf_data
    
    # Group by slot
    for slot in df['slot'].unique():
        if pd.isna(slot):
            continue
            
        slot_data = df[df['slot'] == slot][value_column].dropna()
        
        if len(slot_data) < 5:  # Need minimum data points
            logger.warning(f"Skipping slot {slot} - only {len(slot_data)} data points (minimum 5 required)")
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
    """
    Calculate percentiles for each slot.
    
    Args:
        df: DataFrame with propagation data
        percentiles: List of percentiles to calculate
        value_column: Column to calculate percentiles for
        
    Returns:
        DataFrame with percentiles by slot
    """
    if df.empty or 'slot' not in df.columns:
        return pd.DataFrame()
    
    results = []
    
    for slot in df['slot'].unique():
        if pd.isna(slot):
            continue
            
        slot_data = df[df['slot'] == slot][value_column].dropna()
        
        if len(slot_data) < 5:
            logger.warning(f"Skipping slot {slot} - insufficient data for percentile calculation")
            continue
        
        row = {'slot': int(slot), 'peer_count': len(slot_data)}
        
        for p in percentiles:
            row[f'p{p}'] = np.percentile(slot_data, p) / 1000.0  # Convert to seconds
        
        results.append(row)
    
    return pd.DataFrame(results).sort_values('slot')


def calculate_percentiles_by_continent(
    df: pd.DataFrame,
    percentiles: List[int] = [50, 75, 90, 95, 99],
    value_column: str = 'propagation_delay_ms'
) -> pd.DataFrame:
    """
    Calculate percentiles for each continent.
    
    Args:
        df: DataFrame with propagation data
        percentiles: List of percentiles to calculate
        value_column: Column to calculate percentiles for
        
    Returns:
        DataFrame with percentiles by continent
    """
    if df.empty or 'continent' not in df.columns:
        return pd.DataFrame()
    
    results = []
    
    for continent in df['continent'].unique():
        if pd.isna(continent):
            continue
            
        continent_data = df[df['continent'] == continent][value_column].dropna()
        
        if len(continent_data) < 5:
            logger.warning(f"Skipping continent {continent} - insufficient data for percentile calculation")
            continue
        
        row = {'continent': continent, 'peer_count': len(continent_data)}
        
        for p in percentiles:
            row[f'p{p}'] = np.percentile(continent_data, p) / 1000.0  # Convert to seconds
        
        results.append(row)
    
    return pd.DataFrame(results)


def get_available_slots(
    start_time: datetime,
    end_time: datetime,
    network: str = "mainnet",
    cluster: Optional[str] = None,
    limit: int = 100
) -> List[int]:
    """
    Get list of available slots with gossipsub data.
    
    Args:
        start_time: Start time
        end_time: End time
        network: Network name
        cluster: ClickHouse cluster name
        limit: Maximum number of slots to return
        
    Returns:
        List of slot numbers
    """
    return get_slots_in_range(start_time, end_time, network, cluster, limit)