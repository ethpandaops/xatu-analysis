"""
Metrics calculation utilities for gas usage performance analysis.

This module provides statistical analysis functions including time bucketing,
correlation analysis, trend calculations, and consensus implementation ranking
using Polars for optimal performance.
"""

import polars as pl
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from shared.data_utils import memory_efficient_context, create_time_buckets as shared_create_time_buckets, create_numeric_buckets
from shared.metric_utils import (
    calculate_correlation_analysis as shared_calculate_correlation_analysis,
    calculate_temporal_trends as shared_calculate_temporal_trends,
    calculate_percentile_analysis as shared_calculate_percentile_analysis
)
from config_utils import get_analysis_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_time_buckets(df: pd.DataFrame, num_buckets: int = 30) -> pd.DataFrame:
    """
    Create time buckets using Polars for optimal performance.
    
    Args:
        df: DataFrame with slot_start_date_time column
        num_buckets: Number of time buckets to create
        
    Returns:
        DataFrame with added time bucket columns
    """
    # Use the shared implementation
    return shared_create_time_buckets(df, num_buckets, time_col='slot_start_date_time')


def create_gas_buckets(df: pd.DataFrame, bucket_size: int = 2_000_000, gas_column: str = 'gas_used') -> pd.DataFrame:
    """
    Create gas usage buckets using Polars for optimal performance.
    
    Args:
        df: DataFrame with gas usage data
        bucket_size: Size of each gas bucket (default: 2M gas)
        gas_column: Column name containing gas usage values
        
    Returns:
        DataFrame with added gas bucket columns
    """
    # Use the shared implementation with 'gas' prefix
    return create_numeric_buckets(df, bucket_size, gas_column, bucket_prefix='gas')


def aggregate_data(df: pd.DataFrame, group_by: List[str] = None, metrics: List[str] = None, agg_function: str = 'mean') -> pd.DataFrame:
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
            elif agg_function == 'p90':
                agg_expressions.append(pl.col(col).quantile(0.90).alias(col))
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


def calculate_bucket_metrics(
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
    
    return aggregate_data(df, group_by, metric_cols, agg_function)


def calculate_correlation_analysis(
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
    # Use the shared implementation
    return shared_calculate_correlation_analysis(df, x_col, y_col, method)


def calculate_temporal_trends(
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
    # Use the shared implementation
    return shared_calculate_temporal_trends(df, time_col, metric_cols)


def calculate_percentile_analysis(
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
    # Use the shared implementation
    return shared_calculate_percentile_analysis(df, metric_cols, percentiles)


def prepare_large_dataset(df: pd.DataFrame, max_rows: int = 100_000, strategy: str = 'stratified') -> pd.DataFrame:
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


def calculate_consensus_performance_ranking(
    df: pd.DataFrame,
    performance_metric: str = 'block_gossip_time',
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
    performance_metric: str = 'block_gossip_time',
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
    
    metric_cols = metric_cols or ['gas_used', 'block_gossip_time', 'head_time', 'gas_utilization']
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
            # Import scipy here to handle the statistical test
            from scipy import stats
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
            
        except ImportError:
            # If scipy not available, provide basic comparison without statistical test
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
                'test_statistic': None,
                'test_p_value': None,
                'significant_difference': None
            }
            logger.warning(f"Statistical test skipped for {metric}: scipy not available")
            
        except Exception as e:
            logger.error(f"Error in comparative analysis for {metric}: {e}")
            comparison_results[metric] = None
    
    logger.info(f"Calculated comparative analysis for {len(comparison_results)} metrics")
    return comparison_results