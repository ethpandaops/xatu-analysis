"""
UI utilities for multi-cluster support in Xatu Analysis Dashboard.
"""
import streamlit as st
from typing import Optional, Dict, Any
from .config_loader import config_loader
from .database import get_database_connection


def render_cluster_selector(key_prefix: str = "") -> Optional[str]:
    """
    Render a cluster selector widget in the Streamlit sidebar.
    
    Args:
        key_prefix: Prefix for the session state key to avoid conflicts.
        
    Returns:
        Selected cluster name or None if no clusters available.
    """
    clusters = config_loader.get_clickhouse_clusters()
    
    if not clusters:
        st.sidebar.error("No ClickHouse clusters configured")
        return None
    
    cluster_names = list(clusters.keys())
    cluster_descriptions = [
        f"{name}: {clusters[name].get('description', 'No description')}"
        for name in cluster_names
    ]
    
    default_cluster = config_loader._config.get('clickhouse', {}).get('default_cluster', 'xatu')
    default_index = cluster_names.index(default_cluster) if default_cluster in cluster_names else 0
    
    selected_idx = st.sidebar.selectbox(
        "ClickHouse Cluster",
        range(len(cluster_names)),
        format_func=lambda x: cluster_descriptions[x],
        index=default_index,
        key=f"{key_prefix}_cluster_selector",
        help="Select which ClickHouse cluster to query data from"
    )
    
    return cluster_names[selected_idx]


def render_network_selector(
    key_prefix: str = "",
    cluster_name: Optional[str] = None,
    include_discovered: bool = True
) -> Optional[str]:
    """
    Render a network selector widget with support for discovered networks.
    
    Args:
        key_prefix: Prefix for the session state key to avoid conflicts.
        cluster_name: Optional cluster name to discover networks from.
        include_discovered: Whether to include dynamically discovered networks.
        
    Returns:
        Selected network name or None if no networks available.
    """
    if include_discovered and cluster_name:
        # Temporarily switch to the specified cluster for discovery
        with st.spinner("Discovering available networks..."):
            networks = config_loader.get_networks()
    else:
        # Just get static networks
        networks = {
            name: config 
            for name, config in config_loader._config.get('networks', {}).items()
            if config.get('enabled', True)
        }
    
    if not networks:
        st.sidebar.error("No networks available")
        return None
    
    network_names = sorted(list(networks.keys()))
    network_descriptions = []
    
    for name in network_names:
        config = networks[name]
        desc = f"{name}: {config.get('name', name.title())}"
        if config.get('discovered'):
            desc += " (discovered)"
        network_descriptions.append(desc)
    
    # Default to mainnet if available
    default_index = network_names.index('mainnet') if 'mainnet' in network_names else 0
    
    selected_idx = st.sidebar.selectbox(
        "Network",
        range(len(network_names)),
        format_func=lambda x: network_descriptions[x],
        index=default_index,
        key=f"{key_prefix}_network_selector",
        help="Select which Ethereum network to analyze"
    )
    
    return network_names[selected_idx]


def test_cluster_connection(cluster_name: str) -> bool:
    """
    Test connection to a specific ClickHouse cluster.
    
    Args:
        cluster_name: Name of the cluster to test.
        
    Returns:
        True if connection successful, False otherwise.
    """
    try:
        conn = get_database_connection(cluster_name)
        if conn:
            # Try a simple query
            result = conn.execute("SELECT 1")
            conn.close()
            return True
        return False
    except Exception as e:
        st.error(f"Connection test failed for cluster '{cluster_name}': {e}")
        return False


def get_cluster_info(cluster_name: str) -> Dict[str, Any]:
    """
    Get detailed information about a ClickHouse cluster.
    
    Args:
        cluster_name: Name of the cluster.
        
    Returns:
        Dictionary with cluster information.
    """
    try:
        cluster = config_loader.get_clickhouse_cluster(cluster_name)
        # Remove sensitive information
        info = {
            'name': cluster_name,
            'host': cluster.get('host'),
            'port': cluster.get('port'),
            'database': cluster.get('database'),
            'protocol': cluster.get('protocol'),
            'description': cluster.get('description'),
            'has_credentials': bool(cluster.get('username') and cluster.get('password'))
        }
        return info
    except Exception as e:
        return {'error': str(e)}