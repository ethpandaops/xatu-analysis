"""
Data loading utilities for multi-metric performance analysis.

This module handles loading and caching data from ClickHouse databases
for multi-metric performance analysis using Polars for optimal performance.
"""

import polars as pl
import pandas as pd
import streamlit as st
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List
import logging
import warnings

from shared.database import get_database_connection
from shared.data_utils import memory_efficient_context, normalize_time_range, chunk_time_range
from config_utils import get_analysis_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress pandas warnings about chained assignment
warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)

# Polars configuration for performance
pl.Config.set_streaming_chunk_size(50_000)
pl.Config.set_tbl_rows(10)


@st.cache_data(ttl=3600)
def load_block_gossip_data(
    network: str, 
    start_date: datetime, 
    end_date: datetime
) -> pd.DataFrame:
    """
    Load block gossip data with polars optimizations and normalization.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        
    Returns:
        DataFrame with optimized block gossip timing data
    """
    with memory_efficient_context():
        # Normalize time range (no longer truncates)
        norm_start, norm_end, _ = normalize_time_range(start_date, end_date)
        
        conn = get_database_connection()
        config = get_analysis_config()
        
        # Query without LIMIT - get ALL data in time range
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
            'start_date': norm_start,
            'end_date': norm_end,
            'max_propagation': config['max_propagation_time_ms']
        }
        
        logger.info(f"Loading ALL block gossip data for {network} from {norm_start} to {norm_end}")
        
        try:
            # Load into pandas first, then convert to Polars for processing
            df_pandas = pd.read_sql(query, conn, params=params)
            
            if df_pandas.empty:
                logger.warning("No block gossip data found")
                return pd.DataFrame()
            
            # Ensure datetime column is properly formatted for Polars
            df_pandas['slot_start_date_time'] = pd.to_datetime(df_pandas['slot_start_date_time'])
            
            # Convert to Polars for efficient processing
            df_polars = pl.from_pandas(df_pandas)
            
            # Data cleaning and normalization with Polars
            df_polars = (df_polars
                .with_columns([
                    pl.col("block_gossip_time").cast(pl.Float64),
                    pl.col("meta_client_name").str.strip_chars(),
                    pl.col("meta_consensus_implementation").str.strip_chars().fill_null("unknown")
                ])
                .filter(
                    (pl.col("block_gossip_time").is_not_null()) &
                    (pl.col("block_gossip_time") >= 0) &
                    (pl.col("meta_client_name") != "")
                )
                .sort("slot_start_date_time")
            )
            
            # Convert back to pandas for Streamlit compatibility
            result_df = df_polars.to_pandas()
            
            logger.info(f"Loaded and processed {len(result_df):,} block gossip records")
            
            # Log data size info without UI messages
            if len(result_df) > 100_000:
                logger.info(f"Large dataset loaded: {len(result_df):,} records")
            
            return result_df
            
        except Exception as e:
            logger.error(f"Error loading block gossip data: {e}")
            st.error(f"Failed to load block gossip data: {str(e)}")
            return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_head_time_data(
    network: str, 
    start_date: datetime, 
    end_date: datetime
) -> pd.DataFrame:
    """
    Load head time data with polars optimizations using streaming approach.
    
    Args:
        network: Network name
        start_date: Analysis start date  
        end_date: Analysis end date
        
    Returns:
        DataFrame with optimized head timing data
    """
    with memory_efficient_context():
        # Normalize time range
        norm_start, norm_end, _ = normalize_time_range(start_date, end_date)
        
        conn = get_database_connection()
        config = get_analysis_config()
        
        # Complete query getting ALL head time data without limits
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
            'start_date': norm_start,
            'end_date': norm_end,
            'max_propagation': config['max_propagation_time_ms']
        }
        
        logger.info(f"Loading optimized head time data for {network}")
        
        try:
            df_pandas = pd.read_sql(query, conn, params=params)
            
            if df_pandas.empty:
                return pd.DataFrame()
            
            # Ensure datetime column is properly formatted for Polars
            df_pandas['slot_start_date_time'] = pd.to_datetime(df_pandas['slot_start_date_time'])
            
            # Efficient processing with Polars
            df_polars = pl.from_pandas(df_pandas)
            
            df_polars = (df_polars
                .with_columns([
                    pl.col("head_time").cast(pl.Float64),
                    pl.col("meta_client_name").str.strip_chars(),
                    pl.col("meta_consensus_implementation").str.strip_chars().fill_null("unknown")
                ])
                .filter(pl.col("head_time").is_not_null())
                .sort("slot_start_date_time")
            )
            
            result_df = df_polars.to_pandas()
            logger.info(f"Loaded and processed {len(result_df):,} head time records")
            
            return result_df
            
        except Exception as e:
            logger.error(f"Error loading head time data: {e}")
            st.error(f"Failed to load head time data: {str(e)}")
            return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_canonical_block_data(
    network: str, 
    start_date: datetime, 
    end_date: datetime
) -> pd.DataFrame:
    """
    Load canonical block data with gas usage optimizations using polars.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        
    Returns:
        DataFrame with optimized block and gas usage data
    """
    with memory_efficient_context():
        # Normalize time range
        norm_start, norm_end, _ = normalize_time_range(start_date, end_date)
        
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
        FROM beacon_api_eth_v2_beacon_block FINAL
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND execution_payload_gas_used IS NOT NULL
            AND execution_payload_gas_limit IS NOT NULL
            AND execution_payload_gas_used > 0
        ORDER BY slot_start_date_time
        """
        
        params = {
            'network': network,
            'start_date': norm_start,
            'end_date': norm_end
        }
        
        logger.info(f"Loading optimized canonical block data for {network}")
        
        try:
            df_pandas = pd.read_sql(query, conn, params=params)
            
            if df_pandas.empty:
                return pd.DataFrame()
            
            # Ensure datetime column is properly formatted for Polars
            df_pandas['slot_start_date_time'] = pd.to_datetime(df_pandas['slot_start_date_time'])
            
            # Efficient processing with Polars
            df_polars = pl.from_pandas(df_pandas)
            
            df_polars = (df_polars
                .with_columns([
                    pl.col("gas_used").cast(pl.Int64),
                    pl.col("gas_limit").cast(pl.Int64),
                    (pl.col("gas_used") / pl.col("gas_limit") * 100).round(2).alias("gas_utilization")
                ])
                .filter(
                    (pl.col("gas_used").is_not_null()) &
                    (pl.col("gas_limit").is_not_null()) &
                    (pl.col("gas_used") > 0)
                )
                .sort("slot_start_date_time")
            )
            
            result_df = df_polars.to_pandas()
            logger.info(f"Loaded and processed {len(result_df):,} canonical block records")
            
            return result_df
            
        except Exception as e:
            logger.error(f"Error loading canonical block data: {e}")
            st.error(f"Failed to load canonical block data: {str(e)}")
            return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_blob_sidecar_counts(
    network: str, 
    start_date: datetime, 
    end_date: datetime
) -> pd.DataFrame:
    """
    Load blob sidecar count data using polars optimizations.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        
    Returns:
        DataFrame with blob counts per slot
    """
    with memory_efficient_context():
        # Normalize time range
        norm_start, norm_end, _ = normalize_time_range(start_date, end_date)
        
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
            'start_date': norm_start,
            'end_date': norm_end
        }
        
        logger.info(f"Loading blob sidecar counts for {network}")
        
        try:
            df_pandas = pd.read_sql(query, conn, params=params)
            
            if df_pandas.empty:
                logger.info("No blob sidecar data found")
                return pd.DataFrame()
            
            # Simple processing with Polars
            df_polars = pl.from_pandas(df_pandas)
            df_polars = df_polars.with_columns([
                pl.col("blob_count").cast(pl.Int32)
            ]).sort("slot")
            
            result_df = df_polars.to_pandas()
            logger.info(f"Loaded blob counts for {len(result_df):,} slots")
            
            return result_df
            
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
    Combine performance data using Polars for efficient joins and processing.
    
    Args:
        gossip_df: Block gossip timing data
        head_df: Head timing data  
        block_df: Canonical block data with gas usage
        blob_df: Optional blob sidecar count data
        
    Returns:
        Combined DataFrame optimized for performance
    """
    logger.info("Combining performance data with Polars optimization")
    
    with memory_efficient_context():
        if gossip_df.empty or head_df.empty or block_df.empty:
            logger.warning("One or more data sources are empty")
            return pd.DataFrame()
        
        # Convert to Polars for efficient joins
        gossip_pl = pl.from_pandas(gossip_df)
        head_pl = pl.from_pandas(head_df)
        block_pl = pl.from_pandas(block_df)
        
        # Efficient join strategy - start with smallest dataset
        logger.info(f"Dataset sizes: gossip={len(gossip_pl)}, head={len(head_pl)}, block={len(block_pl)}")
        
        # Join gossip with head data
        combined_pl = (gossip_pl
            .join(
                head_pl.select(["slot", "meta_client_name", "head_time"]),
                on=["slot", "meta_client_name"],
                how="left"
            )
            .with_columns([
                (pl.col("head_time") - pl.col("block_gossip_time")).alias("time_difference")
            ])
        )
        
        # Join with block data
        block_cols = ["slot", "gas_used", "gas_limit", "gas_utilization", "proposer_index", "epoch"]
        available_block_cols = [col for col in block_cols if col in block_pl.columns]
        
        combined_pl = combined_pl.join(
            block_pl.select(available_block_cols),
            on="slot",
            how="left"
        )
        
        # Add blob data if available
        if blob_df is not None and not blob_df.empty:
            blob_pl = pl.from_pandas(blob_df)
            combined_pl = combined_pl.join(blob_pl, on="slot", how="left")
            combined_pl = combined_pl.with_columns(
                pl.col("blob_count").fill_null(0)
            )
        else:
            combined_pl = combined_pl.with_columns(
                pl.lit(0).alias("blob_count")
            )
        
        # Data type optimization and cleaning
        combined_pl = (combined_pl
            .with_columns([
                pl.col("block_gossip_time").cast(pl.Float64),
                pl.col("head_time").cast(pl.Float64),
                pl.col("time_difference").cast(pl.Float64),
                pl.col("gas_used").cast(pl.Int64),
                pl.col("gas_limit").cast(pl.Int64),
                pl.col("gas_utilization").cast(pl.Float64),
                pl.col("blob_count").cast(pl.Int32)
            ])
            .with_columns([
                (pl.col("gas_used").is_not_null() & (pl.col("gas_used") > 0)).alias("has_gas_data")
            ])
            .sort(["slot", "slot_start_date_time", "meta_client_name"])
        )
        
        # Convert back to pandas only at the very end
        result_df = combined_pl.to_pandas()
        
        logger.info(f"Combined polars dataset created with {len(result_df):,} records")
        return result_df


