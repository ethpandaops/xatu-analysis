"""
Data loading functions for Gossipsub Monitoring - Reverse lookup approach.
Start from IHAVE data and work backwards to find slots.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple
import logging
import streamlit as st

from shared.database import get_database_connection
from queries_reverse import (
    get_ihave_based_slots_query, 
    get_ihave_data_for_slot_time,
    get_latest_ihave_slot,
    get_all_ihave_data_in_range
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_gossipsub_data_reverse(
    start_time: datetime,
    end_time: datetime,
    network: str = "mainnet",
    cluster: Optional[str] = None,
    target_slot: Optional[int] = None,
    slot_limit: int = 50
) -> pd.DataFrame:
    """
    Load gossipsub data using reverse lookup from IHAVE messages.
    
    Args:
        start_time: Start time for data query
        end_time: End time for data query
        network: Network name
        cluster: ClickHouse cluster name
        target_slot: Specific slot to analyze (if provided)
        slot_limit: Maximum number of slots to analyze
        
    Returns:
        DataFrame with gossipsub propagation data
    """
    conn = get_database_connection(cluster)
    if conn is None:
        st.error("Cannot connect to database")
        return pd.DataFrame()
    
    try:
        if target_slot is not None:
            # For single slot, calculate its time and get data
            slot_time = datetime(2020, 12, 1, 12, 0, 23, tzinfo=timezone.utc) + timedelta(seconds=target_slot * 12)
            
            st.info(f"📦 Loading IHAVE data for slot {target_slot}...")
            
            query = get_ihave_data_for_slot_time()
            params = {
                'network': network,
                'slot': target_slot,
                'slot_time': slot_time
            }
            
            df = pd.read_sql(query, conn, params=params)
            
            if df.empty:
                st.warning(f"No IHAVE data found for slot {target_slot}")
            else:
                st.success(f"✅ Found {len(df)} IHAVE records for slot {target_slot}")
                
        else:
            # For time range, get all IHAVE data efficiently
            st.info(f"📦 Loading IHAVE data from {start_time.strftime('%H:%M')} to {end_time.strftime('%H:%M')}...")
            
            query = get_all_ihave_data_in_range()
            params = {
                'network': network,
                'start_time': start_time,
                'end_time': end_time
            }
            
            df = pd.read_sql(query, conn, params=params)
            
            if df.empty:
                st.warning("No IHAVE data found in time range")
            else:
                unique_slots = df['slot'].nunique()
                st.success(f"✅ Found {len(df)} IHAVE records across {unique_slots} slots")
        
        return df
        
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        st.error(f"Failed to load data: {str(e)}")
        return pd.DataFrame()
    finally:
        conn.close()


@st.cache_data(ttl=300)
def get_latest_slot_with_ihave(
    network: str = "mainnet",
    cluster: Optional[str] = None
) -> Optional[int]:
    """
    Get the latest slot that has IHAVE beacon_block data.
    
    Args:
        network: Network name
        cluster: ClickHouse cluster name
        
    Returns:
        Latest slot number with IHAVE data or None
    """
    conn = get_database_connection(cluster)
    if conn is None:
        return None
    
    try:
        query = get_latest_ihave_slot()
        result = pd.read_sql(query, conn, params={'network': network})
        
        if not result.empty and result['slot'].iloc[0] is not None:
            return int(result['slot'].iloc[0])
        return None
        
    except Exception as e:
        logger.error(f"Error getting latest slot: {e}")
        return None
    finally:
        conn.close()


def get_available_slots_with_ihave(
    start_time: datetime,
    end_time: datetime,
    network: str = "mainnet",
    cluster: Optional[str] = None,
    limit: int = 100
) -> List[Tuple[int, datetime, int]]:
    """
    Get list of slots that have IHAVE data in the time range.
    
    Returns:
        List of tuples (slot_number, slot_time, peer_count)
    """
    conn = get_database_connection(cluster)
    if conn is None:
        return []
    
    try:
        query = get_ihave_based_slots_query()
        params = {
            'network': network,
            'start_time': start_time,
            'end_time': end_time,
            'limit': limit
        }
        
        result = pd.read_sql(query, conn, params=params)
        
        if not result.empty:
            return [(int(row['slot']), row['slot_time'], int(row['peer_count'])) 
                    for _, row in result.iterrows()]
        return []
        
    except Exception as e:
        logger.error(f"Error getting available slots: {e}")
        return []
    finally:
        conn.close()


def calculate_cdf_by_continent(
    df: pd.DataFrame,
    value_column: str = 'propagation_delay_ms'
) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """Calculate CDF curves for each continent."""
    cdf_data = {}
    
    if df.empty or 'continent' not in df.columns:
        return cdf_data
    
    for continent in df['continent'].unique():
        if pd.isna(continent):
            continue
            
        continent_data = df[df['continent'] == continent][value_column].dropna()
        
        if len(continent_data) < 5:
            continue
        
        sorted_values = np.sort(continent_data.values)
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
    
    for slot in df['slot'].unique():
        if pd.isna(slot):
            continue
            
        slot_data = df[df['slot'] == slot][value_column].dropna()
        
        if len(slot_data) < 5:
            continue
        
        sorted_values = np.sort(slot_data.values)
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
    """Calculate percentiles for each continent."""
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