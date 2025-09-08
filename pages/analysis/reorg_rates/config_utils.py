"""
Configuration utilities for Reorg Rates Analysis.

This module provides utilities for handling configuration parameters,
validation, and default settings for the reorg rates analysis dashboard.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
import streamlit as st
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_default_config() -> Dict[str, Any]:
    """
    Get default configuration for reorg rates analysis.
    
    Returns:
        Dictionary with default configuration values
    """
    return {
        'grouping_dimension': 'node_type',
        'mev_filter': 'both',
        'num_buckets': 6,
        'aggregation_method': 'p95',
        'show_trend_line': True,
        'start_datetime': datetime.now() - timedelta(days=7),
        'end_datetime': datetime.now() - timedelta(days=1),  # Default to yesterday to avoid incomplete data
        'proposer_filters': {
            'proposer_type': None,
            'proposer_cl': None,
            'proposer_el': None
        }
    }


def validate_config(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate configuration parameters.
    
    Args:
        config: Configuration dictionary to validate
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    # Validate time range
    if 'start_datetime' not in config or 'end_datetime' not in config:
        errors.append("Start and end datetime are required")
    elif config['start_datetime'] >= config['end_datetime']:
        errors.append("Start datetime must be before end datetime")
    
    # Validate time range is not too long (to avoid performance issues)
    if 'start_datetime' in config and 'end_datetime' in config:
        time_diff = config['end_datetime'] - config['start_datetime']
        if time_diff.days > 30:
            errors.append("Time range cannot exceed 30 days")
    
    # Validate grouping dimension
    valid_grouping = ['node_type', 'cl_client', 'el_client', 'cl_el_combined', 'cl_node_type', 'block_building', 'node_type_mev', 'cl_node_type_mev']
    if config.get('grouping_dimension') not in valid_grouping:
        errors.append(f"Invalid grouping dimension. Must be one of: {valid_grouping}")
    
    # Validate MEV filter
    valid_mev = ['both', 'yes', 'no']
    if config.get('mev_filter') not in valid_mev:
        errors.append(f"Invalid MEV filter. Must be one of: {valid_mev}")
    
    # Validate number of buckets
    if 'num_buckets' in config:
        if not isinstance(config['num_buckets'], int) or config['num_buckets'] < 3 or config['num_buckets'] > 20:
            errors.append("Number of buckets must be an integer between 3 and 20")
    
    # Validate aggregation method
    valid_agg = ['p95', 'mean', 'median', 'p99']
    if config.get('aggregation_method') not in valid_agg:
        errors.append(f"Invalid aggregation method. Must be one of: {valid_agg}")
    
    return len(errors) == 0, errors


def sanitize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize and normalize configuration parameters.
    
    Args:
        config: Configuration dictionary to sanitize
        
    Returns:
        Sanitized configuration dictionary
    """
    sanitized = config.copy()
    
    # Ensure datetime objects
    for key in ['start_datetime', 'end_datetime']:
        if key in sanitized and not isinstance(sanitized[key], datetime):
            try:
                sanitized[key] = datetime.fromisoformat(str(sanitized[key]))
            except (ValueError, TypeError):
                logger.warning(f"Could not parse {key} as datetime: {sanitized[key]}")
                del sanitized[key]
    
    # Ensure integer types
    if 'num_buckets' in sanitized:
        try:
            sanitized['num_buckets'] = int(sanitized['num_buckets'])
        except (ValueError, TypeError):
            sanitized['num_buckets'] = 6  # Default
    
    # Ensure boolean types
    if 'show_trend_line' in sanitized:
        sanitized['show_trend_line'] = bool(sanitized['show_trend_line'])
    
    # Sanitize proposer filters
    if 'proposer_filters' in sanitized:
        pf = sanitized['proposer_filters']
        
        # Ensure lists for client filters
        for client_key in ['proposer_cl', 'proposer_el']:
            if client_key in pf and pf[client_key] is not None:
                if not isinstance(pf[client_key], list):
                    pf[client_key] = [pf[client_key]]
                # Remove empty strings
                pf[client_key] = [c for c in pf[client_key] if c and c.strip()]
                if not pf[client_key]:
                    pf[client_key] = None
    
    return sanitized


