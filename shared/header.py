"""
Centralized header component for cluster and network selection.
Provides a consistent header across all dashboards with data source configuration.
"""
import streamlit as st
from typing import Optional, Tuple
from .config_loader import config_loader


def initialize_session_state():
    """Initialize session state for global cluster and network selection."""
    if 'global_cluster' not in st.session_state:
        default_cluster = config_loader._config.get('clickhouse', {}).get('default_cluster', 'xatu')
        st.session_state.global_cluster = default_cluster
    
    if 'global_network' not in st.session_state:
        st.session_state.global_network = 'mainnet'
    
    if 'discovered_networks' not in st.session_state:
        st.session_state.discovered_networks = []
    
    if 'last_discovery_cluster' not in st.session_state:
        st.session_state.last_discovery_cluster = None


def test_cluster_connection(cluster_name: str) -> bool:
    """
    Test connection to a specific ClickHouse cluster.
    
    Args:
        cluster_name: Name of the cluster to test.
        
    Returns:
        True if connection successful, False otherwise.
    """
    from .database import get_database_connection
    try:
        conn = get_database_connection(cluster_name)
        if conn:
            # Try a simple query
            result = conn.execute("SELECT 1")
            conn.close()
            return True
        return False
    except Exception:
        return False


def render_global_header() -> Tuple[Optional[str], Optional[str]]:
    """
    Render the global header with cluster and network selection.
    
    Returns:
        Tuple of (selected_cluster, selected_network)
    """
    # Initialize session state
    initialize_session_state()
    
    # Create header container with custom styling
    header_container = st.container()
    
    with header_container:
        # Add custom CSS for header styling
        st.markdown("""
        <style>
        .global-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 1rem;
            border-radius: 0.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .header-title {
            color: white;
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }
        .connection-status {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.875rem;
            margin-left: 0.5rem;
        }
        .status-connected {
            background-color: #10b981;
            color: white;
        }
        .status-disconnected {
            background-color: #ef4444;
            color: white;
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Header with gradient background
        st.markdown('<div class="global-header">', unsafe_allow_html=True)
        
        # Create columns for cluster and network selection
        col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
        
        with col1:
            # Cluster selection
            clusters = config_loader.get_clickhouse_clusters()
            cluster_names = list(clusters.keys())
            
            if cluster_names:
                # Get descriptions for display
                cluster_options = []
                for name in cluster_names:
                    desc = clusters[name].get('description', name)
                    cluster_options.append(f"{name}: {desc}")
                
                # Find current index
                try:
                    current_idx = cluster_names.index(st.session_state.global_cluster)
                except ValueError:
                    current_idx = 0
                    st.session_state.global_cluster = cluster_names[0]
                
                selected_idx = st.selectbox(
                    "🔧 ClickHouse Cluster",
                    range(len(cluster_names)),
                    format_func=lambda x: cluster_options[x],
                    index=current_idx,
                    key="global_cluster_selector",
                    help="Select which ClickHouse cluster to query data from"
                )
                
                selected_cluster = cluster_names[selected_idx]
                st.session_state.global_cluster = selected_cluster
            else:
                st.error("No clusters configured")
                selected_cluster = None
        
        with col2:
            # Network selection
            if selected_cluster:
                # Check if we need to rediscover networks (cluster changed)
                if st.session_state.last_discovery_cluster != selected_cluster:
                    with st.spinner("Discovering networks..."):
                        # Force network discovery for new cluster
                        config_loader._discovered_networks = None
                        config_loader._network_cache_time = None
                        networks = config_loader.get_networks()
                        st.session_state.discovered_networks = list(networks.keys())
                        st.session_state.last_discovery_cluster = selected_cluster
                else:
                    # Use cached networks
                    networks = {name: config_loader.get_network_config(name) 
                               for name in st.session_state.discovered_networks}
                
                if networks:
                    network_names = sorted(list(networks.keys()))
                    
                    # Create display names
                    network_options = []
                    for name in network_names:
                        config = networks[name]
                        display = config.get('name', name.title())
                        if config.get('discovered'):
                            display += " 🔍"
                        network_options.append(f"{name}: {display}")
                    
                    # Find current index
                    try:
                        current_idx = network_names.index(st.session_state.global_network)
                    except ValueError:
                        # Default to mainnet if available, otherwise first network
                        if 'mainnet' in network_names:
                            current_idx = network_names.index('mainnet')
                        else:
                            current_idx = 0
                        st.session_state.global_network = network_names[current_idx]
                    
                    selected_idx = st.selectbox(
                        "🌐 Network",
                        range(len(network_names)),
                        format_func=lambda x: network_options[x],
                        index=current_idx,
                        key="global_network_selector",
                        help="Select which Ethereum network to analyze (🔍 = discovered)"
                    )
                    
                    selected_network = network_names[selected_idx]
                    st.session_state.global_network = selected_network
                else:
                    st.warning("No networks available")
                    selected_network = None
            else:
                selected_network = None
        
        with col3:
            # Connection status
            if selected_cluster:
                if st.button("🔄 Test Connection", key="test_cluster_connection"):
                    with st.spinner("Testing..."):
                        if test_cluster_connection(selected_cluster):
                            st.success("Connected")
                        else:
                            st.error("Failed")
        
        with col4:
            # Refresh button
            if st.button("🔄 Refresh Networks", key="refresh_networks"):
                # Clear discovery cache
                config_loader._discovered_networks = None
                config_loader._network_cache_time = None
                st.session_state.last_discovery_cluster = None
                st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Show connection info in expander
        with st.expander("📊 Data Source Details", expanded=False):
            if selected_cluster:
                cluster_info = clusters[selected_cluster]
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("**Cluster Information:**")
                    st.text(f"Host: {cluster_info.get('host', 'N/A')}")
                    st.text(f"Port: {cluster_info.get('port', 'N/A')}")
                    st.text(f"Database: {cluster_info.get('database', 'default')}")
                
                with col2:
                    if selected_network and selected_network in networks:
                        st.markdown("**Network Information:**")
                        network_info = networks[selected_network]
                        st.text(f"Name: {network_info.get('name', selected_network)}")
                        if 'chain_id' in network_info:
                            st.text(f"Chain ID: {network_info.get('chain_id', 'N/A')}")
                        if network_info.get('discovered'):
                            st.text("Source: Discovered from cluster")
                        else:
                            st.text("Source: Configuration file")
    
    return selected_cluster, selected_network


def get_global_cluster() -> Optional[str]:
    """
    Get the globally selected cluster from session state.
    
    Returns:
        Selected cluster name or None if not set.
    """
    initialize_session_state()
    return st.session_state.get('global_cluster')


def get_global_network() -> Optional[str]:
    """
    Get the globally selected network from session state.
    
    Returns:
        Selected network name or None if not set.
    """
    initialize_session_state()
    return st.session_state.get('global_network')