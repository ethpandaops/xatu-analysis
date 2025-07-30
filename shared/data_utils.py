"""
Data processing utilities for analysis
"""
import pandas as pd
import polars as pl
import gc
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Tuple, List
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_aggregate_function(aggregate):
    """Convert aggregate string to pandas function."""
    agg_map = {
        'mean': 'mean',
        'min': 'min',
        'max': 'max',
        'median': 'median',
        'p05': lambda x: x.quantile(0.05),
        'p50': lambda x: x.quantile(0.50),
        'p90': lambda x: x.quantile(0.90),
        'p95': lambda x: x.quantile(0.95),
        'p99': lambda x: x.quantile(0.99)
    }
    return agg_map.get(aggregate, 'mean')


@contextmanager
def memory_efficient_context():
    """Context manager for memory-efficient operations."""
    try:
        yield
    finally:
        gc.collect()


def normalize_time_range(start_date: datetime, end_date: datetime, max_days: int = None) -> Tuple[datetime, datetime, bool]:
    """
    No longer normalizes time range - just returns the original dates.
    Users can request any amount of data, and if it's too much the system will error naturally.
    
    Args:
        start_date: Original start date
        end_date: Original end date
        max_days: Ignored parameter kept for compatibility
        
    Returns:
        Tuple of (start_date, end_date, False)
    """
    # No longer limit time ranges - let user request what they want
    _ = max_days  # Suppress unused parameter warning
    return start_date, end_date, False


def chunk_time_range(start_date: datetime, end_date: datetime, chunk_days: int = 7) -> List[Tuple[datetime, datetime]]:
    """
    Split large time ranges into smaller chunks for processing.
    
    Args:
        start_date: Analysis start date
        end_date: Analysis end date
        chunk_days: Days per chunk
        
    Returns:
        List of (start, end) date tuples
    """
    chunks = []
    current_start = start_date
    
    while current_start < end_date:
        current_end = min(current_start + timedelta(days=chunk_days), end_date)
        chunks.append((current_start, current_end))
        current_start = current_end
    
    return chunks


def create_time_buckets(df: pd.DataFrame, num_buckets: int = 30, time_col: str = 'slot_start_date_time') -> pd.DataFrame:
    """
    Create time buckets using Polars for optimal performance.
    
    Args:
        df: DataFrame with datetime column
        num_buckets: Number of time buckets to create
        time_col: Name of the datetime column
        
    Returns:
        DataFrame with added time bucket columns
    """
    if df.empty or time_col not in df.columns:
        logger.warning(f"Cannot create time buckets: empty DataFrame or missing {time_col} column")
        return df
    
    with memory_efficient_context():
        # Convert to Polars for efficient processing
        df_pl = pl.from_pandas(df)
        
        # Ensure proper sorting
        if 'slot' in df_pl.columns:
            df_pl = df_pl.sort([time_col, "slot"])
        else:
            df_pl = df_pl.sort(time_col)
        
        # Get time range
        time_stats = df_pl.select([
            pl.col(time_col).min().alias("min_time"),
            pl.col(time_col).max().alias("max_time")
        ]).to_pandas().iloc[0]
        
        min_time = time_stats["min_time"]
        max_time = time_stats["max_time"]
        time_range = max_time - min_time
        bucket_duration = time_range / num_buckets
        
        logger.info(f"Creating {num_buckets} time buckets from {min_time} to {max_time}")
        
        # Create bucket assignments efficiently
        df_pl = df_pl.with_columns([
            # Calculate bucket number (0-based, then make 1-based)
            ((pl.col(time_col) - pl.lit(min_time)).dt.total_nanoseconds() / 
             pl.lit(bucket_duration.total_seconds() * 1e9)).floor().cast(pl.Int32).alias("bucket_number_raw")
        ]).with_columns([
            # Clamp to valid range and make 1-based
            pl.when(pl.col("bucket_number_raw") >= num_buckets)
            .then(pl.lit(num_buckets - 1))
            .otherwise(pl.col("bucket_number_raw"))
            .alias("bucket_number_0_based")
        ]).with_columns([
            (pl.col("bucket_number_0_based") + 1).alias("bucket_number")
        ])
        
        # Add bucket metadata
        bucket_start_seconds = pl.col("bucket_number_0_based") * bucket_duration.total_seconds()
        bucket_end_seconds = (pl.col("bucket_number_0_based") + 1) * bucket_duration.total_seconds()
        
        df_pl = df_pl.with_columns([
            (pl.lit(min_time) + pl.duration(seconds=bucket_start_seconds)).alias("bucket_start_time"),
            (pl.lit(min_time) + pl.duration(seconds=bucket_end_seconds)).alias("bucket_end_time"),
            (pl.lit("Bucket ") + pl.col("bucket_number").cast(pl.Utf8)).alias("time_bucket_label")
        ]).with_columns([
            (pl.col("bucket_start_time") + 
             (pl.col("bucket_end_time") - pl.col("bucket_start_time")) / 2).alias("bucket_midpoint")
        ]).with_columns([
            (pl.col("bucket_midpoint") - pl.lit(min_time)).dt.total_seconds().alias("bucket_midpoint_numeric")
        ])
        
        # Convert back to pandas
        result_df = df_pl.drop(["bucket_number_raw", "bucket_number_0_based"]).to_pandas()
        
        logger.info(f"Created time buckets with {bucket_duration} duration each")
        return result_df


