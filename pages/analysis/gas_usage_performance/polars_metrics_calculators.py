"""
Polars-based metrics calculation utilities for gas usage performance analysis.

This module provides high-performance statistical analysis functions using Polars
for heavy computation while maintaining pandas compatibility for Streamlit.
"""

import polars as pl
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import logging
from contextlib import contextmanager
import gc

# Try to import scipy, but gracefully handle if it's not available
try:
    from scipy.stats import pearsonr, linregress, spearmanr
    from scipy import stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    def pearsonr(x, y):
        raise ImportError("scipy is required for correlation analysis. Please install: pip install scipy>=1.7.0")
    def linregress(x, y):
        raise ImportError("scipy is required for linear regression. Please install: pip install scipy>=1.7.0")
    def spearmanr(x, y):
        raise ImportError("scipy is required for correlation analysis. Please install: pip install scipy>=1.7.0")
    stats = None

from config_utils import get_analysis_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@contextmanager
def memory_efficient_context():
    """Context manager for memory-efficient operations."""
    try:
        yield
    finally:
        gc.collect()


def create_time_buckets_polars(df: pd.DataFrame, num_buckets: int = 30) -> pd.DataFrame:
    """
    Create time buckets using Polars for optimal performance.
    
    Args:
        df: DataFrame with slot_start_date_time column
        num_buckets: Number of time buckets to create
        
    Returns:
        DataFrame with added time bucket columns
    """
    if df.empty or 'slot_start_date_time' not in df.columns:
        logger.warning("Cannot create time buckets: empty DataFrame or missing timestamp column")
        return df
    
    with memory_efficient_context():
        # Convert to Polars for efficient processing
        df_pl = pl.from_pandas(df)
        
        # Ensure proper sorting (datetime should already be correct from pandas)
        df_pl = df_pl.sort(["slot_start_date_time", "slot"])
        
        # Get time range
        time_stats = df_pl.select([
            pl.col("slot_start_date_time").min().alias("min_time"),
            pl.col("slot_start_date_time").max().alias("max_time")
        ]).to_pandas().iloc[0]
        
        min_time = time_stats["min_time"]
        max_time = time_stats["max_time"]
        time_range = max_time - min_time
        bucket_duration = time_range / num_buckets
        
        logger.info(f"Creating {num_buckets} time buckets from {min_time} to {max_time}")
        
        # Create bucket assignments efficiently
        df_pl = df_pl.with_columns([
            # Calculate bucket number (0-based, then make 1-based)
            ((pl.col("slot_start_date_time") - pl.lit(min_time)).dt.total_nanoseconds() / 
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


def create_gas_buckets_polars(df: pd.DataFrame, bucket_size: int = 2_000_000, gas_column: str = 'gas_used') -> pd.DataFrame:
    """
    Create gas usage buckets using Polars for optimal performance.
    
    Args:
        df: DataFrame with gas usage data
        bucket_size: Size of each gas bucket (default: 2M gas)
        gas_column: Column name containing gas usage values
        
    Returns:
        DataFrame with added gas bucket columns
    """
    if df.empty or gas_column not in df.columns:
        logger.warning(f"Cannot create gas buckets: empty DataFrame or missing {gas_column} column")
        return df
    
    with memory_efficient_context():
        # Convert to Polars
        df_pl = pl.from_pandas(df)
        
        # Filter to records with valid gas data
        gas_mask = (pl.col(gas_column).is_not_null()) & (pl.col(gas_column) > 0)
        gas_stats = df_pl.filter(gas_mask).select([
            pl.col(gas_column).min().alias("min_gas"),
            pl.col(gas_column).max().alias("max_gas"),
            pl.col(gas_column).count().alias("valid_count")
        ]).to_pandas().iloc[0]
        
        if gas_stats["valid_count"] == 0:
            logger.warning("No valid gas usage data found for bucketing")
            return df.copy()
        
        min_gas = int(gas_stats["min_gas"])
        max_gas = int(gas_stats["max_gas"])
        
        # Calculate bucket edges
        start_bucket = (min_gas // bucket_size) * bucket_size
        end_bucket = ((max_gas // bucket_size) + 1) * bucket_size
        num_buckets = (end_bucket - start_bucket) // bucket_size
        
        logger.info(f"Creating gas buckets from {min_gas:,} to {max_gas:,} gas with {bucket_size:,} size ({num_buckets} buckets)")
        
        # Create bucket assignments efficiently
        df_pl = df_pl.with_columns([
            # Calculate bucket number (0-based)
            pl.when(gas_mask)
            .then(((pl.col(gas_column) - start_bucket) / bucket_size).floor().cast(pl.Int32))
            .otherwise(None)
            .alias("gas_bucket_0_based")
        ]).with_columns([
            # Make 1-based and add metadata
            pl.when(pl.col("gas_bucket_0_based").is_not_null())
            .then(pl.col("gas_bucket_0_based") + 1)
            .otherwise(None)
            .alias("gas_bucket")
        ]).with_columns([
            # Calculate bucket boundaries
            pl.when(pl.col("gas_bucket_0_based").is_not_null())
            .then(start_bucket + pl.col("gas_bucket_0_based") * bucket_size)
            .otherwise(None)
            .alias("gas_bucket_start"),
            
            pl.when(pl.col("gas_bucket_0_based").is_not_null())
            .then(start_bucket + (pl.col("gas_bucket_0_based") + 1) * bucket_size)
            .otherwise(None)
            .alias("gas_bucket_end")
        ]).with_columns([
            # Midpoint and label
            ((pl.col("gas_bucket_start") + pl.col("gas_bucket_end")) / 2).alias("gas_bucket_midpoint"),
            
            pl.when(pl.col("gas_bucket_start").is_not_null())
            .then(pl.col("gas_bucket_start").cast(pl.Utf8) + "-" + pl.col("gas_bucket_end").cast(pl.Utf8))
            .otherwise(None)
            .alias("gas_bucket_label")
        ])
        
        # Convert back to pandas and sort
        result_df = df_pl.drop("gas_bucket_0_based").to_pandas()
        result_df = result_df.sort_values(['gas_bucket', 'slot_start_date_time'], na_position='last').reset_index(drop=True)
        
        gas_buckets_created = result_df['gas_bucket'].nunique()
        records_with_buckets = result_df['gas_bucket'].notna().sum()
        
        logger.info(f"Created {gas_buckets_created} gas buckets for {records_with_buckets:,}/{len(df):,} records")
        
        return result_df


def aggregate_data_polars(
    df: pd.DataFrame,
    group_by: List[str] = None,
    metrics: List[str] = None,
    agg_function: str = 'mean'
) -> pd.DataFrame:
    """
    Flexible aggregation using Polars for optimal performance.
    
    Args:
        df: DataFrame with client-level data
        group_by: Columns to group by
        metrics: Metrics to aggregate
        agg_function: Aggregation function
        
    Returns:
        DataFrame with aggregated data
    """
    if df.empty:
        logger.warning("Cannot aggregate: empty DataFrame")
        return pd.DataFrame()
    
    group_by = group_by or ['slot']
    metrics = metrics or ['block_gossip_time', 'head_time', 'gas_used', 'gas_utilization']
    
    with memory_efficient_context():
        # Convert to Polars
        df_pl = pl.from_pandas(df)
        
        # Filter to existing columns
        available_group_cols = [col for col in group_by if col in df_pl.columns]
        available_metric_cols = [col for col in metrics if col in df_pl.columns]
        
        if not available_group_cols or not available_metric_cols:
            logger.warning("Missing required columns for aggregation")
            return df
        
        # Map aggregation functions
        agg_expressions = []
        for col in available_metric_cols:
            if agg_function == 'mean':
                agg_expressions.append(pl.col(col).mean().alias(col))
            elif agg_function == 'median':
                agg_expressions.append(pl.col(col).median().alias(col))
            elif agg_function == 'p95':
                agg_expressions.append(pl.col(col).quantile(0.95).alias(col))
            elif agg_function == 'p99':
                agg_expressions.append(pl.col(col).quantile(0.99).alias(col))
            elif agg_function == 'min':
                agg_expressions.append(pl.col(col).min().alias(col))
            elif agg_function == 'max':
                agg_expressions.append(pl.col(col).max().alias(col))
            elif agg_function == 'std':
                agg_expressions.append(pl.col(col).std().alias(col))
            elif agg_function == 'count':
                agg_expressions.append(pl.col(col).count().alias(col))
            else:
                agg_expressions.append(pl.col(col).mean().alias(col))  # Default fallback
        
        # Perform aggregation
        aggregated_pl = df_pl.group_by(available_group_cols).agg(agg_expressions)
        
        # Add metadata columns
        metadata_cols = ['slot_start_date_time', 'bucket_start_time', 'bucket_midpoint', 'bucket_midpoint_numeric']
        for col in metadata_cols:
            if col in df_pl.columns and col not in available_group_cols:
                metadata_expr = df_pl.group_by(available_group_cols).agg([
                    pl.col(col).first().alias(col)
                ])
                aggregated_pl = aggregated_pl.join(metadata_expr, on=available_group_cols, how="left")
        
        # Sort result
        if 'slot' in aggregated_pl.columns:
            aggregated_pl = aggregated_pl.sort('slot')
        elif 'bucket_number' in aggregated_pl.columns:
            aggregated_pl = aggregated_pl.sort('bucket_number')
        elif 'gas_bucket' in aggregated_pl.columns:
            aggregated_pl = aggregated_pl.sort('gas_bucket')
        elif 'slot_start_date_time' in aggregated_pl.columns:
            aggregated_pl = aggregated_pl.sort('slot_start_date_time')
        
        result_df = aggregated_pl.to_pandas()
        
        logger.info(f"Aggregated data: {len(df)} -> {len(result_df)} records using {agg_function}")
        return result_df


def calculate_bucket_metrics_polars(
    df: pd.DataFrame,
    group_cols: List[str] = None,
    metric_cols: List[str] = None,
    agg_function: str = 'mean'
) -> pd.DataFrame:
    """
    Calculate aggregated metrics for each time bucket using polars processing.
    
    Args:
        df: DataFrame with time buckets
        group_cols: Additional columns to group by (beyond bucket)
        metric_cols: Columns to calculate metrics for
        agg_function: Aggregation function to use
        
    Returns:
        DataFrame with aggregated metrics per bucket
    """
    if df.empty:
        logger.warning("Cannot calculate bucket metrics: empty DataFrame")
        return pd.DataFrame()
    
    # Use bucket_number or time_bucket_label for grouping
    bucket_col = 'bucket_number' if 'bucket_number' in df.columns else 'time_bucket_label'
    if bucket_col not in df.columns:
        logger.warning("Cannot calculate bucket metrics: missing bucket columns")
        return df
    
    group_by = [bucket_col] + (group_cols or [])
    metric_cols = metric_cols or ['gas_used', 'block_gossip_time', 'head_time', 'gas_utilization']
    
    return aggregate_data_polars(df, group_by, metric_cols, agg_function)


def calculate_correlation_analysis_polars(
    df: pd.DataFrame, 
    x_col: str, 
    y_col: str,
    method: str = 'pearson'
) -> Optional[Dict[str, float]]:
    """
    Calculate correlation analysis with Polars preprocessing for performance.
    
    Args:
        df: DataFrame containing the data
        x_col: Column name for x-axis variable
        y_col: Column name for y-axis variable  
        method: Correlation method ('pearson' or 'spearman')
        
    Returns:
        Dictionary with correlation statistics or None if insufficient data
    """
    if df.empty or x_col not in df.columns or y_col not in df.columns:
        logger.warning(f"Cannot calculate correlation: missing columns {x_col} or {y_col}")
        return None
    
    with memory_efficient_context():
        # Use Polars to efficiently clean and filter data
        df_pl = pl.from_pandas(df)
        
        # Safely cast columns to float, handling any data type issues
        clean_pl = df_pl.select([
            pl.col(x_col),
            pl.col(y_col)
        ]).with_columns([
            pl.col(x_col).cast(pl.Float64, strict=False),
            pl.col(y_col).cast(pl.Float64, strict=False)
        ]).filter(
            pl.col(x_col).is_not_null() & 
            pl.col(y_col).is_not_null() &
            pl.col(x_col).is_finite() &
            pl.col(y_col).is_finite()
        )
        
        if clean_pl.height < 10:
            logger.warning(f"Insufficient data for correlation analysis: {clean_pl.height} samples")
            return None
        
        # Convert to numpy arrays for scipy
        clean_df = clean_pl.to_pandas()
        x_values = clean_df[x_col].values
        y_values = clean_df[y_col].values
        
        try:
            # Correlation analysis
            if method == 'pearson':
                corr_coef, p_value = pearsonr(x_values, y_values)
            else:
                corr_coef, p_value = spearmanr(x_values, y_values)
            
            # Linear regression for trend line
            slope, intercept, r_value, reg_p_value, std_err = linregress(x_values, y_values)
            
            return {
                'correlation': float(corr_coef),
                'p_value': float(p_value),
                'slope': float(slope),
                'intercept': float(intercept),
                'r_squared': float(r_value ** 2),
                'std_error': float(std_err),
                'sample_size': len(clean_df),
                'method': method,
                'significant': p_value < 0.05
            }
            
        except Exception as e:
            logger.error(f"Error calculating correlation: {e}")
            return None


def calculate_temporal_trends_polars(
    df: pd.DataFrame,
    time_col: str = 'bucket_midpoint_numeric',
    metric_cols: List[str] = None
) -> Dict[str, Dict[str, float]]:
    """
    Calculate temporal trends using Polars for preprocessing.
    
    Args:
        df: DataFrame with time buckets and metrics
        time_col: Time column for trend analysis (should be numeric)
        metric_cols: Metrics to analyze for trends
        
    Returns:
        Dictionary of trend statistics for each metric
    """
    if df.empty:
        logger.warning("Cannot calculate temporal trends: empty DataFrame")
        return {}
    
    with memory_efficient_context():
        # Use Polars to efficiently prepare data
        df_pl = pl.from_pandas(df)
        
        # Determine time column
        if 'bucket_midpoint_numeric' in df_pl.columns:
            time_col = 'bucket_midpoint_numeric'
        elif 'bucket_number' in df_pl.columns:
            time_col = 'bucket_number'
        else:
            logger.warning("No suitable time column for trend analysis")
            return {}
        
        metric_cols = metric_cols or ['gas_used', 'block_gossip_time', 'head_time']
        available_metrics = [col for col in metric_cols if col in df_pl.columns]
        
        if not available_metrics:
            logger.warning("No metric columns available for trend analysis")
            return {}
        
        # Clean data efficiently
        select_cols = [time_col] + available_metrics
        clean_pl = df_pl.select(select_cols).filter(
            pl.all_horizontal([pl.col(col).is_not_null() & pl.col(col).is_finite() for col in select_cols])
        )
        
        if clean_pl.height < 3:
            logger.warning("Insufficient data for trend analysis")
            return {}
        
        clean_df = clean_pl.to_pandas()
        time_values = clean_df[time_col].astype(float).values
        
        trends = {}
        
        for metric in available_metrics:
            try:
                if not SCIPY_AVAILABLE:
                    logger.warning(f"Cannot calculate trend for {metric}: scipy not available")
                    trends[metric] = None
                    continue
                    
                metric_values = clean_df[metric].values
                slope, intercept, r_value, p_value, std_err = linregress(time_values, metric_values)
                
                trends[metric] = {
                    'slope': float(slope),
                    'intercept': float(intercept),
                    'r_squared': float(r_value ** 2),
                    'p_value': float(p_value),
                    'std_error': float(std_err),
                    'trend_direction': 'increasing' if slope > 0 else 'decreasing',
                    'significant': p_value < 0.05,
                    'sample_size': len(clean_df)
                }
                
            except Exception as e:
                logger.error(f"Error calculating trend for {metric}: {e}")
                trends[metric] = None
        
        logger.info(f"Calculated temporal trends for {len(trends)} metrics")
        return trends


def calculate_percentile_analysis_polars(
    df: pd.DataFrame,
    metric_cols: List[str] = None,
    percentiles: List[float] = None
) -> pd.DataFrame:
    """
    Calculate percentile analysis using Polars for efficient computation.
    
    Args:
        df: DataFrame with metrics
        metric_cols: Columns to analyze
        percentiles: List of percentiles to calculate (0-1)
        
    Returns:
        DataFrame with percentile statistics
    """
    if df.empty:
        logger.warning("Cannot calculate percentiles: empty DataFrame")
        return pd.DataFrame()
    
    metric_cols = metric_cols or ['gas_used', 'block_gossip_time', 'head_time', 'gas_utilization']
    percentiles = percentiles or [0.05, 0.25, 0.5, 0.75, 0.95, 0.99]
    
    with memory_efficient_context():
        df_pl = pl.from_pandas(df)
        available_metrics = [col for col in metric_cols if col in df_pl.columns]
        
        if not available_metrics:
            logger.warning("No metric columns available for percentile analysis")
            return pd.DataFrame()
        
        percentile_results = []
        
        for metric in available_metrics:
            # Use Polars for efficient percentile calculations
            metric_stats = df_pl.select([
                pl.col(metric).drop_nulls().alias("clean_metric")
            ]).select([
                pl.col("clean_metric").count().alias("count"),
                pl.col("clean_metric").mean().alias("mean"),
                pl.col("clean_metric").std().alias("std")
            ] + [
                pl.col("clean_metric").quantile(p).alias(f"p{int(p*100)}")
                for p in percentiles
            ])
            
            if metric_stats.height > 0:
                stats_dict = metric_stats.to_pandas().iloc[0].to_dict()
                stats_dict['metric'] = metric
                
                # Convert to regular Python types
                for key, value in stats_dict.items():
                    if pd.notna(value) and key != 'metric':
                        stats_dict[key] = float(value)
                
                percentile_results.append(stats_dict)
        
        result_df = pd.DataFrame(percentile_results)
        logger.info(f"Calculated percentiles for {len(result_df)} metrics")
        return result_df


def sample_large_dataset(df: pd.DataFrame, max_rows: int = 100_000, strategy: str = 'stratified') -> pd.DataFrame:
    """
    Sample large datasets intelligently to prevent memory issues while preserving patterns.
    
    Args:
        df: Input DataFrame
        max_rows: Maximum rows to keep
        strategy: Sampling strategy ('random', 'stratified', 'time_based')
        
    Returns:
        Sampled DataFrame
    """
    if len(df) <= max_rows:
        return df
    
    logger.info(f"Sampling dataset from {len(df):,} to {max_rows:,} rows using {strategy} strategy")
    
    with memory_efficient_context():
        df_pl = pl.from_pandas(df)
        
        if strategy == 'random':
            sampled_pl = df_pl.sample(n=max_rows)
        
        elif strategy == 'time_based' and 'slot_start_date_time' in df_pl.columns:
            # Sample evenly across time
            df_sorted = df_pl.sort('slot_start_date_time')
            step = len(df_sorted) // max_rows
            sampled_pl = df_sorted.slice(0, None, step)
        
        elif strategy == 'stratified' and 'meta_consensus_implementation' in df_pl.columns:
            # Stratified sampling by consensus implementation
            implementations = df_pl.select(pl.col('meta_consensus_implementation').unique()).to_pandas()['meta_consensus_implementation'].tolist()
            samples_per_impl = max_rows // len(implementations)
            
            sampled_parts = []
            for impl in implementations:
                impl_data = df_pl.filter(pl.col('meta_consensus_implementation') == impl)
                if impl_data.height > 0:
                    sample_size = min(samples_per_impl, impl_data.height)
                    sampled_parts.append(impl_data.sample(n=sample_size))
            
            if sampled_parts:
                sampled_pl = pl.concat(sampled_parts)
            else:
                sampled_pl = df_pl.sample(n=max_rows)
        
        else:
            # Fallback to random sampling
            sampled_pl = df_pl.sample(n=max_rows)
        
        result_df = sampled_pl.to_pandas()
        logger.info(f"Sampled dataset to {len(result_df):,} rows")
        return result_df