def calculate_summary_stats(df: pd.DataFrame, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
    """
    Calculate summary statistics efficiently using Polars.
    
    Args:
        df: Combined DataFrame
        start_date: Analysis start date
        end_date: Analysis end date
        
    Returns:
        Dictionary with summary statistics
    """
    if df.empty:
        return {}
    
    with memory_efficient_context():
        df_pl = pl.from_pandas(df)
        
        # Efficient aggregation with Polars
        stats = df_pl.select([
            pl.len().alias("total_records"),
            pl.col("slot").n_unique().alias("unique_slots"),
            pl.col("meta_client_name").n_unique().alias("unique_clients"),
            pl.col("gas_used").mean().alias("avg_gas_used"),
            pl.col("gas_utilization").mean().alias("avg_gas_utilization"),
            pl.col("block_gossip_time").mean().alias("avg_block_gossip_time"),
            pl.col("head_time").mean().alias("avg_head_time")
        ]).to_pandas().iloc[0].to_dict()
        
        # Convert to regular Python types and handle NaN
        summary_stats = {
            'total_blocks': int(stats.get('total_records', 0)),
            'date_range': f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            'avg_gas_used': float(stats.get('avg_gas_used', 0)) if pd.notna(stats.get('avg_gas_used')) else 0,
            'avg_gas_utilization': float(stats.get('avg_gas_utilization', 0)) if pd.notna(stats.get('avg_gas_utilization')) else 0,
            'avg_block_gossip_time': float(stats.get('avg_block_gossip_time', 0)) if pd.notna(stats.get('avg_block_gossip_time')) else 0,
            'avg_head_time': float(stats.get('avg_head_time', 0)) if pd.notna(stats.get('avg_head_time')) else 0,
            'unique_slots': int(stats.get('unique_slots', 0)),
            'unique_clients': int(stats.get('unique_clients', 0))
        }
        
        return summary_stats


@st.cache_data(ttl=3600)
def load_complete_analysis_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    period_name: str = "Analysis Period",
    use_chunking: bool = True
) -> Dict[str, Any]:
    """
    Load complete dataset, converting to pandas only at the end.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        period_name: Human-readable period name
        use_chunking: Whether to use chunking for large time ranges
        
    Returns:
        Dictionary containing all loaded data and metadata (pandas for compatibility)
    """
    logger.info(f"Loading data for {period_name}: {network} {start_date} to {end_date}")
    
    with memory_efficient_context():
        # Check if we need chunking
        time_diff = end_date - start_date
        config = get_analysis_config()
        max_days_per_chunk = config.get('max_days_per_chunk', 14)
        
        if use_chunking and time_diff.days > max_days_per_chunk:
            logger.info(f"Large time range detected ({time_diff.days} days). Using chunked loading.")
            return load_chunked_analysis_data(network, start_date, end_date, period_name, max_days_per_chunk)
        
        # Load all data sources
        gossip_df = load_block_gossip_data(network, start_date, end_date)
        head_df = load_head_time_data(network, start_date, end_date)
        block_df = load_canonical_block_data(network, start_date, end_date)
        blob_df = load_blob_sidecar_counts(network, start_date, end_date)
        
        # Combine all data
        combined_df = combine_performance_data(gossip_df, head_df, block_df, blob_df)
        
        # Calculate summary statistics
        summary_stats = calculate_summary_stats(combined_df, start_date, end_date)
        
        logger.info(f"Data loading complete - loaded {len(combined_df):,} records")
        
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
            'end_date': end_date,
            'optimization_used': 'polars_native_pipeline'
        }


