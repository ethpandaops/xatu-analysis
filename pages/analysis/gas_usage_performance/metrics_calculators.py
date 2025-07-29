"""
Metrics calculation utilities for gas usage performance analysis.

This module provides statistical analysis functions including time bucketing,
correlation analysis, trend calculations, and consensus implementation ranking.
Now includes Polars-optimized functions for better performance.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import logging
# Try to import scipy, but gracefully handle if it's not available
try:
    from scipy.stats import pearsonr, linregress, spearmanr
    from scipy import stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    # Create dummy functions for when scipy is not available
    def pearsonr(x, y):
        raise ImportError("scipy is required for correlation analysis. Please install: pip install scipy>=1.7.0")
    def linregress(x, y):
        raise ImportError("scipy is required for linear regression. Please install: pip install scipy>=1.7.0")
    def spearmanr(x, y):
        raise ImportError("scipy is required for correlation analysis. Please install: pip install scipy>=1.7.0")
    stats = None

from pages.analysis.gas_usage_performance.config_utils import get_analysis_config, get_aggregation_functions

# Import polars functions
try:
    from pages.analysis.gas_usage_performance.polars_metrics_calculators import (
        create_time_buckets_polars,
        create_gas_buckets_polars,
        aggregate_data_polars,
        calculate_bucket_metrics_polars,
        calculate_correlation_analysis_polars,
        calculate_temporal_trends_polars,
        calculate_percentile_analysis_polars,
        sample_large_dataset
    )
    POLARS_METRICS_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("Polars metrics calculators available")
except ImportError as e:
    POLARS_METRICS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning(f"Polars metrics calculators not available: {e}")
    logger.info("Falling back to pandas-based metrics calculators")


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_time_buckets(df: pd.DataFrame, num_buckets: int = 30) -> pd.DataFrame:
    """
    Create time buckets using polars implementation with fallback.
    
    Args:
        df: DataFrame with slot_start_date_time column
        num_buckets: Number of time buckets to create
        
    Returns:
        DataFrame with added time bucket columns
    """
    # Use polars version for large datasets
    if POLARS_METRICS_AVAILABLE and len(df) > 50_000:
        logger.info(f"Using polars time bucketing for {len(df):,} records")
        try:
            return create_time_buckets_polars(df, num_buckets)
        except Exception as e:
            logger.warning(f"Polars time bucketing failed: {e}, falling back to standard")
    
    return create_time_buckets_standard(df, num_buckets)


def create_gas_buckets(df: pd.DataFrame, bucket_size: int = 2_000_000, gas_column: str = 'gas_used') -> pd.DataFrame:
    """
    Create gas buckets using polars implementation with fallback.
    
    Args:
        df: DataFrame with gas usage data
        bucket_size: Size of each gas bucket
        gas_column: Column name containing gas usage values
        
    Returns:
        DataFrame with added gas bucket columns
    """
    # Use polars version for large datasets
    if POLARS_METRICS_AVAILABLE and len(df) > 30_000:
        logger.info(f"Using polars gas bucketing for {len(df):,} records")
        try:
            return create_gas_buckets_polars(df, bucket_size, gas_column)
        except Exception as e:
            logger.warning(f"Polars gas bucketing failed: {e}, falling back to standard")
    
    return create_gas_buckets_standard(df, bucket_size, gas_column)


def aggregate_data(
    df: pd.DataFrame,
    group_by: List[str] = None,
    metrics: List[str] = None,
    agg_function: str = 'mean'
) -> pd.DataFrame:
    """
    Aggregate data using polars implementation with fallback.
    
    Args:
        df: DataFrame with client-level data
        group_by: Columns to group by
        metrics: Metrics to aggregate
        agg_function: Aggregation function
        
    Returns:
        DataFrame with aggregated data
    """
    # Use polars version for large datasets
    if POLARS_METRICS_AVAILABLE and len(df) > 25_000:
        logger.info(f"Using polars aggregation for {len(df):,} records")
        try:
            return aggregate_data_polars(df, group_by, metrics, agg_function)
        except Exception as e:
            logger.warning(f"Polars aggregation failed: {e}, falling back to standard")
    
    return aggregate_data_standard(df, group_by, metrics, agg_function)


def calculate_correlation_analysis(
    df: pd.DataFrame, 
    x_col: str, 
    y_col: str,
    method: str = 'pearson'
) -> Optional[Dict[str, float]]:
    """
    Calculate correlation analysis using polars implementation with fallback.
    
    Args:
        df: DataFrame containing the data
        x_col: Column name for x-axis variable
        y_col: Column name for y-axis variable  
        method: Correlation method
        
    Returns:
        Dictionary with correlation statistics
    """
    # Use polars version for large datasets
    if POLARS_METRICS_AVAILABLE and len(df) > 10_000:
        logger.info(f"Using polars correlation analysis for {len(df):,} records")
        try:
            return calculate_correlation_analysis_polars(df, x_col, y_col, method)
        except Exception as e:
            logger.warning(f"Polars correlation analysis failed: {e}, falling back to standard")
    
    return calculate_correlation_analysis_standard(df, x_col, y_col, method)


def prepare_large_dataset(df: pd.DataFrame, max_rows: int = 100_000) -> pd.DataFrame:
    """
    Prepare large datasets for analysis by sampling if necessary.
    
    Args:
        df: Input DataFrame
        max_rows: Maximum rows to keep
        
    Returns:
        Prepared DataFrame
    """
    if len(df) <= max_rows:
        return df
    
    if POLARS_METRICS_AVAILABLE:
        logger.info(f"Sampling large dataset from {len(df):,} to {max_rows:,} rows")
        try:
            return sample_large_dataset(df, max_rows, strategy='stratified')
        except Exception as e:
            logger.warning(f"Polars sampling failed: {e}, using simple random sample")
    
    # Fallback to simple random sampling
    return df.sample(n=max_rows, random_state=42)


def create_time_buckets_standard(df: pd.DataFrame, num_buckets: int = 30) -> pd.DataFrame:
    """
    Create equal-duration time buckets for temporal analysis.
    Fixes data type issues for temporal calculations.
    
    Args:
        df: DataFrame with slot_start_date_time column
        num_buckets: Number of time buckets to create
        
    Returns:
        DataFrame with added time bucket columns
    """
    if df.empty or 'slot_start_date_time' not in df.columns:
        logger.warning("Cannot create time buckets: empty DataFrame or missing timestamp column")
        return df
    
    df = df.copy()
    
    # Convert to datetime if not already
    df['slot_start_date_time'] = pd.to_datetime(df['slot_start_date_time'])
    
    # CRITICAL: Sort by time BEFORE creating buckets to ensure proper temporal ordering
    df = df.sort_values(['slot_start_date_time', 'slot']).reset_index(drop=True)
    
    min_time = df['slot_start_date_time'].min()
    max_time = df['slot_start_date_time'].max()
    time_range = max_time - min_time
    bucket_size = time_range / num_buckets
    
    logger.info(f"Creating {num_buckets} time buckets from {min_time} to {max_time}")
    
    # Create bucket edges
    bucket_edges = [min_time + i * bucket_size for i in range(num_buckets + 1)]
    
    # Create numeric bucket assignments (0-based)
    df['bucket_number'] = pd.cut(
        df['slot_start_date_time'],
        bins=bucket_edges,
        labels=False,
        include_lowest=True
    ) + 1  # Make 1-based
    
    # Create string labels for display
    bucket_labels = [f"Bucket {i+1}" for i in range(num_buckets)]
    df['time_bucket_label'] = pd.cut(
        df['slot_start_date_time'],
        bins=bucket_edges,
        labels=bucket_labels,
        include_lowest=True
    )
    
    # Add bucket metadata as proper datetime columns (not mapped from categorical)
    if not df.empty and 'bucket_number' in df.columns:
        # Create mapping for bucket start/end times
        bucket_start_map = {i+1: bucket_edges[i] for i in range(num_buckets)}
        bucket_end_map = {i+1: bucket_edges[i+1] for i in range(num_buckets)}
        
        df['bucket_start_time'] = df['bucket_number'].map(bucket_start_map)
        df['bucket_end_time'] = df['bucket_number'].map(bucket_end_map)
    else:
        df['bucket_start_time'] = None
        df['bucket_end_time'] = None
    
    # Calculate midpoint properly as datetime
    df['bucket_midpoint'] = df['bucket_start_time'] + (df['bucket_end_time'] - df['bucket_start_time']) / 2
    
    # Add numeric time for calculations (seconds from min_time)
    df['bucket_midpoint_numeric'] = (df['bucket_midpoint'] - min_time).dt.total_seconds()
    
    logger.info(f"Created time buckets with {bucket_size} duration each")
    return df


def create_gas_buckets_standard(df: pd.DataFrame, bucket_size: int = 2_000_000, gas_column: str = 'gas_used') -> pd.DataFrame:
    """
    Create gas usage buckets for aggregation analysis.
    
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
    
    df = df.copy()
    
    # Remove records without gas data
    gas_df = df[df[gas_column].notna() & (df[gas_column] > 0)].copy()
    
    if gas_df.empty:
        logger.warning("No valid gas usage data found for bucketing")
        return df
    
    # Calculate gas bucket ranges
    min_gas = int(gas_df[gas_column].min())
    max_gas = int(gas_df[gas_column].max())
    
    # Create bucket edges aligned to bucket_size boundaries
    start_bucket = (min_gas // bucket_size) * bucket_size
    end_bucket = ((max_gas // bucket_size) + 1) * bucket_size
    
    bucket_edges = list(range(start_bucket, end_bucket + bucket_size, bucket_size))
    
    logger.info(f"Creating gas buckets from {min_gas:,} to {max_gas:,} gas with {bucket_size:,} size")
    logger.info(f"Bucket edges: {len(bucket_edges)-1} buckets from {bucket_edges[0]:,} to {bucket_edges[-1]:,}")
    
    # Create gas bucket assignments
    gas_df['gas_bucket_range'] = pd.cut(
        gas_df[gas_column],
        bins=bucket_edges,
        include_lowest=True,
        precision=0
    )
    
    # Create numeric bucket numbers for easier aggregation
    gas_df['gas_bucket'] = pd.cut(
        gas_df[gas_column],
        bins=bucket_edges,
        labels=False,
        include_lowest=True
    ) + 1  # Make 1-based
    
    # Add bucket metadata - extract numeric values from intervals
    # Use the bucket_edges directly for accurate start/end values
    bucket_start_map = {i: bucket_edges[i] for i in range(len(bucket_edges) - 1)}
    bucket_end_map = {i: bucket_edges[i + 1] for i in range(len(bucket_edges) - 1)}
    
    # Map bucket numbers (0-based from pd.cut) to actual gas values
    gas_df['gas_bucket_start'] = (gas_df['gas_bucket'] - 1).map(bucket_start_map)
    gas_df['gas_bucket_end'] = (gas_df['gas_bucket'] - 1).map(bucket_end_map)
    gas_df['gas_bucket_midpoint'] = (gas_df['gas_bucket_start'] + gas_df['gas_bucket_end']) / 2
    
    # Create readable labels
    gas_df['gas_bucket_label'] = gas_df.apply(
        lambda row: f"{row['gas_bucket_start']:,}-{row['gas_bucket_end']:,}" 
        if pd.notna(row['gas_bucket_start']) and pd.notna(row['gas_bucket_end']) 
        else f"Bucket {row['gas_bucket']}", 
        axis=1
    )
    
    # Merge back with original data (records without gas data will have NaN buckets)
    result_df = df.merge(
        gas_df[['gas_bucket', 'gas_bucket_range', 'gas_bucket_start', 'gas_bucket_end', 
                'gas_bucket_midpoint', 'gas_bucket_label'] + [gas_column]],
        on=gas_column,
        how='left',
        suffixes=('', '_temp')
    )
    
    # Sort by gas bucket to maintain logical ordering
    result_df = result_df.sort_values(['gas_bucket', 'slot_start_date_time'], na_position='last').reset_index(drop=True)
    
    gas_buckets_created = result_df['gas_bucket'].nunique()
    records_with_buckets = result_df['gas_bucket'].notna().sum()
    
    logger.info(f"Created {gas_buckets_created} gas buckets for {records_with_buckets:,}/{len(df):,} records")
    
    return result_df


def calculate_correlation_analysis_standard(
    df: pd.DataFrame, 
    x_col: str, 
    y_col: str,
    method: str = 'pearson'
) -> Optional[Dict[str, float]]:
    """
    Calculate correlation analysis with statistical significance.
    
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
    
    # Remove NaN values
    mask = df[[x_col, y_col]].notna().all(axis=1)
    clean_df = df.loc[mask]
    
    if len(clean_df) < 10:
        logger.warning(f"Insufficient data for correlation analysis: {len(clean_df)} samples")
        return None
    
    try:
        # Correlation analysis
        if method == 'pearson':
            corr_coef, p_value = pearsonr(clean_df[x_col], clean_df[y_col])
        else:
            corr_coef, p_value = spearmanr(clean_df[x_col], clean_df[y_col])
        
        # Linear regression for trend line
        slope, intercept, r_value, reg_p_value, std_err = linregress(
            clean_df[x_col], clean_df[y_col]
        )
        
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


def aggregate_data_standard(
    df: pd.DataFrame,
    group_by: List[str] = None,
    metrics: List[str] = None,
    agg_function: str = 'mean'
) -> pd.DataFrame:
    """
    Flexible aggregation function for user-controlled data summarization.
    
    Args:
        df: DataFrame with client-level data
        group_by: Columns to group by (e.g., ['slot'], ['meta_consensus_implementation'], ['bucket_number'])
        metrics: Metrics to aggregate
        agg_function: Aggregation function ('mean', 'median', 'p95', etc.)
        
    Returns:
        DataFrame with aggregated data
    """
    if df.empty:
        logger.warning("Cannot aggregate: empty DataFrame")
        return pd.DataFrame()
    
    group_by = group_by or ['slot']
    metrics = metrics or ['block_gossip_time', 'head_time', 'gas_used', 'gas_utilization']
    
    # Filter to existing columns
    available_group_cols = [col for col in group_by if col in df.columns]
    available_metric_cols = [col for col in metrics if col in df.columns]
    
    if not available_group_cols or not available_metric_cols:
        logger.warning("Missing required columns for aggregation")
        return df
    
    # Map aggregation function names to pandas functions
    agg_func_map = {
        'mean': 'mean',
        'median': 'median', 
        'p95': lambda x: x.quantile(0.95),
        'p99': lambda x: x.quantile(0.99),
        'min': 'min',
        'max': 'max',
        'std': 'std',
        'count': 'count'
    }
    
    if agg_function not in agg_func_map:
        logger.warning(f"Unknown aggregation function: {agg_function}, using 'mean'")
        agg_function = 'mean'
    
    try:
        # Create aggregation dictionary
        agg_dict = {col: agg_func_map[agg_function] for col in available_metric_cols}
        
        # Perform aggregation
        aggregated = df.groupby(available_group_cols).agg(agg_dict).reset_index()
        
        # Add metadata columns if they exist
        metadata_cols = ['slot_start_date_time', 'bucket_start_time', 'bucket_midpoint', 'bucket_midpoint_numeric']
        for col in metadata_cols:
            if col in df.columns and col not in available_group_cols:
                # Take the first value for metadata columns
                metadata = df.groupby(available_group_cols)[col].first().reset_index()
                aggregated = aggregated.merge(metadata, on=available_group_cols, how='left')
        
        # Sort aggregated data to maintain logical ordering
        if 'slot' in aggregated.columns:
            aggregated = aggregated.sort_values('slot').reset_index(drop=True)
        elif 'bucket_number' in aggregated.columns:
            aggregated = aggregated.sort_values('bucket_number').reset_index(drop=True)
        elif 'gas_bucket' in aggregated.columns:
            aggregated = aggregated.sort_values('gas_bucket').reset_index(drop=True)
        elif 'slot_start_date_time' in aggregated.columns:
            aggregated = aggregated.sort_values('slot_start_date_time').reset_index(drop=True)
        
        logger.info(f"Aggregated data: {len(df)} -> {len(aggregated)} records using {agg_function}")
        return aggregated
        
    except Exception as e:
        logger.error(f"Error aggregating data: {e}")
        return df


def calculate_bucket_metrics(
    df: pd.DataFrame,
    group_cols: List[str] = None,
    metric_cols: List[str] = None,
    agg_function: str = 'mean'
) -> pd.DataFrame:
    """
    Calculate aggregated metrics for each time bucket.
    Updated to use the new flexible aggregation system.
    
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
    
    return aggregate_data(df, group_by, metric_cols, agg_function)


def calculate_consensus_performance_ranking(
    df: pd.DataFrame,
    performance_metric: str = 'block_gossip_time_mean',
    gas_metric: str = 'gas_used'
) -> pd.DataFrame:
    """
    Calculate performance ranking for consensus implementations.
    
    Args:
        df: DataFrame with consensus implementation data
        performance_metric: Metric to rank by (lower is better for timing)
        gas_metric: Gas usage metric for analysis
        
    Returns:
        DataFrame with consensus implementation rankings
    """
    if df.empty or 'consensus_implementations' not in df.columns:
        logger.warning("Cannot calculate consensus ranking: missing data")
        return pd.DataFrame()
    
    # Parse consensus implementations (they might be comma-separated)
    expanded_rows = []
    for _, row in df.iterrows():
        if pd.notna(row['consensus_implementations']):
            implementations = str(row['consensus_implementations']).split(',')
            for impl in implementations:
                impl = impl.strip()
                if impl:
                    new_row = row.copy()
                    new_row['consensus_implementation'] = impl
                    expanded_rows.append(new_row)
    
    if not expanded_rows:
        logger.warning("No consensus implementation data found")
        return pd.DataFrame()
    
    expanded_df = pd.DataFrame(expanded_rows)
    
    # Calculate metrics by consensus implementation
    metrics_by_impl = expanded_df.groupby('consensus_implementation').agg({
        performance_metric: ['mean', 'median', 'std', 'count'],
        gas_metric: ['mean', 'median', 'std'] if gas_metric in expanded_df.columns else ['count']
    }).reset_index()
    
    # Flatten column names
    metrics_by_impl.columns = ['_'.join(col).strip('_') if col[1] else col[0] 
                              for col in metrics_by_impl.columns]
    
    # Rank by performance (lower timing is better)
    perf_mean_col = f"{performance_metric}_mean"
    if perf_mean_col in metrics_by_impl.columns:
        metrics_by_impl['performance_rank'] = metrics_by_impl[perf_mean_col].rank(ascending=True)
    
    # Calculate performance score (normalized)
    if perf_mean_col in metrics_by_impl.columns:
        min_perf = metrics_by_impl[perf_mean_col].min()
        max_perf = metrics_by_impl[perf_mean_col].max()
        metrics_by_impl['performance_score'] = 100 * (max_perf - metrics_by_impl[perf_mean_col]) / (max_perf - min_perf)
    
    logger.info(f"Calculated consensus ranking for {len(metrics_by_impl)} implementations")
    return metrics_by_impl.sort_values('performance_rank' if 'performance_rank' in metrics_by_impl.columns else perf_mean_col)


def calculate_gas_binned_analysis(
    df: pd.DataFrame,
    gas_metric: str = 'gas_used',
    performance_metric: str = 'block_gossip_time_mean',
    bin_size: int = 5_000_000
) -> pd.DataFrame:
    """
    Calculate performance metrics across gas usage bins.
    
    Args:
        df: DataFrame with gas and performance data
        gas_metric: Gas usage column
        performance_metric: Performance timing column
        bin_size: Size of gas bins
        
    Returns:
        DataFrame with binned analysis results
    """
    if df.empty or gas_metric not in df.columns or performance_metric not in df.columns:
        logger.warning(f"Cannot calculate gas binned analysis: missing columns")
        return pd.DataFrame()
    
    # Remove rows with missing data
    clean_df = df[[gas_metric, performance_metric]].dropna()
    
    if len(clean_df) < 10:
        logger.warning("Insufficient data for gas binned analysis")
        return pd.DataFrame()
    
    # Create gas bins
    min_gas = clean_df[gas_metric].min()
    max_gas = clean_df[gas_metric].max()
    
    # Create bin edges
    bin_edges = list(range(int(min_gas), int(max_gas) + bin_size, bin_size))
    if bin_edges[-1] < max_gas:
        bin_edges.append(bin_edges[-1] + bin_size)
    
    # Assign bins
    clean_df = clean_df.copy()
    clean_df['gas_bin'] = pd.cut(clean_df[gas_metric], bins=bin_edges, include_lowest=True)
    
    # Calculate metrics per bin
    bin_metrics = clean_df.groupby('gas_bin').agg({
        performance_metric: ['mean', 'median', 'std', 'count'],
        gas_metric: ['mean', 'median']
    }).reset_index()
    
    # Flatten column names
    bin_metrics.columns = ['_'.join(col).strip('_') if col[1] else col[0] 
                          for col in bin_metrics.columns]
    
    # Add bin metadata - convert to numeric to avoid categorical arithmetic errors
    try:
        bin_metrics['gas_bin_start'] = bin_metrics['gas_bin'].apply(lambda x: float(x.left) if pd.notna(x) and hasattr(x, 'left') else np.nan)
        bin_metrics['gas_bin_end'] = bin_metrics['gas_bin'].apply(lambda x: float(x.right) if pd.notna(x) and hasattr(x, 'right') else np.nan)
        # Ensure numeric types before arithmetic
        bin_metrics['gas_bin_start'] = pd.to_numeric(bin_metrics['gas_bin_start'], errors='coerce')
        bin_metrics['gas_bin_end'] = pd.to_numeric(bin_metrics['gas_bin_end'], errors='coerce')
        bin_metrics['gas_bin_midpoint'] = (bin_metrics['gas_bin_start'] + bin_metrics['gas_bin_end']) / 2
    except Exception as e:
        logger.warning(f"Could not calculate bin midpoints: {e}")
        # Fallback: use bin labels as approximations
        bin_metrics['gas_bin_midpoint'] = range(len(bin_metrics))
    
    # Filter bins with sufficient data
    min_samples = get_analysis_config()['min_samples_per_bin']
    count_col = f"{performance_metric}_count"
    if count_col in bin_metrics.columns:
        bin_metrics = bin_metrics[bin_metrics[count_col] >= min_samples]
    
    logger.info(f"Calculated gas binned analysis for {len(bin_metrics)} bins")
    return bin_metrics


def calculate_temporal_trends(
    df: pd.DataFrame,
    time_col: str = 'bucket_midpoint_numeric',
    metric_cols: List[str] = None
) -> Dict[str, Dict[str, float]]:
    """
    Calculate temporal trends for metrics over time.
    
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
    
    # Use numeric time column if available, fallback to bucket_number
    if 'bucket_midpoint_numeric' in df.columns:
        time_col = 'bucket_midpoint_numeric'
    elif 'bucket_number' in df.columns:
        time_col = 'bucket_number'
    else:
        logger.warning("No suitable time column for trend analysis")
        return {}
    
    metric_cols = metric_cols or ['gas_used_mean', 'block_gossip_time_mean_mean', 'head_time_mean_mean']
    available_metrics = [col for col in metric_cols if col in df.columns]
    
    if not available_metrics:
        logger.warning("No metric columns available for trend analysis")
        return {}
    
    trends = {}
    
    # Use numeric time column directly
    df_clean = df[[time_col] + available_metrics].dropna()
    if len(df_clean) < 3:
        logger.warning("Insufficient data for trend analysis")
        return trends
    
    time_values = df_clean[time_col].astype(float)
    
    for metric in available_metrics:
        try:
            if not SCIPY_AVAILABLE:
                logger.warning(f"Cannot calculate trend for {metric}: scipy not available")
                trends[metric] = None
                continue
                
            slope, intercept, r_value, p_value, std_err = linregress(time_values, df_clean[metric])
            
            trends[metric] = {
                'slope': float(slope),
                'intercept': float(intercept),
                'r_squared': float(r_value ** 2),
                'p_value': float(p_value),
                'std_error': float(std_err),
                'trend_direction': 'increasing' if slope > 0 else 'decreasing',
                'significant': p_value < 0.05,
                'sample_size': len(df_clean)
            }
            
        except Exception as e:
            logger.error(f"Error calculating trend for {metric}: {e}")
            trends[metric] = None
    
    logger.info(f"Calculated temporal trends for {len(trends)} metrics")
    return trends


def calculate_percentile_analysis(
    df: pd.DataFrame,
    metric_cols: List[str] = None,
    percentiles: List[float] = None
) -> pd.DataFrame:
    """
    Calculate percentile analysis for key metrics.
    
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
    
    metric_cols = metric_cols or ['gas_used', 'block_gossip_time_mean', 'head_time_mean', 'gas_utilization']
    percentiles = percentiles or [0.05, 0.25, 0.5, 0.75, 0.95, 0.99]
    
    available_metrics = [col for col in metric_cols if col in df.columns]
    if not available_metrics:
        logger.warning("No metric columns available for percentile analysis")
        return pd.DataFrame()
    
    percentile_results = []
    
    for metric in available_metrics:
        metric_data = df[metric].dropna()
        if len(metric_data) == 0:
            continue
            
        metric_percentiles = {
            'metric': metric,
            'count': len(metric_data),
            'mean': float(metric_data.mean()),
            'std': float(metric_data.std())
        }
        
        for p in percentiles:
            metric_percentiles[f'p{int(p*100)}'] = float(metric_data.quantile(p))
        
        percentile_results.append(metric_percentiles)
    
    result_df = pd.DataFrame(percentile_results)
    logger.info(f"Calculated percentiles for {len(result_df)} metrics")
    return result_df


def calculate_comparative_analysis(
    period1_data: pd.DataFrame,
    period2_data: pd.DataFrame,
    metric_cols: List[str] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Calculate comparative analysis between two time periods.
    
    Args:
        period1_data: Data from first period
        period2_data: Data from second period  
        metric_cols: Metrics to compare
        
    Returns:
        Dictionary with comparative statistics
    """
    if period1_data.empty or period2_data.empty:
        logger.warning("Cannot perform comparative analysis: empty period data")
        return {}
    
    metric_cols = metric_cols or ['gas_used', 'block_gossip_time_mean', 'head_time_mean', 'gas_utilization']
    available_metrics = [col for col in metric_cols if col in period1_data.columns and col in period2_data.columns]
    
    if not available_metrics:
        logger.warning("No common metric columns for comparative analysis")
        return {}
    
    comparison_results = {}
    
    for metric in available_metrics:
        period1_values = period1_data[metric].dropna()
        period2_values = period2_data[metric].dropna()
        
        if len(period1_values) == 0 or len(period2_values) == 0:
            continue
        
        # Basic statistics
        p1_mean = float(period1_values.mean())
        p2_mean = float(period2_values.mean())
        
        # Statistical test (Mann-Whitney U test)
        try:
            statistic, p_value = stats.mannwhitneyu(period1_values, period2_values, alternative='two-sided')
            
            comparison_results[metric] = {
                'period1_mean': p1_mean,
                'period2_mean': p2_mean,
                'absolute_change': p2_mean - p1_mean,
                'percent_change': ((p2_mean - p1_mean) / p1_mean * 100) if p1_mean != 0 else 0,
                'period1_median': float(period1_values.median()),
                'period2_median': float(period2_values.median()),
                'period1_std': float(period1_values.std()),
                'period2_std': float(period2_values.std()),
                'period1_count': len(period1_values),
                'period2_count': len(period2_values),
                'test_statistic': float(statistic),
                'test_p_value': float(p_value),
                'significant_difference': p_value < 0.05
            }
            
        except Exception as e:
            logger.error(f"Error in comparative analysis for {metric}: {e}")
            comparison_results[metric] = None
    
    logger.info(f"Calculated comparative analysis for {len(comparison_results)} metrics")
    return comparison_results


def calculate_gas_vs_head_time_relationship(
    df: pd.DataFrame,
    gas_column: str = 'gas_used',
    head_time_column: str = 'head_time_mean',
    bin_size: Optional[int] = None
) -> Dict[str, Any]:
    """
    Calculate the relationship between gas used and head time.
    
    This function analyzes whether there's a linear relationship between 
    gas usage and head time (block processing/propagation time).
    
    Args:
        df: DataFrame with gas and head time data
        gas_column: Column name for gas usage
        head_time_column: Column name for head time
        bin_size: Optional gas bin size for binned analysis
        
    Returns:
        Dictionary containing:
        - correlation_analysis: Correlation statistics (r, p-value, etc.)
        - linear_regression: Linear regression results (slope, intercept, r-squared)
        - binned_analysis: Gas-binned average head times (if bin_size provided)
        - relationship_type: String describing the relationship
        - visualization_data: Data formatted for plotting
    """
    if df.empty or gas_column not in df.columns or head_time_column not in df.columns:
        logger.warning(f"Cannot calculate gas vs head time relationship: missing data or columns")
        return {}
    
    # Remove NaN values
    mask = df[[gas_column, head_time_column]].notna().all(axis=1)
    clean_df = df.loc[mask]
    
    if len(clean_df) < 10:
        logger.warning(f"Insufficient data for gas vs head time analysis: {len(clean_df)} samples")
        return {}
    
    result = {
        'sample_size': len(clean_df),
        'gas_range': {
            'min': float(clean_df[gas_column].min()),
            'max': float(clean_df[gas_column].max()),
            'mean': float(clean_df[gas_column].mean())
        },
        'head_time_range': {
            'min': float(clean_df[head_time_column].min()),
            'max': float(clean_df[head_time_column].max()),
            'mean': float(clean_df[head_time_column].mean())
        }
    }
    
    # Calculate correlation analysis
    correlation_data = calculate_correlation_analysis(clean_df, gas_column, head_time_column)
    if correlation_data:
        result['correlation_analysis'] = correlation_data
        
        # Determine relationship type based on correlation and p-value
        r_value = correlation_data['correlation']
        p_value = correlation_data['p_value']
        
        if p_value >= 0.05:
            result['relationship_type'] = 'no_significant_relationship'
            result['relationship_description'] = 'No statistically significant relationship'
        elif abs(r_value) < 0.3:
            result['relationship_type'] = 'weak'
            result['relationship_description'] = f'Weak {"positive" if r_value > 0 else "negative"} relationship'
        elif abs(r_value) < 0.7:
            result['relationship_type'] = 'moderate'
            result['relationship_description'] = f'Moderate {"positive" if r_value > 0 else "negative"} relationship'
        else:
            result['relationship_type'] = 'strong'
            result['relationship_description'] = f'Strong {"positive" if r_value > 0 else "negative"} relationship'
        
        # Add linearity assessment
        result['is_linear'] = abs(r_value) > 0.7 and p_value < 0.05
        result['linearity_confidence'] = 1 - p_value if p_value < 0.05 else 0
    
    # Perform binned analysis if requested
    if bin_size:
        try:
            # Create gas bins
            min_gas = clean_df[gas_column].min()
            max_gas = clean_df[gas_column].max()
            
            # Create bin edges
            bin_edges = list(range(int(min_gas), int(max_gas) + bin_size, bin_size))
            if bin_edges[-1] < max_gas:
                bin_edges.append(bin_edges[-1] + bin_size)
            
            # Assign bins
            clean_df = clean_df.copy()
            clean_df['gas_bin'] = pd.cut(clean_df[gas_column], bins=bin_edges, include_lowest=True)
            
            # Calculate metrics per bin
            bin_metrics = clean_df.groupby('gas_bin').agg({
                head_time_column: ['mean', 'median', 'std', 'count'],
                gas_column: ['mean', 'median']
            }).reset_index()
            
            # Flatten column names
            bin_metrics.columns = ['_'.join(col).strip('_') if col[1] else col[0] 
                                  for col in bin_metrics.columns]
            
            # Add bin metadata
            bin_metrics['gas_bin_start'] = bin_metrics['gas_bin'].apply(lambda x: float(x.left))
            bin_metrics['gas_bin_end'] = bin_metrics['gas_bin'].apply(lambda x: float(x.right))
            bin_metrics['gas_bin_midpoint'] = (bin_metrics['gas_bin_start'] + bin_metrics['gas_bin_end']) / 2
            
            # Filter bins with sufficient data
            min_samples = 5
            bin_metrics = bin_metrics[bin_metrics[f"{head_time_column}_count"] >= min_samples]
            
            result['binned_analysis'] = {
                'bin_size': bin_size,
                'num_bins': len(bin_metrics),
                'bin_data': bin_metrics.to_dict('records')
            }
            
            # Calculate trend across bins
            if len(bin_metrics) >= 3:
                bin_correlation = calculate_correlation_analysis(
                    bin_metrics, 
                    'gas_bin_midpoint', 
                    f"{head_time_column}_mean"
                )
                if bin_correlation:
                    result['binned_correlation'] = bin_correlation
                    result['binned_trend_description'] = (
                        f"Binned analysis shows {'positive' if bin_correlation['slope'] > 0 else 'negative'} "
                        f"trend with R² = {bin_correlation['r_squared']:.3f}"
                    )
        
        except Exception as e:
            logger.error(f"Error in binned analysis: {e}")
    
    # Prepare visualization data
    result['visualization_data'] = {
        'scatter_data': clean_df[[gas_column, head_time_column]].to_dict('records'),
        'x_column': gas_column,
        'y_column': head_time_column,
        'x_label': 'Gas Used',
        'y_label': 'Head Time (ms)',
        'title': 'Gas Usage vs Head Time Relationship'
    }
    
    # Add trend line data if correlation exists
    if 'correlation_analysis' in result and result['correlation_analysis']:
        slope = result['correlation_analysis']['slope']
        intercept = result['correlation_analysis']['intercept']
        
        # Generate trend line points
        x_min, x_max = clean_df[gas_column].min(), clean_df[gas_column].max()
        x_trend = np.linspace(x_min, x_max, 100)
        y_trend = slope * x_trend + intercept
        
        result['visualization_data']['trend_line'] = {
            'x': x_trend.tolist(),
            'y': y_trend.tolist(),
            'equation': f"y = {slope:.2e}x + {intercept:.2f}",
            'r_squared': result['correlation_analysis']['r_squared']
        }
    
    logger.info(f"Calculated gas vs head time relationship: {result.get('relationship_description', 'Unknown')}")
    return result


