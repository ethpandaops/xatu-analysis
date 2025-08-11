"""
Polars-optimized data loading utilities for attestation CDF analysis.

This module provides high-performance data loading using Polars for large-scale
attestation propagation analysis.
"""

import polars as pl
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from typing import Dict, Any
import logging

from shared.database import get_database_connection
from shared.config import get_network_genesis_timestamp
from config_utils import get_data_source_options

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


@st.cache_data(ttl=3600)
def load_attestation_timing_data_polars(start_time, end_time, network="mainnet", data_source="gossip", cluster_name=None):
    """Load attestation arrival timing data using Polars for high performance."""
    logger.info(f"Loading attestation data for missed slots: network={network}, data_source={data_source}")
    logger.info(f"Time range: {start_time} to {end_time}")
    
    conn = get_database_connection(cluster_name)
    
    # Times are now passed in UTC from the dashboard
    from datetime import timezone
    
    if start_time.tzinfo is None:
        # If naive, assume UTC (shouldn't happen now)
        start_time_utc = start_time.replace(tzinfo=timezone.utc)
        end_time_utc = end_time.replace(tzinfo=timezone.utc)
    else:
        # Already has timezone info, convert to UTC
        start_time_utc = start_time.astimezone(timezone.utc)
        end_time_utc = end_time.astimezone(timezone.utc)
    
    # Convert to slot numbers for partition filtering
    genesis_time = get_network_genesis_timestamp(network)
    
    start_slot = int((start_time_utc.timestamp() - genesis_time) // 12)
    end_slot = int((end_time_utc.timestamp() - genesis_time) // 12)
    
    logger.info(f"Slot range: {start_slot} to {end_slot} ({end_slot - start_slot + 1} slots)")
    
    # Get data source configuration
    source_config = get_data_source_options()[data_source]
    table_name = source_config["table"]
    logger.info(f"Using table: {table_name}")
    
    try:
        # Convert to naive datetime like the working gas_usage_performance code
        params = {
            'start_date': start_time_utc.replace(tzinfo=None),
            'end_date': end_time_utc.replace(tzinfo=None),
            'start_slot': start_slot,
            'end_slot': end_slot,
            'network': network
        }
        
        # Step 1: Generate all slots in the time range
        all_slots = list(range(start_slot, end_slot + 1))
        logger.info(f"Generated {len(all_slots)} total slots in range")
        
        # Step 2: Get slots that have blocks
        block_slots_query = """
        SELECT DISTINCT slot
        FROM beacon_api_eth_v2_beacon_block
        WHERE slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND slot BETWEEN %(start_slot)s AND %(end_slot)s
            AND meta_network_name = %(network)s
        """
        
        import pandas as pd
        logger.debug("Executing block slots query...")
        block_slots_df = pd.read_sql(block_slots_query, conn, params=params)
        logger.info(f"Found {len(block_slots_df)} slots with blocks")
        
        # Find missed slots (all slots minus slots with blocks)
        block_slots = set(block_slots_df['slot'].tolist())
        missed_slots = sorted([slot for slot in all_slots if slot not in block_slots])
        
        logger.info(f"Found {len(missed_slots)} missed slots out of {len(all_slots)} total slots")
        if missed_slots:
            logger.debug(f"First 10 missed slots: {missed_slots[:10]}")
        
        if not missed_slots:
            # No missed slots found - return empty DataFrame
            logger.warning("No missed slots found in this time range")
            return pl.DataFrame()
        
        # Convert to comma-separated string for SQL IN clause
        missed_slots_str = ','.join(map(str, missed_slots))
        logger.debug(f"Querying attestations for slots: {len(missed_slots)} slots")
        
        # Step 2: Get attestation metrics for missed slots
        # First deduplicate attestations by taking MIN propagation time per validator
        query = f"""
        WITH unique_attestations AS (
            SELECT 
                meta_client_name,
                slot,
                attesting_validator_index,
                MIN(propagation_slot_start_diff) as min_prop_time
            FROM {table_name}
            WHERE slot IN ({missed_slots_str})
                AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
                AND meta_network_name = %(network)s
                AND attesting_validator_index IS NOT NULL
                AND propagation_slot_start_diff >= 0
                AND propagation_slot_start_diff <= 12000  -- Cap at 12 seconds
            GROUP BY meta_client_name, slot, attesting_validator_index
        )
        SELECT 
            meta_client_name,
            slot,
            COUNT(*) as total_attestations,
            COUNT(DISTINCT attesting_validator_index) as unique_validators,
            MIN(min_prop_time) as min_propagation,
            """ + ",\n            ".join([
                f"quantile({i/100:.2f})(min_prop_time) as p{i:02d}_propagation"
                for i in range(2, 100, 2)  # 2%, 4%, 6%, ..., 98%
            ]) + """,
            MAX(min_prop_time) as max_propagation,
            AVG(min_prop_time) as mean_propagation,
            stddevPop(min_prop_time) as stddev_propagation
        FROM unique_attestations
        GROUP BY meta_client_name, slot
        ORDER BY slot, meta_client_name
        """
        
        # Load attestation data for missed slots
        logger.debug("Executing attestation query...")
        df_pandas = pd.read_sql(query, conn, params=params)
        logger.info(f"Found {len(df_pandas)} attestation records for missed slots")
        
        if df_pandas.empty:
            logger.warning("No attestation data found for missed slots")
            return pl.DataFrame()
        
        # Convert to Polars with proper data types
        cast_expressions = [
            pl.col('slot').cast(pl.Int64),
            pl.col('total_attestations').cast(pl.Int64),
            pl.col('unique_validators').cast(pl.Int64),
            pl.col('min_propagation').cast(pl.Float64),
        ]
        
        # Add all percentile columns programmatically
        for i in range(2, 100, 2):
            cast_expressions.append(pl.col(f'p{i:02d}_propagation').cast(pl.Float64))
        
        cast_expressions.extend([
            pl.col('max_propagation').cast(pl.Float64),
            pl.col('mean_propagation').cast(pl.Float64),
            pl.col('stddev_propagation').cast(pl.Float64),
        ])
        
        df_polars = pl.from_pandas(df_pandas).with_columns(cast_expressions)
        
        logger.info(f"Successfully loaded attestation data: {len(df_polars)} records")
        return df_polars
        
    except Exception as e:
        logger.error(f"Error loading attestation data: {str(e)}", exc_info=True)
        st.error(f"Error loading attestation data: {str(e)}")
        return pl.DataFrame()


@st.cache_data(ttl=3600)
def load_raw_attestation_data_for_slow_analysis(start_time, end_time, network="mainnet", data_source="beacon_api", missed_slots=None, client_filters=None, include_observer_nodes=False, cluster_name=None):
    """Load raw attestation data with validator indices for slow period analysis."""
    logger.info(f"Loading raw attestation data for slow analysis: network={network}, data_source={data_source}, include_observer_nodes={include_observer_nodes}")
    
    conn = get_database_connection(cluster_name)
    
    # Get data source configuration
    source_config = get_data_source_options()[data_source]
    table_name = source_config["table"]
    
    try:
        from datetime import timezone
        
        if start_time.tzinfo is None:
            start_time_utc = start_time.replace(tzinfo=timezone.utc)
            end_time_utc = end_time.replace(tzinfo=timezone.utc)
        else:
            start_time_utc = start_time.astimezone(timezone.utc)
            end_time_utc = end_time.astimezone(timezone.utc)
        
        params = {
            'start_date': start_time_utc.replace(tzinfo=None),
            'end_date': end_time_utc.replace(tzinfo=None),
            'network': network
        }
        
        # If no missed slots provided, we need to find them first
        if missed_slots is None:
            genesis_time = get_network_genesis_timestamp(network)
            
            start_slot = int((start_time_utc.timestamp() - genesis_time) // 12)
            end_slot = int((end_time_utc.timestamp() - genesis_time) // 12)
            params['start_slot'] = start_slot
            params['end_slot'] = end_slot
            
            # Get missed slots
            all_slots = list(range(start_slot, end_slot + 1))
            
            block_slots_query = """
            SELECT DISTINCT slot
            FROM beacon_api_eth_v2_beacon_block
            WHERE slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
                AND slot BETWEEN %(start_slot)s AND %(end_slot)s
                AND meta_network_name = %(network)s
            """
            
            block_slots_df = pd.read_sql(block_slots_query, conn, params=params)
            block_slots = set(block_slots_df['slot'].tolist())
            missed_slots = sorted([slot for slot in all_slots if slot not in block_slots])
        
        if not missed_slots:
            logger.warning("No missed slots found")
            return pl.DataFrame()
        
        # Limit to reasonable number of slots to avoid huge queries
        if len(missed_slots) > 100:
            logger.warning(f"Too many missed slots ({len(missed_slots)}), limiting to most recent 100")
            missed_slots = missed_slots[-100:]
        
        missed_slots_str = ','.join(map(str, missed_slots))
        
        # Build client filter conditions
        client_conditions = []
        if client_filters:
            if client_filters.get('selected_clients'):
                clients_str = ','.join([f"'{c}'" for c in client_filters['selected_clients']])
                client_conditions.append(f"meta_client_name IN ({clients_str})")
            
            if client_filters.get('excluded_clients'):
                excluded_str = ','.join([f"'{c}'" for c in client_filters['excluded_clients']])
                client_conditions.append(f"meta_client_name NOT IN ({excluded_str})")
        
        client_filter_sql = " AND " + " AND ".join(client_conditions) if client_conditions else ""
        
        if include_observer_nodes:
            # Query includes observation node details for consensus analysis
            query = f"""
            WITH validator_slot_node_attestations AS (
                SELECT 
                    slot,
                    attesting_validator_index,
                    meta_client_name as observer_node,
                    MIN(propagation_slot_start_diff) as propagation_time
                FROM {table_name}
                WHERE slot IN ({missed_slots_str})
                    AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
                    AND meta_network_name = %(network)s
                    AND attesting_validator_index IS NOT NULL
                    AND propagation_slot_start_diff >= 0
                    AND propagation_slot_start_diff <= 12000
                    {client_filter_sql}
                GROUP BY slot, attesting_validator_index, meta_client_name
            )
            SELECT 
                slot,
                attesting_validator_index,
                observer_node,
                propagation_time
            FROM validator_slot_node_attestations
            ORDER BY slot, attesting_validator_index, observer_node
            """
        else:
            # Original query - aggregate across all observation nodes
            query = f"""
            WITH validator_slot_attestations AS (
                SELECT 
                    slot,
                    attesting_validator_index,
                    MIN(propagation_slot_start_diff) as propagation_time
                FROM {table_name}
                WHERE slot IN ({missed_slots_str})
                    AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
                    AND meta_network_name = %(network)s
                    AND attesting_validator_index IS NOT NULL
                    AND propagation_slot_start_diff >= 0
                    AND propagation_slot_start_diff <= 12000
                    {client_filter_sql}
                GROUP BY slot, attesting_validator_index
            )
            SELECT 
                slot,
                attesting_validator_index,
                propagation_time
            FROM validator_slot_attestations
            ORDER BY slot, propagation_time
            """
        
        logger.debug("Executing validator attestation query...")
        df_pandas = pd.read_sql(query, conn, params=params)
        
        if include_observer_nodes:
            logger.info(f"Found {len(df_pandas)} attestation records across {df_pandas['slot'].nunique()} slots and {df_pandas['observer_node'].nunique()} observer nodes")
        else:
            logger.info(f"Found {len(df_pandas)} attestation records across {df_pandas['slot'].nunique()} slots")
        logger.info(f"Unique validators: {df_pandas['attesting_validator_index'].nunique()}")
        
        if df_pandas.empty:
            return pl.DataFrame()
        
        # Convert to Polars
        columns_to_cast = [
            pl.col('slot').cast(pl.Int64),
            pl.col('attesting_validator_index').cast(pl.Int64),
            pl.col('propagation_time').cast(pl.Float64)
        ]
        
        if include_observer_nodes:
            # Keep observer_node as string
            df_polars = pl.from_pandas(df_pandas).with_columns(columns_to_cast)
        else:
            df_polars = pl.from_pandas(df_pandas).with_columns(columns_to_cast)
        
        return df_polars
        
    except Exception as e:
        logger.error(f"Error loading raw attestation data: {str(e)}", exc_info=True)
        return pl.DataFrame()
    finally:
        conn.close()


def load_combined_analysis_data_polars(start_time, end_time, network="mainnet", data_source="beacon_api", cluster_name=None):
    """Load attestation data for missed slots analysis."""
    logger.info(f"load_combined_analysis_data_polars called: network={network}, data_source={data_source}")
    
    # Load attestation metrics for missed slots
    attestation_metrics = load_attestation_timing_data_polars(start_time, end_time, network, data_source, cluster_name)
    
    if attestation_metrics.is_empty():
        logger.warning("No attestation metrics found, returning empty dataframes")
        return {
            'attestations': pd.DataFrame(),
            'committees': pd.DataFrame(),
            'slots': pd.DataFrame(),
            'data_quality': {
                'attestation_rows': 0,
                'slot_range': 0,
                'committee_slots': 0,
                'networks': [],
                'data_source': data_source,
                'data_source_table': get_data_source_options()[data_source]["table"]
            }
        }
    
    # Convert to pandas - we only have the columns from the query
    attestations_df = attestation_metrics.to_pandas()
    logger.info(f"Converted {len(attestations_df)} attestation records to pandas")
    
    # Create simplified slot metadata for missed slots
    unique_slots = sorted(attestations_df['slot'].unique())
    logger.info(f"Found {len(unique_slots)} unique slots with attestations")
    
    slots_df = pd.DataFrame({
        'slot': unique_slots,
        'epoch': [slot // 32 for slot in unique_slots],
        'block_seen': 0  # All are missed slots by definition
    })
    
    # Create empty committee data - we don't have this info for missed slots
    committees_df = pd.DataFrame({
        'slot': unique_slots,
        'expected_attestations': 0
    })
    
    result = {
        'attestations': attestations_df,
        'committees': committees_df,
        'slots': slots_df,
        'data_quality': {
            'attestation_rows': len(attestations_df),
            'slot_range': len(unique_slots),
            'committee_slots': len(committees_df),
            'networks': [network],
            'data_source': data_source,
            'data_source_table': get_data_source_options()[data_source]["table"]
        }
    }
    
    logger.info(f"Returning analysis data: {len(attestations_df)} attestations, {len(unique_slots)} slots")
    return result


@st.cache_data(ttl=3600)
def load_proposer_duties_for_missed_slots(missed_slots, network="mainnet", cluster_name=None):
    """Load proposer duties for missed slots to identify who should have proposed.
    
    Args:
        missed_slots: List of slot numbers
        network: Network name
        
    Returns:
        DataFrame with columns: slot, proposer_validator_index
    """
    logger.info(f"Loading proposer duties for {len(missed_slots)} missed slots")
    
    if not missed_slots:
        return pd.DataFrame(columns=['slot', 'proposer_validator_index'])
    
    # Limit to reasonable number to avoid huge queries
    if len(missed_slots) > 1000:
        logger.warning(f"Too many missed slots ({len(missed_slots)}), limiting to most recent 1000")
        missed_slots = sorted(missed_slots)[-1000:]
    
    conn = get_database_connection(cluster_name)
    
    try:
        # Convert slots to comma-separated string
        slots_str = ','.join(map(str, missed_slots))
        
        query = f"""
        SELECT DISTINCT
            slot,
            proposer_validator_index
        FROM beacon_api_eth_v1_proposer_duty
        WHERE slot IN ({slots_str})
            AND meta_network_name = %(network)s
        ORDER BY slot
        """
        
        params = {'network': network}
        
        logger.debug("Executing proposer duties query...")
        df = pd.read_sql(query, conn, params=params)
        
        logger.info(f"Found proposer duties for {len(df)} slots out of {len(missed_slots)} missed slots")
        
        return df
        
    except Exception as e:
        logger.error(f"Error loading proposer duties: {str(e)}", exc_info=True)
        return pd.DataFrame(columns=['slot', 'proposer_validator_index'])
    finally:
        conn.close()