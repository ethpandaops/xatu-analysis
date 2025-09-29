"""
Configuration utilities for Blob Mempool Analysis.

This module provides configuration options, validation, and utility functions
for the blob mempool analysis dashboard.
"""

from typing import Dict, Any, List
from datetime import timedelta

def get_analysis_config() -> Dict[str, Any]:
    """
    Get default configuration for blob mempool analysis.
    
    Returns:
        Dictionary with default analysis parameters
    """
    return {
        "default_time_range": timedelta(hours=6),
        "max_time_range": timedelta(days=7),
        "min_time_range": timedelta(minutes=30),
        "default_mempool_lookback": 24,  # seconds before slot start
        "max_slots_per_query": 10000,
        "cache_ttl": 300,  # 5 minutes
        "supported_networks": ["mainnet", "holesky", "sepolia"],
        "blob_transaction_type": 3,  # EIP-4844 blob transaction type
    }

def get_visualization_options() -> Dict[str, Dict[str, Any]]:
    """
    Get available visualization options for blob mempool analysis.
    
    Returns:
        Dictionary of chart types and their configurations
    """
    return {
        "line_chart": {
            "name": "Line Chart",
            "description": "Time series view of blob counts and mempool presence",
            "x_axis": "Slot",
            "y_axis": "Blob Count",
            "suitable_for": ["timeline", "trends", "comparison"]
        },
        "bar_chart": {
            "name": "Bar Chart", 
            "description": "Comparison of blob counts across slots",
            "x_axis": "Slot",
            "y_axis": "Blob Count",
            "suitable_for": ["discrete_comparison", "categorical"]
        },
        "percentage_chart": {
            "name": "Percentage Chart",
            "description": "Mempool inclusion rates as percentages",
            "x_axis": "Slot",
            "y_axis": "Match Percentage (%)",
            "suitable_for": ["rates", "efficiency_metrics"]
        },
        "scatter_plot": {
            "name": "Scatter Plot",
            "description": "Correlation between canonical blobs and mempool blobs",
            "x_axis": "Canonical Blob Count",
            "y_axis": "Mempool Blob Count",
            "suitable_for": ["correlation", "relationship_analysis"]
        },
        "heatmap": {
            "name": "Heatmap",
            "description": "Hourly blob inclusion patterns by client",
            "x_axis": "Time (Hours)",
            "y_axis": "Client",
            "suitable_for": ["patterns", "client_comparison"]
        }
    }

def get_aggregation_options() -> Dict[str, str]:
    """
    Get available aggregation options for time-based grouping.
    
    Returns:
        Dictionary mapping aggregation keys to display names
    """
    return {
        "slot": "Per Slot",
        "minute": "Per Minute", 
        "5min": "Per 5 Minutes",
        "15min": "Per 15 Minutes",
        "hour": "Per Hour",
        "day": "Per Day"
    }

def get_metric_options() -> Dict[str, Dict[str, str]]:
    """
    Get available metrics for analysis.
    
    Returns:
        Dictionary of metric configurations
    """
    return {
        "blob_count": {
            "name": "Blob Count",
            "description": "Number of blobs per slot",
            "unit": "blobs",
            "aggregations": ["sum", "avg", "max", "min"]
        },
        "match_percentage": {
            "name": "Mempool Match Rate",
            "description": "Percentage of canonical blobs found in mempool",
            "unit": "%",
            "aggregations": ["avg", "median", "p90", "p95"]
        },
        "mempool_tx_count": {
            "name": "Mempool Transaction Count",
            "description": "Number of blob transactions in mempool",
            "unit": "transactions",
            "aggregations": ["sum", "avg", "max", "min"]
        },
        "inclusion_efficiency": {
            "name": "Inclusion Efficiency",
            "description": "Ratio of included blobs to mempool blobs",
            "unit": "ratio",
            "aggregations": ["avg", "median", "p90", "p95"]
        }
    }