def create_numeric_buckets(df: pd.DataFrame, bucket_size: int, numeric_column: str, bucket_prefix: str = 'bucket') -> pd.DataFrame:
    """
    Create numeric buckets using Polars for optimal performance.
    Generic function that can be used for gas, transactions, or any numeric data.
    
    Args:
        df: DataFrame with numeric data
        bucket_size: Size of each bucket
        numeric_column: Column name containing numeric values to bucket
        bucket_prefix: Prefix for bucket column names (e.g., 'gas', 'tx')
        
    Returns:
        DataFrame with added bucket columns
    """
    if df.empty or numeric_column not in df.columns:
        logger.warning(f"Cannot create numeric buckets: empty DataFrame or missing {numeric_column} column")
        return df
    
    with memory_efficient_context():
        # Convert to Polars
        df_pl = pl.from_pandas(df)
        
        # Filter to records with valid numeric data
        numeric_mask = (pl.col(numeric_column).is_not_null()) & (pl.col(numeric_column) > 0)
        numeric_stats = df_pl.filter(numeric_mask).select([
            pl.col(numeric_column).min().alias("min_val"),
            pl.col(numeric_column).max().alias("max_val"),
            pl.col(numeric_column).count().alias("valid_count")
        ]).to_pandas().iloc[0]
        
        if numeric_stats["valid_count"] == 0:
            logger.warning(f"No valid {numeric_column} data found for bucketing")
            return df.copy()
        
        min_val = int(numeric_stats["min_val"])
        max_val = int(numeric_stats["max_val"])
        
        # Calculate bucket edges
        start_bucket = (min_val // bucket_size) * bucket_size
        end_bucket = ((max_val // bucket_size) + 1) * bucket_size
        num_buckets = (end_bucket - start_bucket) // bucket_size
        
        logger.info(f"Creating {bucket_prefix} buckets from {min_val:,} to {max_val:,} with {bucket_size:,} size ({num_buckets} buckets)")
        
        # Create bucket assignments efficiently
        df_pl = df_pl.with_columns([
            # Calculate bucket number (0-based)
            pl.when(numeric_mask)
            .then(((pl.col(numeric_column) - start_bucket) / bucket_size).floor().cast(pl.Int32))
            .otherwise(None)
            .alias(f"{bucket_prefix}_bucket_0_based")
        ]).with_columns([
            # Make 1-based and add metadata
            pl.when(pl.col(f"{bucket_prefix}_bucket_0_based").is_not_null())
            .then(pl.col(f"{bucket_prefix}_bucket_0_based") + 1)
            .otherwise(None)
            .alias(f"{bucket_prefix}_bucket")
        ]).with_columns([
            # Calculate bucket boundaries
            pl.when(pl.col(f"{bucket_prefix}_bucket_0_based").is_not_null())
            .then(start_bucket + pl.col(f"{bucket_prefix}_bucket_0_based") * bucket_size)
            .otherwise(None)
            .alias(f"{bucket_prefix}_bucket_start"),
            
            pl.when(pl.col(f"{bucket_prefix}_bucket_0_based").is_not_null())
            .then(start_bucket + (pl.col(f"{bucket_prefix}_bucket_0_based") + 1) * bucket_size)
            .otherwise(None)
            .alias(f"{bucket_prefix}_bucket_end")
        ]).with_columns([
            # Midpoint and label
            ((pl.col(f"{bucket_prefix}_bucket_start") + pl.col(f"{bucket_prefix}_bucket_end")) / 2).alias(f"{bucket_prefix}_bucket_midpoint"),
            
            pl.when(pl.col(f"{bucket_prefix}_bucket_start").is_not_null())
            .then(pl.col(f"{bucket_prefix}_bucket_start").cast(pl.Utf8) + "-" + pl.col(f"{bucket_prefix}_bucket_end").cast(pl.Utf8))
            .otherwise(None)
            .alias(f"{bucket_prefix}_bucket_label")
        ])
        
        # Convert back to pandas and sort
        result_df = df_pl.drop(f"{bucket_prefix}_bucket_0_based").to_pandas()
        
        # Sort by bucket and original time column if available
        sort_cols = [f'{bucket_prefix}_bucket']
        if 'slot_start_date_time' in result_df.columns:
            sort_cols.append('slot_start_date_time')
        result_df = result_df.sort_values(sort_cols, na_position='last').reset_index(drop=True)
        
        buckets_created = result_df[f'{bucket_prefix}_bucket'].nunique()
        records_with_buckets = result_df[f'{bucket_prefix}_bucket'].notna().sum()
        
        logger.info(f"Created {buckets_created} {bucket_prefix} buckets for {records_with_buckets:,}/{len(df):,} records")
        
        return result_df
