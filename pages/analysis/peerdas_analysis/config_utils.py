"""
Configuration utilities for PeerDAS analysis.

This module provides metric definitions, validation functions, and analysis 
parameters for the PeerDAS data availability dashboard.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from shared.config import get_supported_networks, get_network_config


def get_analysis_config() -> Dict[str, Any]:
    """
    Get default configuration parameters for PeerDAS analysis.
    
    Returns:
        Dictionary containing analysis configuration parameters
    """
    return {
        "default_time_buckets": 30,
        "max_time_buckets": 50,
        "min_time_buckets": 10,
        "max_propagation_time_ms": 12000,
        "min_samples_per_analysis": 100,
        "supported_networks": get_supported_networks(),
        "cache_ttl_hours": 1,
        "max_query_timeout_seconds": 300,
        # Performance optimization settings
        "default_chunk_days": 1,
        "max_days_per_chunk": 7,
        "large_dataset_threshold": 50_000,
        "enable_polars_optimization": True,
        "memory_efficient_mode": True,
        "max_visualization_points": 100_000,
        # PeerDAS specific
        "max_columns": 128,
        "default_custody_filter": 128,  # Show all by default
        "min_custody_count": 4,  # Minimum columns for non-validating nodes
    }


def get_data_source_options() -> Dict[str, Dict[str, Any]]:
    """
    Get available PeerDAS data source options.
    
    Returns:
        Dictionary of data source configurations
    """
    return {
        "beacon_api": {
            "name": "Beacon Node API Events",
            "block_table": "beacon_api_eth_v1_events_block",
            "sidecar_table": "beacon_api_eth_v1_events_data_column_sidecar", 
            "description": "Data column sidecars captured via beacon node API events",
            "use_case": "Node-specific column processing, API timing analysis"
        },
        "libp2p": {
            "name": "P2P Gossip Network",
            "block_table": "libp2p_gossipsub_beacon_block",
            "sidecar_table": "libp2p_gossipsub_data_column_sidecar",
            "description": "Data column sidecars from P2P gossip network",
            "use_case": "Network-wide propagation analysis, gossip timing"
        }
    }


def get_default_time_ranges() -> Dict[str, timedelta]:
    """
    Get default time range options.
    
    Returns:
        Dictionary of time range labels to timedelta values
    """
    return {
        "Last 1 Hour": timedelta(hours=1),
        "Last 6 Hours": timedelta(hours=6), 
        "Last 24 Hours": timedelta(hours=24),
        "Last 3 Days": timedelta(days=3),
        "Last Week": timedelta(days=7)
    }


def get_aggregation_options() -> Dict[str, str]:
    """
    Get supported aggregation functions for PeerDAS metrics.
    
    Returns:
        Dictionary mapping function names to descriptions
    """
    return {
        "p50": "Median (p50)",
        "p90": "90th Percentile",
        "p95": "95th Percentile",
        "p99": "99th Percentile",
        "mean": "Average",
        "max": "Maximum"
    }


def get_blob_count_bins() -> List[int]:
    """
    Get blob count bins for aggregation.
    
    Returns:
        List of blob count values for binning
    """
    return [0, 1, 2, 3, 4, 5, 6]  # 0-6 blobs per slot


def validate_analysis_config(
    network: str,
    start_date: datetime,
    end_date: datetime
) -> List[str]:
    """
    Validate analysis configuration parameters.
    
    Args:
        network: Network name
        start_date: Analysis start date
        end_date: Analysis end date
        
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
        
    if date_range.total_seconds() < 3600:
        errors.append("Date range must be at least 1 hour")
    
    return errors


def get_query_templates() -> Dict[str, str]:
    """
    Get SQL query templates for PeerDAS data sources.
    
    Returns:
        Dictionary of query template names to SQL strings
    """
    return {
        "discover_columns": """
            SELECT *
            FROM {sidecar_table} FINAL
            WHERE meta_network_name = %(network)s
            LIMIT 1
        """,
        
        "client_names": """
            SELECT DISTINCT
                meta_client_name,
                COUNT(*) as sample_count
            FROM {sidecar_table} FINAL
            WHERE meta_network_name = %(network)s
                AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
                AND meta_client_name != '' 
                AND meta_client_name IS NOT NULL
            GROUP BY meta_client_name
            HAVING sample_count > 10
            ORDER BY sample_count DESC
        """,
        
        "custody_counts": """
            SELECT
                meta_client_name,
                column_index,
                COUNT(*) as column_count
            FROM {sidecar_table} FINAL
            WHERE meta_network_name = %(network)s
                AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
                AND meta_client_name IN %(client_names)s
            GROUP BY meta_client_name, column_index
        """,
        
        "block_data": """
            SELECT
                slot,
                slot_start_date_time,
                meta_client_name,
                propagation_slot_start_diff as block_recv_time
            FROM {block_table} FINAL
            WHERE meta_network_name = %(network)s
                AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
                AND meta_client_name IN %(client_names)s
                AND propagation_slot_start_diff < %(max_propagation)s
        """,
        
        "sidecar_data": """
            SELECT
                slot,
                slot_start_date_time,
                meta_client_name,
                column_index,
                propagation_slot_start_diff as column_recv_time,
                0 as blob_count
            FROM {sidecar_table} FINAL
            WHERE meta_network_name = %(network)s
                AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
                AND meta_client_name IN %(client_names)s
                AND propagation_slot_start_diff < %(max_propagation)s
        """,
        
        "data_with_blobs_libp2p": """
            SELECT
                slot,
                slot_start_date_time,
                meta_client_name,
                column_index,
                propagation_slot_start_diff as column_recv_time,
                kzg_commitments_count as blob_count
            FROM libp2p_gossipsub_data_column_sidecar FINAL
            WHERE meta_network_name = %(network)s
                AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
                AND meta_client_name IN %(client_names)s
                AND propagation_slot_start_diff < %(max_propagation)s
        """,
        
        "data_with_blobs_beacon": """
            SELECT
                slot,
                slot_start_date_time,
                meta_client_name,
                column_index,
                propagation_slot_start_diff as column_recv_time,
                arrayLength(kzg_commitments) as blob_count
            FROM beacon_api_eth_v1_events_data_column_sidecar FINAL
            WHERE meta_network_name = %(network)s
                AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
                AND meta_client_name IN %(client_names)s
                AND propagation_slot_start_diff < %(max_propagation)s
        """
    }