"""
Data loading functions for Gossipsub Monitoring - Reverse lookup approach.
Start from IHAVE data and work backwards to find slots.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple, Union
import logging
import streamlit as st

from shared.database import get_database_connection
from pages.analysis.gossipsub_monitoring.queries_reverse import (
    get_ihave_based_slots_query, 
    get_ihave_data_for_slot_time,
    get_idontwant_data_for_slot_time,
    get_latest_ihave_slot,
    get_all_ihave_data_in_range,
    get_all_idontwant_data_in_range,
    get_combined_ihave_idontwant_data,
    get_latest_idontwant_slot
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
    slot_limit: int = 50,
    message_type: str = "IHAVE",
    subtract_latency: bool = True
) -> pd.DataFrame:
    """
    Load gossipsub data using reverse lookup from control messages.
    
    Args:
        start_time: Start time for data query
        end_time: End time for data query
        network: Network name
        cluster: ClickHouse cluster name
        target_slot: Specific slot to analyze (if provided)
        slot_limit: Maximum number of slots to analyze
        message_type: Type of message to load ("IHAVE", "IDONTWANT", or "COMBINED")
        subtract_latency: Whether to subtract network latency from propagation times
        
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
            
            message_label = message_type if message_type != "COMBINED" else "IHAVE+IDONTWANT"
            st.info(f"📦 Loading {message_label} data for slot {target_slot}...")
            
            if message_type == "IHAVE":
                query = get_ihave_data_for_slot_time()
            elif message_type == "IDONTWANT":
                query = get_idontwant_data_for_slot_time()
            else:  # COMBINED - need to handle specially
                # For combined, we need to get both and merge
                ihave_query = get_ihave_data_for_slot_time()
                idontwant_query = get_idontwant_data_for_slot_time()
                
                params = {
                    'network': network,
                    'slot': target_slot,
                    'slot_time': slot_time
                }
                
                ihave_df = pd.read_sql(ihave_query, conn, params=params)
                idontwant_df = pd.read_sql(idontwant_query, conn, params=params)
                
                # Merge taking the minimum time for each peer
                if not ihave_df.empty and not idontwant_df.empty:
                    ihave_df['message_type'] = 'IHAVE'
                    idontwant_df['message_type'] = 'IDONTWANT'
                    df = pd.concat([ihave_df, idontwant_df])
                    # Group by peer and take the minimum propagation delay
                    df = df.sort_values('propagation_delay_ms').groupby('peer_id').first().reset_index()
                elif not ihave_df.empty:
                    df = ihave_df
                    df['message_type'] = 'IHAVE'
                else:
                    df = idontwant_df
                    df['message_type'] = 'IDONTWANT'
                
                if df.empty:
                    st.warning(f"No {message_label} data found for slot {target_slot}")
                else:
                    st.success(f"✅ Found {len(df)} {message_label} records for slot {target_slot}")
                
                # Handle latency adjustment for combined data
                if not df.empty:
                    if subtract_latency and 'adjusted_propagation_ms' in df.columns:
                        # Use adjusted propagation times
                        df['raw_propagation_delay_ms'] = df['propagation_delay_ms'].copy()
                        df['propagation_delay_ms'] = df['adjusted_propagation_ms']
                        # Keep latency info columns for display
                        if 'rtt_ms' not in df.columns:
                            df['rtt_ms'] = None
                        if 'one_way_latency_ms' not in df.columns:
                            df['one_way_latency_ms'] = None
                    else:
                        # Keep raw propagation times
                        if 'adjusted_propagation_ms' in df.columns:
                            df.drop(columns=['adjusted_propagation_ms'], inplace=True)
                        if 'rtt_ms' in df.columns:
                            df.drop(columns=['rtt_ms'], inplace=True)
                        if 'one_way_latency_ms' in df.columns:
                            df.drop(columns=['one_way_latency_ms'], inplace=True)
                
                return df
            
            params = {
                'network': network,
                'slot': target_slot,
                'slot_time': slot_time
            }
            
            df = pd.read_sql(query, conn, params=params)
            
            if df.empty:
                st.warning(f"No {message_label} data found for slot {target_slot}")
            else:
                st.success(f"✅ Found {len(df)} {message_label} records for slot {target_slot}")
        
        # Handle latency adjustment
        if not df.empty:
            if subtract_latency and 'adjusted_propagation_ms' in df.columns:
                # Use adjusted propagation times
                df['raw_propagation_delay_ms'] = df['propagation_delay_ms'].copy()
                df['propagation_delay_ms'] = df['adjusted_propagation_ms']
                # Keep latency info columns for display
                if 'rtt_ms' not in df.columns:
                    df['rtt_ms'] = None
                if 'one_way_latency_ms' not in df.columns:
                    df['one_way_latency_ms'] = None
            else:
                # Keep raw propagation times
                if 'adjusted_propagation_ms' in df.columns:
                    df.drop(columns=['adjusted_propagation_ms'], inplace=True)
                if 'rtt_ms' in df.columns:
                    df.drop(columns=['rtt_ms'], inplace=True)
                if 'one_way_latency_ms' in df.columns:
                    df.drop(columns=['one_way_latency_ms'], inplace=True)
                    
        else:
            # For time range, get data based on message type
            message_label = message_type if message_type != "COMBINED" else "IHAVE+IDONTWANT"
            st.info(f"📦 Loading {message_label} data from {start_time.strftime('%H:%M')} to {end_time.strftime('%H:%M')}...")
            
            if message_type == "IHAVE":
                query = get_all_ihave_data_in_range()
            elif message_type == "IDONTWANT":
                query = get_all_idontwant_data_in_range()
            else:  # COMBINED
                query = get_combined_ihave_idontwant_data()
            
            params = {
                'network': network,
                'start_time': start_time,
                'end_time': end_time
            }
            
            df = pd.read_sql(query, conn, params=params)
            
            if df.empty:
                st.warning(f"No {message_label} data found in time range")
            else:
                unique_slots = df['slot'].nunique()
                st.success(f"✅ Found {len(df)} {message_label} records across {unique_slots} slots")
        
        # Handle latency adjustment for all data
        if not df.empty:
            if subtract_latency and 'adjusted_propagation_ms' in df.columns:
                # Use adjusted propagation times
                df['raw_propagation_delay_ms'] = df['propagation_delay_ms'].copy()
                df['propagation_delay_ms'] = df['adjusted_propagation_ms']
                # Keep latency info columns for display
                if 'rtt_ms' not in df.columns:
                    df['rtt_ms'] = None
                if 'one_way_latency_ms' not in df.columns:
                    df['one_way_latency_ms'] = None
            else:
                # Keep raw propagation times
                if 'adjusted_propagation_ms' in df.columns:
                    df.drop(columns=['adjusted_propagation_ms'], inplace=True)
                if 'rtt_ms' in df.columns:
                    df.drop(columns=['rtt_ms'], inplace=True)
                if 'one_way_latency_ms' in df.columns:
                    df.drop(columns=['one_way_latency_ms'], inplace=True)
        
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
    value_column: str = 'propagation_delay_ms',
    return_peer_counts: bool = False
) -> Union[Dict[str, Tuple[np.ndarray, np.ndarray]], Tuple[Dict[str, Tuple[np.ndarray, np.ndarray]], Dict[str, int]]]:
    """Calculate CDF curves for each continent."""
    cdf_data = {}
    peer_counts = {}
    
    if df.empty or 'continent' not in df.columns:
        return (cdf_data, peer_counts) if return_peer_counts else cdf_data
    
    for continent in df['continent'].unique():
        if pd.isna(continent):
            continue
            
        continent_df = df[df['continent'] == continent]
        # Only consider rows with valid propagation delays
        valid_continent_df = continent_df[continent_df[value_column].notna()]
        continent_data = valid_continent_df[value_column]
        
        if len(continent_data) < 5:
            continue
        
        sorted_values = np.sort(continent_data.values)
        y_values = np.arange(1, len(sorted_values) + 1) / len(sorted_values)
        
        cdf_data[continent] = (sorted_values, y_values)
        
        # Calculate unique peer count from rows with valid data only
        if return_peer_counts and 'peer_id' in df.columns:
            peer_counts[continent] = valid_continent_df['peer_id'].nunique()
    
    return (cdf_data, peer_counts) if return_peer_counts else cdf_data