def get_client_filter_options() -> Dict[str, Any]:
    """
    Get client filtering options and defaults.
    
    Returns:
        Dictionary with client filter configurations
    """
    return {
        "allow_multiple": True,
        "default_selection": "all",
        "min_clients": 1,
        "max_clients": 20,
        "sort_by": "name",
        "exclude_empty": True
    }

def get_time_range_presets() -> Dict[str, Dict[str, Any]]:
    """
    Get predefined time range presets for quick selection.
    
    Returns:
        Dictionary of time range preset configurations
    """
    return {
        "last_hour": {
            "name": "Last Hour",
            "duration": timedelta(hours=1),
            "description": "Most recent hour of data"
        },
        "last_6_hours": {
            "name": "Last 6 Hours", 
            "duration": timedelta(hours=6),
            "description": "Last 6 hours (default)"
        },
        "last_24_hours": {
            "name": "Last 24 Hours",
            "duration": timedelta(hours=24),
            "description": "Full day of blob activity"
        },
        "last_3_days": {
            "name": "Last 3 Days",
            "duration": timedelta(days=3),
            "description": "3 days for pattern analysis"
        },
        "last_week": {
            "name": "Last Week",
            "duration": timedelta(days=7),
            "description": "Weekly blob trends"
        }
    }

def get_validation_rules() -> Dict[str, Any]:
    """
    Get validation rules for user inputs.
    
    Returns:
        Dictionary with validation configurations
    """
    return {
        "time_range": {
            "min_duration": timedelta(minutes=30),
            "max_duration": timedelta(days=7),
            "max_slots": 10000
        },
        "clients": {
            "min_selection": 1,
            "max_selection": 20,
            "required_fields": ["meta_client_name"]
        },
        "slots": {
            "min_slot": 0,
            "max_slot": 999999999,  # Reasonable upper bound
            "slot_increment": 1
        }
    }

def get_default_chart_config() -> Dict[str, Any]:
    """
    Get default chart configuration settings.
    
    Returns:
        Dictionary with default chart settings
    """
    return {
        "height": 400,
        "width": "100%",
        "responsive": True,
        "show_legend": True,
        "show_grid": True,
        "color_scheme": "viridis",
        "line_width": 2,
        "marker_size": 6,
        "opacity": 0.8,
        "animation": True,
        "download_enabled": True
    }

def get_performance_settings() -> Dict[str, Any]:
    """
    Get performance optimization settings.
    
    Returns:
        Dictionary with performance configurations
    """
    return {
        "query_timeout": 60,  # seconds
        "max_data_points": 5000,
        "chunked_loading": True,
        "chunk_size": 1000,
        "parallel_queries": True,
        "cache_enabled": True,
        "lazy_loading": True
    }

def validate_analysis_params(params: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Validate analysis parameters against configuration rules.
    
    Args:
        params: Dictionary of parameters to validate
        
    Returns:
        Dictionary with validation errors (empty if valid)
    """
    errors = {}
    rules = get_validation_rules()
    
    # Validate time range
    if 'start_date' in params and 'end_date' in params:
        duration = params['end_date'] - params['start_date']
        if duration < rules['time_range']['min_duration']:
            errors['time_range'] = [f"Time range too short (minimum: {rules['time_range']['min_duration']})"]
        elif duration > rules['time_range']['max_duration']:
            errors['time_range'] = [f"Time range too long (maximum: {rules['time_range']['max_duration']})"]
    
    # Validate client selection
    if 'selected_clients' in params:
        clients = params['selected_clients']
        if len(clients) < rules['clients']['min_selection']:
            errors['clients'] = [f"Must select at least {rules['clients']['min_selection']} client(s)"]
        elif len(clients) > rules['clients']['max_selection']:
            errors['clients'] = [f"Cannot select more than {rules['clients']['max_selection']} clients"]
    
    return errors

