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
from config_utils import get_data_source_options

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


@st.cache_data(ttl=3600)
def load_attestation_timing_data_polars(start_time, end_time, network="mainnet", data_source="gossip"):
    """Load attestation arrival timing data using Polars for high performance."""
    logger.info(f"Loading attestation data for missed slots: network={network}, data_source={data_source}")
    logger.info(f"Time range: {start_time} to {end_time}")
    
    conn = get_database_connection()
    
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
    start_slot = int((start_time_utc.timestamp() - 1606824023) // 12)  # Genesis timestamp
    end_slot = int((end_time_utc.timestamp() - 1606824023) // 12)
    
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



def load_combined_analysis_data_polars(start_time, end_time, network="mainnet", data_source="beacon_api"):
    """Load attestation data for missed slots analysis."""
    logger.info(f"load_combined_analysis_data_polars called: network={network}, data_source={data_source}")
    
    # Load attestation metrics for missed slots
    attestation_metrics = load_attestation_timing_data_polars(start_time, end_time, network, data_source)
    
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