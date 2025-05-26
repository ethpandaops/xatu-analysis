"""
Data processing utilities for analysis
"""
import pandas as pd


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
