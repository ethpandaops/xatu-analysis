"""
Shared validator filtering utilities for Ethereum analysis.

This module provides reusable functions for creating Streamlit UI components
and applying validator filters based on node type, CL implementation, and EL implementation.
Supports multiple networks and provides proper caching.
"""

import streamlit as st
import pandas as pd
import polars as pl
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, Set
import logging

from shared.network_spec import NetworkSpec, get_network_spec

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def get_node_classifications(network: str, cluster_name: Optional[str] = None) -> pd.DataFrame:
    """
    Get node classifications from the network YAML file.
    
    Args:
        network: Network name
        cluster_name: Optional cluster name (for compatibility)
        
    Returns:
        DataFrame with node names and their classifications
    """
    # Get network spec
    network_spec = get_network_spec(network)
    if not network_spec:
        logger.error(f"No network specification found for network: {network}")
        return pd.DataFrame()
    
    try:
        # Build classifications from network spec
        classifications = []
        
        for node_name in network_spec.get_all_nodes():
            node_info = network_spec.get_node_info(node_name)
            if not node_info:
                continue
            
            tags = node_info.get('tags', [])
            attributes = node_info.get('attributes', {})
            
            # Determine node type
            node_type = 'regular'
            if 'supernode' in tags or attributes.get('supernode', False):
                node_type = 'supernode'
            
            # Extract CL and EL from tags
            cl_implementation = None
            el_implementation = None
            
            for tag in tags:
                if tag.startswith('cl:'):
                    cl_implementation = tag.split(':')[1]
                elif tag.startswith('el:'):
                    el_implementation = tag.split(':')[1]
            
            classifications.append({
                'client_name': node_name,
                'node_type': node_type,
                'cl_implementation': cl_implementation,
                'el_implementation': el_implementation
            })
        
        df = pd.DataFrame(classifications)
        return df
        
    except Exception as e:
        logger.error(f"Error getting node classifications from network spec: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def get_available_clients(network: str) -> Tuple[List[str], List[str]]:
    """
    Get available CL and EL clients for a network.
    
    Args:
        network: Network name
        
    Returns:
        Tuple of (cl_clients, el_clients) lists
    """
    network_spec = get_network_spec(network)
    
    cl_clients = set()
    el_clients = set()
    
    # Handle networks without spec files (like mainnet)
    if not network_spec:
        # Return default clients for networks without specs
        return [], []
    
    for node_name in network_spec.get_all_nodes():
        clients = network_spec.get_node_clients(node_name)
        if clients['cl']:
            cl_clients.add(clients['cl'])
        if clients['el']:
            el_clients.add(clients['el'])
    
    return sorted(list(cl_clients)), sorted(list(el_clients))


def create_proposer_filters_ui(
    network: str, 
    key_prefix: str = "proposer",
    initial_values: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create Streamlit UI components for proposer filtering.
    
    Args:
        network: Network name
        key_prefix: Prefix for Streamlit widget keys to avoid conflicts
        initial_values: Optional dict with initial values from URL params
        
    Returns:
        Dictionary with filter values
    """
    st.subheader("🎯 Proposer Filters")
    
    # Get available clients for this network
    cl_clients, el_clients = get_available_clients(network)
    
    # Determine initial values
    if initial_values:
        initial_type = initial_values.get('proposer_type', 'all')
        if initial_type is None:
            initial_type = 'all'
        initial_cl = initial_values.get('proposer_cl', cl_clients)
        if initial_cl is None:
            initial_cl = cl_clients
        initial_el = initial_values.get('proposer_el', [el for el in el_clients if el.lower() != 'nimbusel'])
        if initial_el is None:
            initial_el = [el for el in el_clients if el.lower() != 'nimbusel']
    else:
        initial_type = 'all'
        initial_cl = cl_clients
        initial_el = [el for el in el_clients if el.lower() != 'nimbusel']
    
    proposer_type = st.selectbox(
        "Proposer Node Type",
        options=["all", "supernode", "regular"],
        index=["all", "supernode", "regular"].index(initial_type) if initial_type in ["all", "supernode", "regular"] else 0,
        format_func=lambda x: {
            "all": "All Node Types",
            "supernode": "Supernodes Only", 
            "regular": "Regular Nodes Only"
        }[x],
        key=f"{key_prefix}_type",
        help="Filter by proposer node type"
    )
    
    proposer_cl = st.multiselect(
        "Proposer CL Clients",
        options=cl_clients,
        default=initial_cl,
        key=f"{key_prefix}_cl",
        help="Filter by proposer consensus layer client"
    )
    
    proposer_el = st.multiselect(
        "Proposer EL Clients", 
        options=el_clients,
        default=initial_el,
        key=f"{key_prefix}_el",
        help="Filter by proposer execution layer client"
    )
    
    return {
        'proposer_type': proposer_type if proposer_type != "all" else None,
        'proposer_cl': proposer_cl if proposer_cl and set(proposer_cl) != set(cl_clients) else None,
        'proposer_el': proposer_el if proposer_el and set(proposer_el) != set(el_clients) else None
    }


def create_attester_filters_ui(
    network: str, 
    key_prefix: str = "attester",
    initial_values: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create Streamlit UI components for attester filtering.
    
    Args:
        network: Network name
        key_prefix: Prefix for Streamlit widget keys to avoid conflicts
        initial_values: Optional dict with initial values from URL params
        
    Returns:
        Dictionary with filter values
    """
    st.subheader("👥 Attester Filters")
    
    # Get available clients for this network
    cl_clients, el_clients = get_available_clients(network)
    
    # Determine initial values
    if initial_values:
        initial_type = initial_values.get('attester_type', 'all')
        if initial_type is None:
            initial_type = 'all'
        initial_cl = initial_values.get('attester_cl', cl_clients)
        if initial_cl is None:
            initial_cl = cl_clients
        initial_el = initial_values.get('attester_el', [el for el in el_clients if el.lower() != 'nimbusel'])
        if initial_el is None:
            initial_el = [el for el in el_clients if el.lower() != 'nimbusel']
    else:
        initial_type = 'all'
        initial_cl = cl_clients
        initial_el = [el for el in el_clients if el.lower() != 'nimbusel']
    
    attester_type = st.selectbox(
        "Attester Node Type",
        options=["all", "supernode", "regular"],
        index=["all", "supernode", "regular"].index(initial_type) if initial_type in ["all", "supernode", "regular"] else 0,
        format_func=lambda x: {
            "all": "All Node Types", 
            "supernode": "Supernodes Only",
            "regular": "Regular Nodes Only"
        }[x],
        key=f"{key_prefix}_type",
        help="Filter by attester node type"
    )
    
    attester_cl = st.multiselect(
        "Attester CL Clients",
        options=cl_clients,
        default=initial_cl,
        key=f"{key_prefix}_cl", 
        help="Filter by attester consensus layer client"
    )
    
    attester_el = st.multiselect(
        "Attester EL Clients",
        options=el_clients,
        default=initial_el,
        key=f"{key_prefix}_el",
        help="Filter by attester execution layer client"
    )
    
    return {
        'attester_type': attester_type if attester_type != "all" else None,
        'attester_cl': attester_cl if attester_cl and set(attester_cl) != set(cl_clients) else None,
        'attester_el': attester_el if attester_el and set(attester_el) != set(el_clients) else None
    }


def get_filtered_validator_indices(
    network: str,
    validator_type: str = "proposer",  
    node_type: Optional[str] = None,
    cl_filter: Optional[List[str]] = None,
    el_filter: Optional[List[str]] = None
) -> List[int]:
    """
    Get validator indices that match the specified filters.
    
    Args:
        network: Network name
        validator_type: Either "proposer" or "attester" (for logging)
        node_type: Filter by node type ('supernode', 'regular', or None for all)
        cl_filter: List of consensus layer clients to include
        el_filter: List of execution layer clients to include
        
    Returns:
        List of validator indices matching the filters
    """
    logger.info(f"Getting filtered {validator_type} validator indices for network={network}")
    
    network_spec = get_network_spec(network)
    if not network_spec:
        logger.warning(f"No network specification found for {network} - returning empty list")
        return []
    
    validator_indices = []
    nodes_processed = 0
    nodes_matched = 0
    
    # Check for any filters that require processing
    has_filters = node_type or cl_filter or el_filter
    
    for node_name in network_spec.get_all_nodes():
        nodes_processed += 1
        node_info = network_spec.get_node_info(node_name)
        if not node_info:
            continue
        
        # If no filters, include all nodes from the spec
        if not has_filters:
            validators = network_spec.get_validators(node_name)
            validator_indices.extend(validators)
            nodes_matched += 1
            continue
            
        # Check if node matches filters
        tags = node_info.get('tags', [])
        attributes = node_info.get('attributes', {})
        node_is_supernode = 'supernode' in tags or attributes.get('supernode', False)
        
        # Check node type filter
        if node_type:
            if node_type == 'supernode' and not node_is_supernode:
                continue
            if node_type == 'regular' and node_is_supernode:
                continue
        
        # Check CL filter
        if cl_filter:
            node_cl = None
            for tag in tags:
                if tag.startswith('cl:'):
                    node_cl = tag.split(':')[1]
                    break
            if not node_cl or node_cl not in cl_filter:
                continue
        
        # Check EL filter
        if el_filter:
            node_el = None
            for tag in tags:
                if tag.startswith('el:'):
                    node_el = tag.split(':')[1]
                    break
            if not node_el or node_el not in el_filter:
                continue
        
        # Add validator indices for this node
        validators = network_spec.get_validators(node_name)
        validator_indices.extend(validators)
        nodes_matched += 1
    
    logger.info(f"{validator_type.title()} filter: processed {nodes_processed} nodes, matched {nodes_matched}, total validators: {len(validator_indices)}")
    return validator_indices


def get_filtered_proposer_indices(
    network: str,
    proposer_type: Optional[str] = None,
    cl_filter: Optional[List[str]] = None,
    el_filter: Optional[List[str]] = None
) -> List[int]:
    """
    Get proposer validator indices that match the specified filters.
    
    Args:
        network: Network name
        proposer_type: Filter by node type ('supernode', 'regular', or None)
        cl_filter: List of consensus layer clients to include
        el_filter: List of execution layer clients to include
        
    Returns:
        List of proposer validator indices matching the filters
    """
    return get_filtered_validator_indices(
        network=network,
        validator_type="proposer",
        node_type=proposer_type,
        cl_filter=cl_filter,
        el_filter=el_filter
    )


def get_filtered_attester_indices(
    network: str, 
    attester_type: Optional[str] = None,
    cl_filter: Optional[List[str]] = None,
    el_filter: Optional[List[str]] = None
) -> List[int]:
    """
    Get attester validator indices that match the specified filters.
    
    Args:
        network: Network name
        attester_type: Filter by node type ('supernode', 'regular', or None)
        cl_filter: List of consensus layer clients to include
        el_filter: List of execution layer clients to include
        
    Returns:
        List of attester validator indices matching the filters
    """
    return get_filtered_validator_indices(
        network=network,
        validator_type="attester",
        node_type=attester_type,
        cl_filter=cl_filter,
        el_filter=el_filter
    )


def get_validator_node_mapping(network: str) -> Dict[int, Dict[str, Any]]:
    """
    Get mapping from validator index to node information.
    
    Args:
        network: Network name
        
    Returns:
        Dictionary mapping validator indices to node info (node_name, node_type, cl_client, el_client)
    """
    network_spec = get_network_spec(network)
    if not network_spec:
        return {}
    
    validator_mapping = {}
    
    for node_name in network_spec.get_all_nodes():
        node_info = network_spec.get_node_info(node_name)
        if not node_info:
            continue
        
        # Get node characteristics
        tags = node_info.get('tags', [])
        attributes = node_info.get('attributes', {})
        node_is_supernode = 'supernode' in tags or attributes.get('supernode', False)
        
        # Extract clients
        cl_client = None
        el_client = None
        for tag in tags:
            if tag.startswith('cl:'):
                cl_client = tag.split(':')[1]
            elif tag.startswith('el:'):
                el_client = tag.split(':')[1]
        
        # Get validators for this node
        validators = network_spec.get_validators(node_name)
        
        node_type = 'supernode' if node_is_supernode else 'regular'
        
        for validator_index in validators:
            validator_mapping[validator_index] = {
                'node_name': node_name,
                'node_type': node_type,
                'cl_client': cl_client,
                'el_client': el_client
            }
    
    return validator_mapping


def build_validator_filter_condition(validator_indices: List[int]) -> str:
    """
    Build SQL WHERE condition for filtering by validator indices.
    
    Args:
        validator_indices: List of validator indices to include
        
    Returns:
        SQL WHERE condition string, or empty string if no indices provided
    """
    if not validator_indices:
        return ""
    
    # For large lists, use IN clause with proper formatting
    if len(validator_indices) == 1:
        return f"AND validator_index = {validator_indices[0]}"
    else:
        indices_str = ','.join(str(idx) for idx in sorted(validator_indices))
        return f"AND validator_index IN ({indices_str})"


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def get_network_summary(network: str) -> Dict[str, Any]:
    """
    Get summary information about a network's validator distribution.
    
    Args:
        network: Network name
        
    Returns:
        Dictionary with network summary statistics
    """
    network_spec = get_network_spec(network)
    if not network_spec:
        return {
            'total_nodes': 0,
            'total_validators': 0,
            'supernodes': 0,
            'regular_nodes': 0,
            'cl_distribution': {},
            'el_distribution': {}
        }
    
    cl_distribution = {}
    el_distribution = {}
    supernodes = 0
    regular_nodes = 0
    total_validators = 0
    
    for node_name in network_spec.get_all_nodes():
        node_info = network_spec.get_node_info(node_name)
        if not node_info:
            continue
        
        # Count validators
        validators = network_spec.get_validators(node_name)
        total_validators += len(validators)
        
        # Determine node type
        tags = node_info.get('tags', [])
        attributes = node_info.get('attributes', {})
        node_is_supernode = 'supernode' in tags or attributes.get('supernode', False)
        
        if node_is_supernode:
            supernodes += 1
        else:
            regular_nodes += 1
        
        # Count clients
        for tag in tags:
            if tag.startswith('cl:'):
                cl_client = tag.split(':')[1]
                cl_distribution[cl_client] = cl_distribution.get(cl_client, 0) + 1
            elif tag.startswith('el:'):
                el_client = tag.split(':')[1]
                el_distribution[el_client] = el_distribution.get(el_client, 0) + 1
    
    return {
        'total_nodes': len(network_spec.get_all_nodes()),
        'total_validators': total_validators,
        'supernodes': supernodes,
        'regular_nodes': regular_nodes,
        'cl_distribution': cl_distribution,
        'el_distribution': el_distribution
    }


def validate_network_filters(
    network: str,
    proposer_filters: Dict[str, Any],
    attester_filters: Dict[str, Any]
) -> Tuple[bool, str]:
    """
    Validate that the provided filters are applicable to the network.
    
    Args:
        network: Network name
        proposer_filters: Proposer filter configuration
        attester_filters: Attester filter configuration
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    network_spec = get_network_spec(network)
    if not network_spec:
        return False, f"No network specification found for {network}"
    
    # Get available clients
    cl_clients, el_clients = get_available_clients(network)
    
    # Check proposer CL filter
    proposer_cl = proposer_filters.get('proposer_cl')
    if proposer_cl:
        invalid_cl = set(proposer_cl) - set(cl_clients)
        if invalid_cl:
            return False, f"Invalid proposer CL clients for {network}: {invalid_cl}"
    
    # Check proposer EL filter
    proposer_el = proposer_filters.get('proposer_el')
    if proposer_el:
        invalid_el = set(proposer_el) - set(el_clients)
        if invalid_el:
            return False, f"Invalid proposer EL clients for {network}: {invalid_el}"
    
    # Check attester CL filter
    attester_cl = attester_filters.get('attester_cl')
    if attester_cl:
        invalid_cl = set(attester_cl) - set(cl_clients)
        if invalid_cl:
            return False, f"Invalid attester CL clients for {network}: {invalid_cl}"
    
    # Check attester EL filter
    attester_el = attester_filters.get('attester_el')
    if attester_el:
        invalid_el = set(attester_el) - set(el_clients)
        if invalid_el:
            return False, f"Invalid attester EL clients for {network}: {invalid_el}"
    
    return True, ""