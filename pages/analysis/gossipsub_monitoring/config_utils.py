"""
Configuration utilities for Gossipsub Monitoring.
"""

from datetime import timedelta
from typing import Dict, Any


def get_default_time_ranges() -> Dict[str, timedelta]:
    """Get default time range options."""
    return {
        "Last 1 Hour": timedelta(hours=1),
        "Last 6 Hours": timedelta(hours=6),
        "Last 12 Hours": timedelta(hours=12),
        "Last 24 Hours": timedelta(hours=24),
        "Last 3 Days": timedelta(days=3),
        "Last 7 Days": timedelta(days=7),
    }


def get_supported_networks() -> list:
    """Get list of supported networks."""
    return ["mainnet", "holesky", "sepolia"]


def get_data_source_options() -> Dict[str, Dict[str, Any]]:
    """Get available data source options for gossipsub analysis."""
    return {
        "libp2p": {
            "name": "P2P Gossip Network",
            "description": "Direct P2P network propagation times from libp2p layer",
            "table": "libp2p_gossipsub_beacon_block",
            "ihave_table": "libp2p_rpc_meta_control_ihave",
            "connected_table": "libp2p_connected",
            "use_case": "Analyze actual P2P message propagation"
        }
    }


def get_continent_mappings() -> Dict[str, str]:
    """Get continent mappings from continent codes to full names."""
    return {
        "NA": "North America",
        "SA": "South America",
        "EU": "Europe",
        "AF": "Africa",
        "AS": "Asia",
        "OC": "Oceania",
        "AN": "Antarctica",
    }


def get_continent_from_code(code: str) -> str:
    """Convert continent code to full name."""
    mappings = get_continent_mappings()
    return mappings.get(code, code)  # Return code if not found


def get_analysis_config() -> Dict[str, Any]:
    """Get analysis configuration."""
    return {
        "max_propagation_ms": 30000,  # Maximum propagation time to consider (30 seconds)
        "default_percentiles": [50, 75, 90, 95, 99],
        "cdf_resolution": 100,  # Number of points for CDF curves
        "min_peers_for_analysis": 5,  # Minimum peers required for meaningful analysis
    }