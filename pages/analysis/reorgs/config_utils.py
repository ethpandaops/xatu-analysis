"""
Configuration utilities for reorg analysis
"""
import streamlit as st
from datetime import timedelta

def get_metric_info(metric_name):
    """Get human-readable title and description for metrics."""
    metric_info = {
        "reorg_count": {
            "title": "Reorg Count",
            "subtitle": "Total number of chain reorganization events detected"
        },
        "reorg_rate": {
            "title": "Reorg Rate",
            "subtitle": "Frequency of reorganizations per hour"
        },
        "avg_depth": {
            "title": "Average Depth",
            "subtitle": "Mean number of blocks reorganized per event"
        },
        "max_depth": {
            "title": "Maximum Depth",
            "subtitle": "Deepest reorganization observed in the period"
        },
        "detection_delay": {
            "title": "Detection Delay",
            "subtitle": "Time from slot start to reorg detection (milliseconds)"
        },
        "episode_count": {
            "title": "Reorg Episodes",
            "subtitle": "Number of distinct reorg episodes (clustered events within 4-8 seconds)"
        },
        "stabilization_time": {
            "title": "Stabilization Time",
            "subtitle": "Time taken for the chain to stabilize after a reorg"
        },
        "client_diversity": {
            "title": "Client Diversity",
            "subtitle": "Number of distinct clients reporting the same reorg"
        },
        "severity_score": {
            "title": "Severity Score",
            "subtitle": "Composite score based on depth, duration, and client consensus"
        },
        "missed_slot_correlation": {
            "title": "Missed Slot Correlation",
            "subtitle": "Percentage of reorgs following missed block proposals"
        }
    }
    
    return metric_info.get(metric_name, {
        "title": metric_name.replace('_', ' ').title(),
        "subtitle": "No description available for this metric."
    })

def get_default_time_ranges():
    """Get default time range options."""
    return {
        "Last 1 Hour": timedelta(hours=1),
        "Last 6 Hours": timedelta(hours=6),
        "Last 12 Hours": timedelta(hours=12),
        "Last 24 Hours": timedelta(days=1),
        "Last 3 Days": timedelta(days=3),
        "Last 7 Days": timedelta(days=7),
        "Last 14 Days": timedelta(days=14),
        "Last 30 Days": timedelta(days=30),
        "Last 3 Months": timedelta(days=90),
        "Last 6 Months": timedelta(days=180),
        "Last 9 Months": timedelta(days=270),
        "Last 12 Months": timedelta(days=365)
    }

def get_depth_filter_config():
    """Get configuration for depth filtering."""
    return {
        "default_max_depth": 16,
        "absolute_max_depth": 100,
        "invalid_depth_threshold": 1000,
        "invalid_depth_values": [65532, 65533, 65534],  # Known bad values from Caplin
        "depth_buckets": [1, 2, 3, 4, 5, 10, 16, 32, 64]  # For histogram binning
    }

def get_episode_clustering_config():
    """Get configuration for episode clustering."""
    return {
        "episode_window_seconds": 4,  # Group events within 4-second windows
        "max_episode_duration": 30,   # Maximum duration for a single episode
        "min_clients_for_confidence": 2,  # Minimum clients for high confidence
        "storm_threshold_episodes": 3,    # Episodes within 5 minutes for "storm"
        "storm_window_minutes": 5
    }

def get_severity_weights():
    """Get weights for severity score calculation."""
    return {
        "depth_weight": 0.3,          # Weight for reorg depth
        "duration_weight": 0.2,       # Weight for episode duration
        "client_weight": 0.2,         # Weight for client diversity
        "cross_epoch_weight": 0.15,   # Weight for crossing epoch boundaries
        "near_justified_weight": 0.15 # Weight for proximity to justified checkpoint
    }

def get_aggregation_options():
    """Get time aggregation options."""
    return {
        "5 Minutes": "5min",
        "15 Minutes": "15min",
        "30 Minutes": "30min",
        "1 Hour": "1h",
        "4 Hours": "4h",
        "1 Day": "1d"
    }

def get_client_normalization_rules():
    """Get rules for normalizing client depth reporting differences.
    
    Based on empirical analysis of actual reorg events:
    - Lighthouse & Grandine report depth N (correct - number of blocks replaced)
    - Lodestar, Teku & Prysm report depth N+1 (off-by-one higher)
    - Caplin reports invalid values (unsigned int underflows)
    - Nimbus: No recent data, assuming correct like Lighthouse
    
    We normalize to Lighthouse/Grandine standard (the correct value).
    """
    return {
        "caplin": {
            "filter_values": [65532, 65533, 65534, 65535],  # Invalid values to filter
            "depth_adjustment": 0,  # No adjustment after filtering (insufficient valid data)
            "is_trusted": False  # Don't use for consensus depth
        },
        "lighthouse": {
            "filter_values": [],
            "depth_adjustment": 0,  # Reference standard - correct depth
            "is_trusted": True  # Use for consensus depth
        },
        "lodestar": {
            "filter_values": [],
            "depth_adjustment": -1,  # Subtract 1 to match correct depth
            "is_trusted": False  # Don't use for consensus depth (needs adjustment)
        },
        "teku": {
            "filter_values": [],
            "depth_adjustment": -1,  # Subtract 1 to match correct depth
            "is_trusted": False  # Don't use for consensus depth (needs adjustment)
        },
        "prysm": {
            "filter_values": [],
            "depth_adjustment": -1,  # Subtract 1 to match correct depth
            "is_trusted": False  # Don't use for consensus depth (needs adjustment)
        },
        "grandine": {
            "filter_values": [],
            "depth_adjustment": 0,  # Already correct depth
            "is_trusted": True  # Use for consensus depth
        },
        "nimbus": {
            "filter_values": [],
            "depth_adjustment": 0,  # Assuming correct depth like Lighthouse
            "is_trusted": True  # Use for consensus depth
        }
    }