def calculate_cdf_by_slot(
    df: pd.DataFrame,
    value_column: str = 'propagation_delay_ms',
    return_peer_counts: bool = False
) -> Union[Dict[int, Tuple[np.ndarray, np.ndarray]], Tuple[Dict[int, Tuple[np.ndarray, np.ndarray]], Dict[int, int]]]:
    """Calculate CDF curves for each slot."""
    cdf_data = {}
    peer_counts = {}
    
    if df.empty or 'slot' not in df.columns:
        return (cdf_data, peer_counts) if return_peer_counts else cdf_data
    
    for slot in df['slot'].unique():
        if pd.isna(slot):
            continue
            
        slot_df = df[df['slot'] == slot]
        # Only consider rows with valid propagation delays
        valid_slot_df = slot_df[slot_df[value_column].notna()]
        slot_data = valid_slot_df[value_column]
        
        if len(slot_data) < 5:
            continue
        
        sorted_values = np.sort(slot_data.values)
        y_values = np.arange(1, len(sorted_values) + 1) / len(sorted_values)
        
        cdf_data[int(slot)] = (sorted_values, y_values)
        
        # Calculate unique peer count from rows with valid data only
        if return_peer_counts and 'peer_id' in df.columns:
            peer_counts[int(slot)] = valid_slot_df['peer_id'].nunique()
    
    return (cdf_data, peer_counts) if return_peer_counts else cdf_data


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


