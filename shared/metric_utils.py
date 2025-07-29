"""
Metric utilities for analysis dashboards.

This module provides metric metadata and information for various Ethereum metrics
used across different analysis dashboards, as well as statistical analysis functions.
"""

import pandas as pd
import polars as pl
import numpy as np
from typing import Dict, Any, List, Optional
import logging
from contextlib import contextmanager

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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import memory_efficient_context from data_utils
import gc

@contextmanager
def memory_efficient_context():
    """Context manager for memory-efficient operations."""
    try:
        yield
    finally:
        gc.collect()


def get_metric_info(metric_name: str) -> Dict[str, str]:
    """
    Get human-readable information for metrics used in analysis.
    
    Args:
        metric_name: The internal metric name (may include aggregation suffix like _mean, _p95)
        
    Returns:
        Dictionary containing title, subtitle, unit, and format information
    """
    metric_info = {
        "block_gossip_time": {
            "title": "Block Gossip Time",
            "subtitle": "Time for block gossip event to propagate from slot start to client reception",
            "unit": "ms",
            "format": ".2f"
        },
        "head_time": {
            "title": "Head Time", 
            "subtitle": "Maximum propagation time across head, block, and blob events to reach client",
            "unit": "ms",
            "format": ".2f"
        },
        "gas_used": {
            "title": "Gas Used",
            "subtitle": "Total gas consumed in execution payload",
            "unit": "gas",
            "format": ".2e"
        },
        "gas_limit": {
            "title": "Gas Limit",
            "subtitle": "Maximum gas allowed in execution payload",
            "unit": "gas",
            "format": ".2e"
        },
        "gas_utilization": {
            "title": "Gas Utilization",
            "subtitle": "Percentage of gas limit utilized (gas_used / gas_limit * 100)",
            "unit": "%",
            "format": ".1f"
        },
        "time_difference": {
            "title": "Head vs Gossip Time Difference",
            "subtitle": "Difference between head time and block gossip time",
            "unit": "ms", 
            "format": ".2f"
        },
        "blob_count": {
            "title": "Blob Count",
            "subtitle": "Number of blob sidecars associated with the block",
            "unit": "blobs",
            "format": ".0f"
        },
        "proposer_index": {
            "title": "Proposer Index",
            "subtitle": "Validator index of the block proposer",
            "unit": "",
            "format": ".0f"
        },
        "slot": {
            "title": "Slot",
            "subtitle": "Beacon chain slot number",
            "unit": "",
            "format": ".0f"
        },
        "epoch": {
            "title": "Epoch",
            "subtitle": "Beacon chain epoch number",
            "unit": "",
            "format": ".0f"
        },
        "meta_consensus_implementation": {
            "title": "Consensus Implementation",
            "subtitle": "Beacon chain client software implementation",
            "unit": "",
            "format": "s"
        },
        "meta_client_name": {
            "title": "Client Name",
            "subtitle": "Individual client instance identifier",
            "unit": "",
            "format": "s"
        },
        "meta_client_geo_continent_code": {
            "title": "Continent",
            "subtitle": "Geographic continent of the client location",
            "unit": "",
            "format": "s"
        }
    }
    
    # Handle aggregated metrics (e.g., block_gossip_time_mean, gas_used_p95)
    base_metric = metric_name
    agg_suffix = ""
    agg_description = ""
    
    # Check for aggregation suffixes
    for suffix in ['_mean', '_median', '_p90', '_p95', '_p99', '_min', '_max', '_std', '_count']:
        if metric_name.endswith(suffix):
            base_metric = metric_name.replace(suffix, '')
            agg_suffix = suffix[1:]  # Remove the underscore
            
            # Map aggregation functions to descriptions
            agg_descriptions = {
                'mean': 'average',
                'median': 'median (p50)',
                'p90': 'p90',
                'p95': 'p95',
                'p99': 'p99',
                'min': 'minimum',
                'max': 'maximum',
                'std': 'standard deviation',
                'count': 'count'
            }
            agg_description = agg_descriptions.get(agg_suffix, agg_suffix)
            break
    
    # Get base metric info
    info = metric_info.get(base_metric, {
        "title": base_metric.replace('_', ' ').title(),
        "subtitle": "No description available",
        "unit": "",
        "format": ".2f"
    }).copy()
    
    # Modify title and subtitle for aggregated metrics
    if agg_suffix:
        info["title"] = info['title']  # Keep original title without aggregation description
        info["subtitle"] = f"{agg_description.title()} of {info['subtitle'].lower()}"
        info["agg_function"] = agg_suffix
        info["base_metric"] = base_metric
    else:
        info["agg_function"] = None
        info["base_metric"] = metric_name
    
    return info


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