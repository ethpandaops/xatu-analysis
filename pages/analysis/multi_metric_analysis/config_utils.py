"""
Configuration utilities for gas usage performance analysis.

This module provides metric definitions, validation functions, and analysis 
parameters for the gas usage vs performance dashboard.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from shared.config import get_supported_networks, get_network_config


def get_analysis_config() -> Dict[str, Any]:
    """
    Get default configuration parameters for gas performance analysis.
    
    Returns:
        Dictionary containing analysis configuration parameters
    """
    return {
        "default_time_buckets": 30,
        "max_time_buckets": 50,
        "min_time_buckets": 10,
        "max_propagation_time_ms": 12000,
        "default_gas_bin_size": 5_000_000,
        "min_samples_per_bin": 5,
        "min_samples_per_analysis": 100,
        "supported_networks": get_supported_networks(),
        "visualization_themes": ["viridis", "plasma", "inferno", "turbo"],
        "default_theme": "viridis",
        "cache_ttl_hours": 1,
        "max_query_timeout_seconds": 300,
        # Performance optimization settings
        "default_chunk_days": 7,
        "max_days_per_chunk": 21,
        "large_dataset_threshold": 50_000,
        "enable_polars_optimization": True,
        "memory_efficient_mode": True,
        "max_visualization_points": 100_000,
        "enable_data_sampling": True,
        "sampling_strategy": "stratified",
        # Data size warning thresholds
        "medium_dataset_threshold": 100_000,
        "large_dataset_threshold_records": 500_000,
        "huge_dataset_threshold": 1_000_000
    }


def get_consensus_implementations() -> List[str]:
    """
    Get list of supported consensus layer implementations.
    
    Returns:
        List of consensus implementation names
    """
    return [
        "lighthouse",
        "prysm", 
        "teku",
        "nimbus",
        "lodestar",
        "grandine"
    ]


def get_continents() -> Dict[str, str]:
    """
    Get mapping of continent codes to human-readable names.
    
    Returns:
        Dictionary mapping continent codes to names
    """
    return {
        "AF": "Africa",
        "AS": "Asia", 
        "EU": "Europe",
        "NA": "North America",
        "OC": "Oceania",
        "SA": "South America",
        "AN": "Antarctica"
    }


def get_default_periods() -> Dict[str, Dict[str, datetime]]:
    """
    Get predefined analysis periods for quick selection.
    
    Returns:
        Dictionary of period names to start/end datetime mappings
    """
    now = datetime.now()
    return {
        "Last 24 Hours": {
            "start": now - timedelta(hours=24),
            "end": now
        },
        "Last 7 Days": {
            "start": now - timedelta(days=7),
            "end": now
        },
        "Last 14 Days": {
            "start": now - timedelta(days=14),
            "end": now
        },
        "Last 30 Days": {
            "start": now - timedelta(days=30),
            "end": now
        },
        "Previous Week": {
            "start": now - timedelta(days=14),
            "end": now - timedelta(days=7)
        },
        "Two Weeks Ago": {
            "start": now - timedelta(days=21),
            "end": now - timedelta(days=14)
        }
    }


def validate_analysis_config(
    network: str,
    start_date: datetime,
    end_date: datetime,
    time_buckets: int
) -> List[str]:
    """
    Validate analysis configuration parameters.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        time_buckets: Number of time buckets
        
    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    config = get_analysis_config()
    
    # Validate network
    if network not in config["supported_networks"]:
        errors.append(f"Unsupported network: {network}. Must be one of {config['supported_networks']}")
    
    # Validate date range
    if start_date >= end_date:
        errors.append("Start date must be before end date")
        
    date_range = end_date - start_date
    # No maximum date range limit - let user request as much data as needed
    # If they request too much data, the system will error out naturally
        
    if date_range.total_seconds() < 3600:
        errors.append("Date range must be at least 1 hour")
    
    # Validate time buckets
    if time_buckets < config["min_time_buckets"] or time_buckets > config["max_time_buckets"]:
        errors.append(f"Time buckets must be between {config['min_time_buckets']} and {config['max_time_buckets']}")
    
    return errors


def get_aggregation_functions() -> Dict[str, str]:
    """
    Get supported aggregation functions for metrics.
    
    Returns:
        Dictionary mapping function names to descriptions
    """
    return {
        "mean": "Average",
        "median": "Median (p50)",
        "p90": "p90",
        "p95": "p95",
        "p99": "p99", 
        "min": "Minimum",
        "max": "Maximum",
        "std": "Standard deviation",
        "count": "Count of observations"
    }


def get_visualization_types() -> Dict[str, Dict[str, str]]:
    """
    Get available visualization types with descriptions.
    
    Returns:
        Dictionary of visualization types with metadata
    """
    return {
        "scatter": {
            "title": "Scatter Plot",
            "description": "Gas usage vs arrival time with trend line",
            "icon": "📊"
        },
        "time_series": {
            "title": "Time Series",
            "description": "Metrics over time buckets",
            "icon": "📈"
        },
        "heatmap": {
            "title": "Heatmap",
            "description": "Gas utilization by time and consensus implementation",
            "icon": "🔥"
        },
        "box_plot": {
            "title": "Box Plot",
            "description": "Distribution comparison across consensus implementations",
            "icon": "📦"
        },
        "correlation_matrix": {
            "title": "Correlation Matrix",
            "description": "Correlation coefficients between metrics",
            "icon": "🔗"
        },
        "geographic": {
            "title": "Geographic Analysis",
            "description": "Performance by continent",
            "icon": "🌍"
        }
    }


def get_query_templates() -> Dict[str, str]:
    """
    Get SQL query templates for different data sources.
    
    Returns:
        Dictionary of query template names to SQL strings
    """
    return {
        "block_gossip": """
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
        """,
        
        "canonical_blocks": """
            SELECT
                slot,
                slot_start_date_time,
                epoch,
                proposer_index,
                execution_payload_gas_used as gas_used,
                execution_payload_gas_limit as gas_limit,
                execution_payload_blob_gas_used as blob_gas_used,
                execution_payload_excess_blob_gas as excess_blob_gas
            FROM canonical_beacon_block FINAL
            WHERE meta_network_name = %(network)s
                AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
                AND execution_payload_gas_used IS NOT NULL
        """
    }