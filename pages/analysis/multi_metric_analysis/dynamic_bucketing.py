"""
Dynamic bucketing system for any numeric metric.
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def create_dynamic_buckets(
    df: pd.DataFrame, 
    metric_column: str, 
    bucket_size: float,
    bucket_column_name: str = 'x_bucket'
) -> pd.DataFrame:
    """
    Create buckets for any numeric metric.
    
    Args:
        df: DataFrame containing the data
        metric_column: Name of the column to bucket
        bucket_size: Size of each bucket
        bucket_column_name: Name for the bucket column
        
    Returns:
        DataFrame with added bucket columns
    """
    if metric_column not in df.columns:
        logger.warning(f"Column {metric_column} not found in DataFrame")
        return df
        
    if df[metric_column].isna().all():
        logger.warning(f"Column {metric_column} contains only null values")
        return df
        
    try:
        # Create a copy to avoid modifying the original
        result_df = df.copy()
        
        # Get min and max values
        min_val = df[metric_column].min()
        max_val = df[metric_column].max()
        
        if pd.isna(min_val) or pd.isna(max_val):
            logger.warning(f"Could not determine range for {metric_column}")
            return df
            
        # Create bucket edges
        num_buckets = int(np.ceil((max_val - min_val) / bucket_size)) + 1
        bucket_edges = [min_val + i * bucket_size for i in range(num_buckets)]
        
        # Assign buckets
        result_df[bucket_column_name] = pd.cut(
            df[metric_column],
            bins=bucket_edges,
            labels=range(len(bucket_edges) - 1),
            include_lowest=True
        )
        
        # Convert to numeric
        result_df[bucket_column_name] = pd.to_numeric(result_df[bucket_column_name], errors='coerce')
        
        # Add bucket range information
        result_df[f'{bucket_column_name}_start'] = result_df[bucket_column_name] * bucket_size + min_val
        result_df[f'{bucket_column_name}_end'] = result_df[f'{bucket_column_name}_start'] + bucket_size
        
        # Add bucket midpoint for plotting
        result_df[f'{bucket_column_name}_midpoint'] = (result_df[f'{bucket_column_name}_start'] + result_df[f'{bucket_column_name}_end']) / 2
        
        # Create human-readable labels
        result_df[f'{bucket_column_name}_label'] = result_df.apply(
            lambda row: f"{row[f'{bucket_column_name}_start']:.0f}-{row[f'{bucket_column_name}_end']:.0f}"
            if pd.notna(row[bucket_column_name]) else "Unknown",
            axis=1
        )
        
        logger.info(f"Created {num_buckets} buckets for {metric_column} with size {bucket_size}")
        
        return result_df
        
    except Exception as e:
        logger.error(f"Error creating buckets for {metric_column}: {e}")
        return df