def load_chunked_analysis_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    period_name: str,
    chunk_days: int = 7
) -> Dict[str, Any]:
    """
    Load data in chunks for very large time ranges to prevent OOM.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        period_name: Human-readable period name
        chunk_days: Days per chunk
        
    Returns:
        Dictionary with combined chunked data
    """
    logger.info(f"Loading chunked data with {chunk_days} day chunks")
    
    chunks = chunk_time_range(start_date, end_date, chunk_days)
    
    combined_dfs = []
    total_chunks = len(chunks)
    
    # Progress tracking
    progress_bar = st.progress(0, text="Loading data chunks...")
    
    for i, (chunk_start, chunk_end) in enumerate(chunks):
        progress_bar.progress((i + 1) / total_chunks, 
                            text=f"Loading chunk {i+1}/{total_chunks}: {chunk_start.date()} to {chunk_end.date()}")
        
        try:
            # Load chunk data
            gossip_chunk = load_block_gossip_data(network, chunk_start, chunk_end)
            head_chunk = load_head_time_data(network, chunk_start, chunk_end)
            block_chunk = load_canonical_block_data(network, chunk_start, chunk_end)
            
            if not gossip_chunk.empty and not head_chunk.empty and not block_chunk.empty:
                chunk_combined = combine_performance_data(gossip_chunk, head_chunk, block_chunk)
                if not chunk_combined.empty:
                    combined_dfs.append(chunk_combined)
                    
        except Exception as e:
            logger.error(f"Error loading chunk {i+1}: {e}")
            st.warning(f"Skipped chunk {i+1} due to error: {str(e)}")
    
    progress_bar.empty()
    
    if not combined_dfs:
        logger.error("No data loaded from any chunks")
        return {
            'combined_data': pd.DataFrame(),
            'summary_stats': {},
            'period_name': period_name,
            'network': network,
            'start_date': start_date,
            'end_date': end_date,
            'optimization_used': 'chunked_loading_failed'
        }
    
    # Combine all chunks efficiently using Polars
    logger.info(f"Combining {len(combined_dfs)} chunks")
    
    with memory_efficient_context():
        if len(combined_dfs) == 1:
            final_df = combined_dfs[0]
        else:
            # Use Polars for efficient concatenation
            chunk_polars = [pl.from_pandas(df) for df in combined_dfs]
            combined_polars = pl.concat(chunk_polars)
            final_df = combined_polars.sort("slot_start_date_time").to_pandas()
    
    # Calculate summary statistics
    summary_stats = calculate_summary_stats(final_df, start_date, end_date)
    
    logger.info(f"Successfully loaded {len(final_df):,} records from {len(combined_dfs)} chunks")
    
    return {
        'combined_data': final_df,
        'gossip_data': pd.DataFrame(),  # Not preserved in chunked mode
        'head_data': pd.DataFrame(),
        'block_data': pd.DataFrame(),
        'blob_data': pd.DataFrame(),
        'summary_stats': summary_stats,
        'period_name': period_name,
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
        'optimization_used': 'chunked_loading',
        'chunks_loaded': len(combined_dfs)
    }