@st.cache_data(ttl=300)
def load_comparison_data(
    start_time: datetime,
    end_time: datetime,
    network: str = "mainnet",
    cluster: Optional[str] = None,
    slot_limit: int = 50,
    subtract_latency: bool = True
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load both IHAVE and IDONTWANT data for comparison.
    
    Returns:
        Tuple of (ihave_df, idontwant_df)
    """
    conn = get_database_connection(cluster)
    if conn is None:
        st.error("Cannot connect to database")
        return pd.DataFrame(), pd.DataFrame()
    
    try:
        # Load IHAVE data
        ihave_query = get_all_ihave_data_in_range()
        ihave_params = {
            'network': network,
            'start_time': start_time,
            'end_time': end_time
        }
        ihave_df = pd.read_sql(ihave_query, conn, params=ihave_params)
        ihave_df['message_type'] = 'IHAVE'
        
        # Load IDONTWANT data
        idontwant_query = get_all_idontwant_data_in_range()
        idontwant_params = {
            'network': network,
            'start_time': start_time,
            'end_time': end_time
        }
        idontwant_df = pd.read_sql(idontwant_query, conn, params=idontwant_params)
        idontwant_df['message_type'] = 'IDONTWANT'
        
        # Handle latency adjustment for both dataframes
        for df in [ihave_df, idontwant_df]:
            if not df.empty:
                if subtract_latency and 'adjusted_propagation_ms' in df.columns:
                    # Use adjusted propagation times
                    df['raw_propagation_delay_ms'] = df['propagation_delay_ms'].copy()
                    df['propagation_delay_ms'] = df['adjusted_propagation_ms']
                    # Keep latency info columns for display
                    if 'rtt_ms' not in df.columns:
                        df['rtt_ms'] = None
                    if 'one_way_latency_ms' not in df.columns:
                        df['one_way_latency_ms'] = None
                else:
                    # Keep raw propagation times
                    if 'adjusted_propagation_ms' in df.columns:
                        df.drop(columns=['adjusted_propagation_ms'], inplace=True)
                    if 'rtt_ms' in df.columns:
                        df.drop(columns=['rtt_ms'], inplace=True)
                    if 'one_way_latency_ms' in df.columns:
                        df.drop(columns=['one_way_latency_ms'], inplace=True)
        
        return ihave_df, idontwant_df
        
    except Exception as e:
        logger.error(f"Error loading comparison data: {e}")
        st.error(f"Failed to load comparison data: {str(e)}")
        return pd.DataFrame(), pd.DataFrame()
    finally:
        conn.close()