def get_config_hash(config: Dict[str, Any]) -> str:
    """
    Generate a hash string for configuration to detect changes.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Hash string representing the configuration
    """
    import hashlib
    import json
    
    # Create a simplified version for hashing
    hashable_config = {
        'start_datetime': config.get('start_datetime').isoformat() if config.get('start_datetime') else None,
        'end_datetime': config.get('end_datetime').isoformat() if config.get('end_datetime') else None,
        'grouping_dimension': config.get('grouping_dimension'),
        'mev_filter': config.get('mev_filter'),
        'num_buckets': config.get('num_buckets'),
        'aggregation_method': config.get('aggregation_method'),
        'show_trend_line': config.get('show_trend_line'),
        'proposer_filters': config.get('proposer_filters')
    }
    
    # Sort keys for consistent hashing
    config_str = json.dumps(hashable_config, sort_keys=True, default=str)
    return hashlib.md5(config_str.encode()).hexdigest()


def format_time_range_label(start_datetime: datetime, end_datetime: datetime) -> str:
    """
    Format time range for display in charts and UI.
    
    Args:
        start_datetime: Start datetime
        end_datetime: End datetime
        
    Returns:
        Formatted time range string
    """
    start_str = start_datetime.strftime('%Y-%m-%d')
    end_str = end_datetime.strftime('%Y-%m-%d')
    
    if start_str == end_str:
        return start_str
    else:
        return f"{start_str} to {end_str}"


def get_filter_description(proposer_filters: Dict[str, Any]) -> str:
    """
    Generate a human-readable description of active filters.
    
    Args:
        proposer_filters: Dictionary of proposer filter settings
        
    Returns:
        Human-readable filter description
    """
    if not proposer_filters:
        return "All proposers"
    
    parts = []
    
    # Node type filter
    if proposer_filters.get('proposer_type'):
        node_type = proposer_filters['proposer_type']
        parts.append(f"{node_type.title()} nodes")
    
    # CL client filter
    if proposer_filters.get('proposer_cl'):
        cl_clients = proposer_filters['proposer_cl']
        if len(cl_clients) == 1:
            parts.append(f"{cl_clients[0].title()} CL")
        else:
            parts.append(f"{len(cl_clients)} CL clients")
    
    # EL client filter  
    if proposer_filters.get('proposer_el'):
        el_clients = proposer_filters['proposer_el']
        if len(el_clients) == 1:
            parts.append(f"{el_clients[0].title()} EL")
        else:
            parts.append(f"{len(el_clients)} EL clients")
    
    if not parts:
        return "All proposers"
    
    return " + ".join(parts)


def suggest_optimal_buckets(data_points: int) -> int:
    """
    Suggest optimal number of buckets based on data size.
    
    Args:
        data_points: Number of data points
        
    Returns:
        Suggested number of buckets
    """
    if data_points < 50:
        return 3
    elif data_points < 200:
        return 6
    elif data_points < 1000:
        return 10
    else:
        return 15


def check_analysis_feasibility(
    network: str,
    start_datetime: datetime,
    end_datetime: datetime,
    proposer_filters: Dict[str, Any]
) -> Tuple[bool, List[str], List[str]]:
    """
    Check if the analysis is feasible with the given parameters.
    
    Args:
        network: Network name
        start_datetime: Start datetime
        end_datetime: End datetime  
        proposer_filters: Proposer filter settings
        
    Returns:
        Tuple of (is_feasible, list_of_warnings, list_of_suggestions)
    """
    warnings = []
    suggestions = []
    is_feasible = True
    
    # Check time range
    time_diff = end_datetime - start_datetime
    
    if time_diff.days < 1:
        warnings.append("Time range is very short (< 1 day). Results may not be representative.")
    elif time_diff.days > 14:
        warnings.append("Long time range may result in slower query performance.")
    
    # Check if end time is too recent
    now = datetime.utcnow()
    end_age = now - end_datetime
    if end_age.total_seconds() < 3600:  # Less than 1 hour ago
        warnings.append("End time is very recent. Canonical data may not be available yet.")
        suggestions.append("Consider using an end time at least 1 hour in the past.")
    
    # Network-specific checks
    if 'fusaka' in network.lower():
        suggestions.append("Fusaka devnet data may be limited. Consider shorter time ranges.")
    
    # Filter checks
    if proposer_filters:
        filter_count = sum(1 for v in proposer_filters.values() if v)
        if filter_count > 2:
            warnings.append("Many filters active. This may result in very limited data.")
    
    return is_feasible, warnings, suggestions