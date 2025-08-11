"""
Minimal header for cluster and network selection with persistent storage.
"""
import streamlit as st
from typing import Optional, Tuple
from .config_loader import config_loader
import json


def get_local_storage_script():
    """Generate JavaScript for local storage operations."""
    return """
    <script>
    // Function to save to localStorage
    function saveToLocalStorage(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
        } catch (e) {
            console.error('Failed to save to localStorage:', e);
        }
    }
    
    // Function to load from localStorage
    function loadFromLocalStorage(key) {
        try {
            const item = localStorage.getItem(key);
            return item ? JSON.parse(item) : null;
        } catch (e) {
            console.error('Failed to load from localStorage:', e);
            return null;
        }
    }
    
    // Initialize from localStorage on page load
    document.addEventListener('DOMContentLoaded', function() {
        const savedCluster = loadFromLocalStorage('ethpandaops_cluster');
        const savedNetwork = loadFromLocalStorage('ethpandaops_network');
        
        if (savedCluster || savedNetwork) {
            // Send saved values back to Streamlit
            window.parent.postMessage({
                type: 'localStorage_init',
                cluster: savedCluster,
                network: savedNetwork
            }, '*');
        }
    });
    </script>
    """


def initialize_session_state():
    """Initialize session state for global cluster and network selection with localStorage support."""
    # Try to load from query params first (for sharing links)
    query_params = st.query_params
    
    # Check for saved preferences in query params
    saved_cluster = query_params.get('cluster', None)
    saved_network = query_params.get('network', None)
    
    if 'global_cluster' not in st.session_state:
        if saved_cluster:
            st.session_state.global_cluster = saved_cluster
        else:
            default_cluster = config_loader._config.get('clickhouse', {}).get('default_cluster', 'xatu')
            st.session_state.global_cluster = default_cluster
    
    if 'global_network' not in st.session_state:
        if saved_network:
            st.session_state.global_network = saved_network
        else:
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
    
    # Add logo using st.logo - this puts it in the upper-left corner
    st.logo("branding/ethpandaops.png", size="large", link="https://ethpandaops.io")
    
    # Add branding text after the logo using CSS injection
    st.markdown("""
    <style>
        /* Add ethPandaOps text next to the logo in sidebar */
        div[data-testid="stSidebarHeader"] > div:first-child::after {
            content: "ethPandaOps";
            position: absolute;
            left: 50px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 1.3rem;
            font-weight: 700;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            letter-spacing: -0.02em;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            white-space: nowrap;
        }
        
        /* Ensure the logo container has relative positioning */
        div[data-testid="stSidebarHeader"] > div:first-child {
            position: relative;
        }
    </style>
    """, unsafe_allow_html=True)
    
    # Minimal header with just selectors
    with st.container(border=True):
        col1, col2 = st.columns([1, 1])
        
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
                
                # Update session state and query params if changed
                if selected_cluster != st.session_state.global_cluster:
                    st.session_state.global_cluster = selected_cluster
                    # Update query params for shareable links
                    st.query_params['cluster'] = selected_cluster
                
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
                    
                    # Update session state and query params if changed
                    if selected_network != st.session_state.global_network:
                        st.session_state.global_network = selected_network
                        # Update query params for shareable links
                        st.query_params['network'] = selected_network
                    
                    st.session_state.global_network = selected_network
                else:
                    st.warning("No networks")
                    selected_network = None
            else:
                selected_network = None
    
    return selected_cluster, selected_network


def get_global_cluster() -> Optional[str]:
    """Get the globally selected cluster from session state."""
    initialize_session_state()
    return st.session_state.get('global_cluster')


def get_global_network() -> Optional[str]:
    """Get the globally selected network from session state."""
    initialize_session_state()
    return st.session_state.get('global_network')