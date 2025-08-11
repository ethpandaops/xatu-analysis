"""
Minimal header for cluster and network selection.
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


def render_global_header() -> Tuple[Optional[str], Optional[str]]:
    """
    Render minimal header with cluster and network selection.
    
    Returns:
        Tuple of (selected_cluster, selected_network)
    """
    # Initialize session state
    initialize_session_state()
    
    # Logo and header in same container
    with st.container(border=True):
        col_logo, col1, col2, col3 = st.columns([0.5, 2, 2, 0.5])
        
        with col_logo:
            st.image("branding/ethpandaops.png", width=40)
        
        with col1:
            # Cluster selection
            clusters = config_loader.get_clickhouse_clusters()
            cluster_names = list(clusters.keys())
            
            if cluster_names:
                try:
                    current_idx = cluster_names.index(st.session_state.global_cluster)
                except ValueError:
                    current_idx = 0
                    st.session_state.global_cluster = cluster_names[0]
                
                selected_cluster = st.selectbox(
                    "Cluster",
                    cluster_names,
                    index=current_idx,
                    key="global_cluster_selector",
                    help="ClickHouse cluster"
                )
                
                st.session_state.global_cluster = selected_cluster
            else:
                st.error("No clusters configured")
                selected_cluster = None
        
        with col2:
            # Network selection
            if selected_cluster:
                # Check if we need to rediscover networks
                if st.session_state.last_discovery_cluster != selected_cluster:
                    config_loader._discovered_networks = None
                    config_loader._network_cache_time = None
                    networks = config_loader.get_networks()
                    st.session_state.discovered_networks = list(networks.keys())
                    st.session_state.last_discovery_cluster = selected_cluster
                else:
                    networks = {name: config_loader.get_network_config(name) 
                               for name in st.session_state.discovered_networks}
                
                if networks:
                    network_names = sorted(list(networks.keys()))
                    
                    try:
                        current_idx = network_names.index(st.session_state.global_network)
                    except ValueError:
                        if 'mainnet' in network_names:
                            current_idx = network_names.index('mainnet')
                        else:
                            current_idx = 0
                        st.session_state.global_network = network_names[current_idx]
                    
                    selected_network = st.selectbox(
                        "Network",
                        network_names,
                        index=current_idx,
                        key="global_network_selector",
                        help="Ethereum network"
                    )
                    
                    st.session_state.global_network = selected_network
                else:
                    st.warning("No networks")
                    selected_network = None
            else:
                selected_network = None
        
        with col3:
            # Settings popover
            with st.popover("⚙️"):
                if st.button("Refresh Networks", use_container_width=True):
                    config_loader._discovered_networks = None
                    config_loader._network_cache_time = None
                    st.session_state.last_discovery_cluster = None
                    st.rerun()
                
                if st.button("Reload Config", use_container_width=True):
                    config_loader.reload_config()
                    st.rerun()
    
    return selected_cluster, selected_network


def get_global_cluster() -> Optional[str]:
    """Get the globally selected cluster from session state."""
    initialize_session_state()
    return st.session_state.get('global_cluster')


def get_global_network() -> Optional[str]:
    """Get the globally selected network from session state."""
    initialize_session_state()
    return st.session_state.get('global_network')