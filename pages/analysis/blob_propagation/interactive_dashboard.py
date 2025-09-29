"""
Interactive dashboard for Blob Propagation Analysis.

This module provides a Streamlit-based dashboard for analyzing blob propagation
patterns across the Ethereum network, showing how blob sidecar events propagate
from proposer groups to attester groups.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import logging
from urllib.parse import urlencode, parse_qs

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import shared components
from shared.header import render_global_header, get_global_cluster, get_global_network
from shared.database import get_database_connection
from shared.ethereum.validator_filters import (
    create_proposer_filters_ui,
    create_attester_filters_ui,
    get_node_classifications
)

# Import local modules
from pages.analysis.blob_propagation.loader import (
    load_blob_propagation_data,
    load_eligible_slots_for_blob_analysis,
    validate_blob_data_availability,
    get_blob_propagation_summary_stats
)
from pages.analysis.blob_propagation.plot_generators import (
    create_blob_propagation_heatmap,
    create_blob_propagation_timeline,
    create_blob_propagation_coverage_chart,
    create_blob_propagation_scatter,
    create_blob_propagation_box_plot,
    create_blob_propagation_network_diagram,
    create_blob_propagation_summary_dashboard,
    create_blob_propagation_metrics_table
)


def render_sidebar_config(cluster: str, network: str, url_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Render the sidebar configuration for blob propagation analysis.
    
    Args:
        cluster: Database cluster name
        network: Network name
        url_config: URL configuration parameters
    
    Returns:
        Configuration dictionary
    """
    
    st.sidebar.subheader("🔧 Configuration")
    
    # Data source selection
    data_source = st.sidebar.selectbox(
        "Data Source",
        options=['beacon_api', 'libp2p'],
        index=['beacon_api', 'libp2p'].index(url_config.get('data_source', 'beacon_api')),
        help="Choose between Beacon API or libp2p data sources"
    )
    
    # Proposer grouping
    proposer_grouping = st.sidebar.selectbox(
        "Proposer Grouping",
        options=['node_type', 'cl_client', 'el_client', 'architecture', 'operator', 'cl_el_combined', 'cl_node_type', 'cl_architecture'],
        index=['node_type', 'cl_client', 'el_client', 'architecture', 'operator', 'cl_el_combined', 'cl_node_type', 'cl_architecture'].index(
            url_config.get('proposer_grouping', 'node_type')
        ),
        format_func=lambda x: {
            'node_type': 'Node Type',
            'cl_client': 'CL Client',
            'el_client': 'EL Client',
            'architecture': 'Architecture',
            'operator': 'Operator',
            'cl_el_combined': 'CL+EL Combination',
            'cl_node_type': 'CL+Node Type',
            'cl_architecture': 'CL+Architecture'
        }[x],
        help="Group proposers by characteristics"
    )
    
    # Attester grouping
    attester_grouping = st.sidebar.selectbox(
        "Attester Grouping",
        options=['node_type', 'cl_client', 'cl_el_combined', 'cl_node_type', 'cl_architecture'],
        index=['node_type', 'cl_client', 'cl_el_combined', 'cl_node_type', 'cl_architecture'].index(
            url_config.get('attester_grouping', 'node_type')
        ),
        format_func=lambda x: {
            'node_type': 'Node Type',
            'cl_client': 'CL Client',
            'cl_el_combined': 'CL+EL Combination',
            'cl_node_type': 'CL+Node Type',
            'cl_architecture': 'CL+Architecture'
        }[x],
        help="Group attesters by characteristics (limited by available data)"
    )
    
    # Proposer and attester filters
    st.sidebar.subheader("🎯 Filters")
    
    # Prepare initial values from URL config
    proposer_initial = {}
    attester_initial = {}
    
    if url_config:
        if 'proposer_type' in url_config:
            proposer_initial['proposer_type'] = url_config['proposer_type']
        if 'proposer_cl' in url_config:
            proposer_initial['proposer_cl'] = url_config['proposer_cl']
        if 'proposer_el' in url_config:
            proposer_initial['proposer_el'] = url_config['proposer_el']
        if 'proposer_architecture' in url_config:
            proposer_initial['proposer_architecture'] = url_config['proposer_architecture']
        if 'proposer_operator' in url_config:
            proposer_initial['proposer_operator'] = url_config['proposer_operator']
        if 'proposer_region' in url_config:
            proposer_initial['proposer_region'] = url_config['proposer_region']
        if 'proposer_datacenter' in url_config:
            proposer_initial['proposer_datacenter'] = url_config['proposer_datacenter']
        
        if 'attester_type' in url_config:
            attester_initial['attester_type'] = url_config['attester_type']
        if 'attester_cl' in url_config:
            attester_initial['attester_cl'] = url_config['attester_cl']
        if 'attester_el' in url_config:
            attester_initial['attester_el'] = url_config['attester_el']
        if 'attester_architecture' in url_config:
            attester_initial['attester_architecture'] = url_config['attester_architecture']
        if 'attester_operator' in url_config:
            attester_initial['attester_operator'] = url_config['attester_operator']
        if 'attester_region' in url_config:
            attester_initial['attester_region'] = url_config['attester_region']
        if 'attester_datacenter' in url_config:
            attester_initial['attester_datacenter'] = url_config['attester_datacenter']
    
    # Proposer filters
    proposer_filters = create_proposer_filters_ui(
        network=network,
        cluster_name=cluster,
        key_prefix="blob_propagation_proposer",
        initial_values=proposer_initial
    )
    
    # Attester filters
    attester_filters = create_attester_filters_ui(
        network=network,
        cluster_name=cluster,
        key_prefix="blob_propagation_attester",
        initial_values=attester_initial
    )
    
    # Time range selection
    st.sidebar.subheader("📅 Time Range")
    
    # Quick period selection
    time_options = {
        "Last 1 Hour": timedelta(hours=1),
        "Last 2 Hours": timedelta(hours=2),
        "Last 6 Hours": timedelta(hours=6),
        "Last 12 Hours": timedelta(hours=12),
        "Last 24 Hours": timedelta(hours=24),
        "Last 2 Days": timedelta(days=2),
        "Last 7 Days": timedelta(days=7),
        "Custom Range": None
    }
    
    selected_period = st.sidebar.selectbox(
        "Time Period",
        options=list(time_options.keys()),
        index=list(time_options.keys()).index(url_config.get('time_period', 'Last 24 Hours')),
        help="Select a predefined time period or choose custom range"
    )
    
    if selected_period == "Custom Range":
        col1, col2 = st.sidebar.columns(2)
        with col1:
            start_date = st.date_input(
                "Start Date",
                value=datetime.now() - timedelta(hours=24),
                help="Analysis start date"
            )
        with col2:
            end_date = st.date_input(
                "End Date", 
                value=datetime.now(),
                help="Analysis end date"
            )
        
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.max.time())
    else:
        end_datetime = datetime.now()
        start_datetime = end_datetime - time_options[selected_period]
    
    # Advanced settings
    st.sidebar.subheader("⚙️ Advanced Settings")
    
    max_propagation_ms = st.sidebar.slider(
        "Max Propagation Time (ms)",
        min_value=1000,
        max_value=60000,
        value=int(url_config.get('max_propagation_ms', 12000)),
        step=1000,
        help="Maximum propagation time to consider for analysis"
    )
    
    time_bucket_ms = st.sidebar.slider(
        "Time Bucket Size (ms)",
        min_value=100,
        max_value=5000,
        value=int(url_config.get('time_bucket_ms', 1000)),
        step=100,
        help="Time bucket size for timeline analysis"
    )
    
    # Chart options
    st.sidebar.subheader("📊 Chart Options")
    
    chart_type = st.sidebar.selectbox(
        "Chart Type",
        options=['heatmap', 'timeline', 'coverage', 'scatter', 'box', 'network', 'dashboard'],
        index=['heatmap', 'timeline', 'coverage', 'scatter', 'box', 'network', 'dashboard'].index(
            url_config.get('chart_type', 'heatmap')
        ),
        format_func=lambda x: {
            'heatmap': 'Heatmap',
            'timeline': 'Timeline',
            'coverage': 'Coverage Chart',
            'scatter': 'Scatter Plot',
            'box': 'Box Plot',
            'network': 'Network Diagram',
            'dashboard': 'Summary Dashboard'
        }[x],
        help="Choose the visualization type"
    )
    
    # Load data button
    st.sidebar.subheader("🚀 Analysis")
    
    load_data = st.sidebar.button(
        "Load Blob Propagation Data",
        type="primary",
        help="Load and analyze blob propagation data"
    )
    
    # Return configuration
    config = {
        'data_source': data_source,
        'proposer_grouping': proposer_grouping,
        'attester_grouping': attester_grouping,
        'start_datetime': start_datetime,
        'end_datetime': end_datetime,
        'max_propagation_ms': max_propagation_ms,
        'time_bucket_ms': time_bucket_ms,
        'chart_type': chart_type,
        'load_data': load_data,
        'proposer_filters': proposer_filters,
        'attester_filters': attester_filters,
        'network': network,
        'cluster': cluster
    }
    
    return config


def parse_url_params() -> Dict[str, Any]:
    """
    Parse URL parameters for blob propagation analysis.
    
    Returns:
        Dictionary with parsed URL parameters
    """
    
    query_params = st.query_params
    
    config = {}
    
    # Simple parameters
    simple_params = [
        'data_source', 'proposer_grouping', 'attester_grouping', 'chart_type',
        'proposer_type', 'attester_type', 'proposer_architecture', 'attester_architecture',
        'proposer_operator', 'attester_operator', 'proposer_region', 'attester_region',
        'proposer_datacenter', 'attester_datacenter', 'time_period'
    ]
    
    for param in simple_params:
        if param in query_params:
            config[param] = query_params[param]
    
    # List parameters
    list_params = ['proposer_cl', 'proposer_el', 'attester_cl', 'attester_el']
    
    for param in list_params:
        if param in query_params:
            # Parse comma-separated list
            config[param] = [x.strip() for x in query_params[param].split(',') if x.strip()]
    
    # Numeric parameters
    numeric_params = ['max_propagation_ms', 'time_bucket_ms']
    
    for param in numeric_params:
        if param in query_params:
            try:
                config[param] = int(query_params[param])
            except (ValueError, TypeError):
                pass
    
    # Date parameters
    if 'start_date' in query_params:
        try:
            config['start_date'] = datetime.fromisoformat(query_params['start_date'])
        except (ValueError, TypeError):
            pass
    
    if 'end_date' in query_params:
        try:
            config['end_date'] = datetime.fromisoformat(query_params['end_date'])
        except (ValueError, TypeError):
            pass
    
    return config


def generate_url_params(config: Dict[str, Any]) -> str:
    """
    Generate URL parameters for sharing blob propagation analysis.
    
    Args:
        config: Configuration dictionary
    
    Returns:
        URL parameter string
    """
    
    params = {}
    
    # Simple parameters
    simple_params = [
        'data_source', 'proposer_grouping', 'attester_grouping', 'chart_type',
        'proposer_type', 'attester_type', 'proposer_architecture', 'attester_architecture',
        'proposer_operator', 'attester_operator', 'proposer_region', 'attester_region',
        'proposer_datacenter', 'attester_datacenter', 'time_period'
    ]
    
    for param in simple_params:
        if param in config:
            params[param] = config[param]
    
    # List parameters
    list_params = ['proposer_cl', 'proposer_el', 'attester_cl', 'attester_el']
    
    for param in list_params:
        if param in config and config[param]:
            params[param] = ','.join(config[param])
    
    # Numeric parameters
    numeric_params = ['max_propagation_ms', 'time_bucket_ms']
    
    for param in numeric_params:
        if param in config:
            params[param] = str(config[param])
    
    # Date parameters
    if 'start_datetime' in config:
        params['start_date'] = config['start_datetime'].isoformat()
    
    if 'end_datetime' in config:
        params['end_date'] = config['end_datetime'].isoformat()
    
    return urlencode(params)


def load_and_process_blob_propagation_data(config: Dict[str, Any]) -> Optional[pd.DataFrame]:
    """
    Load and process blob propagation data based on configuration.
    
    Following the PeerDAS v2 pattern with proper filter handling.
    
    Args:
        config: Configuration dictionary
    
    Returns:
        Processed DataFrame or None if error
    """
    
    # Check if data is already loaded and cached
    if (st.session_state.get('blob_propagation_data_loaded', False) and 
        st.session_state.get('blob_propagation_last_config', {}) == config):
        logger.info("Using cached blob propagation data")
        return st.session_state.blob_propagation_analysis_data.get('data')
    
    # Validate data availability
    if not validate_blob_data_availability(
        config['network'], 
        config['start_datetime'], 
        config['end_datetime'],
        config['data_source'],
        config['cluster']
    ):
        st.error(f"No blob data available for {config['network']} on {config['cluster']} cluster")
        return None
    
    # Load eligible slots using PeerDAS v2 approach
    try:
        eligible_slots, slot_to_block, slot_to_proposer, mev_slots = load_eligible_slots_for_blob_analysis(
            network=config['network'],
            start_date=config['start_datetime'],
            end_date=config['end_datetime'],
            proposer_filters=config['proposer_filters'],
            mev_filter=config.get('mev_filter'),
            cluster_name=config['cluster']
        )
        
        if not eligible_slots:
            st.error("No eligible slots found for the specified criteria")
            return None
        
        st.info(f"Found {len(eligible_slots)} eligible slots")
        
    except Exception as e:
        st.error(f"Error loading eligible slots: {e}")
        return None
    
    # Load blob propagation data
    try:
        data = load_blob_propagation_data(
            network=config['network'],
            start_date=config['start_datetime'],
            end_date=config['end_datetime'],
            eligible_slots=eligible_slots,
            data_source=config['data_source'],
            proposer_group_by=config['proposer_grouping'],
            attester_group_by=config['attester_grouping'],
            max_propagation_ms=config['max_propagation_ms'],
            proposer_filters=config['proposer_filters'],
            attester_filters=config['attester_filters'],
            cluster_name=config['cluster']
        )
        
        if data is None or data.empty:
            st.error("Failed to load blob propagation data")
            return None
        
        # Cache the data
        st.session_state.blob_propagation_data_loaded = True
        st.session_state.blob_propagation_last_config = config
        st.session_state.blob_propagation_analysis_data = {'data': data}
        
        logger.info(f"Successfully loaded and cached blob propagation data: {len(data)} records")
        return data
        
    except Exception as e:
        st.error(f"Error loading blob propagation data: {e}")
        logger.error(f"Blob propagation data loading error: {e}")
        return None


def render_blob_propagation_analysis(data: pd.DataFrame, config: Dict[str, Any]) -> None:
    """
    Render the blob propagation analysis visualizations.
    
    Args:
        data: DataFrame with blob propagation data
        config: Configuration dictionary
    """
    
    if data.empty:
        st.warning("No data available for the selected parameters")
        return
    
    # Display summary statistics
    st.subheader("📊 Summary Statistics")
    
    stats = get_blob_propagation_summary_stats(data)
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Slots", stats.get('total_slots', 0))
    with col2:
        st.metric("Proposer Groups", stats.get('total_proposer_groups', 0))
    with col3:
        st.metric("Attester Groups", stats.get('total_attester_groups', 0))
    with col4:
        st.metric("Total Blob Events", stats.get('total_blob_events', 0))
    
    # Display metrics table
    metrics_table = create_blob_propagation_metrics_table(data)
    st.dataframe(metrics_table, use_container_width=True)
    
    # Render selected chart
    st.subheader(f"📈 {config['chart_type'].title()} Visualization")
    
    chart_type = config['chart_type']
    
    if chart_type == 'heatmap':
        fig = create_blob_propagation_heatmap(data)
        st.plotly_chart(fig, use_container_width=True)
        
    elif chart_type == 'timeline':
        fig = create_blob_propagation_timeline(data)
        st.plotly_chart(fig, use_container_width=True)
        
    elif chart_type == 'coverage':
        fig = create_blob_propagation_coverage_chart(data)
        st.plotly_chart(fig, use_container_width=True)
        
    elif chart_type == 'scatter':
        fig = create_blob_propagation_scatter(data)
        st.plotly_chart(fig, use_container_width=True)
        
    elif chart_type == 'box':
        fig = create_blob_propagation_box_plot(data)
        st.plotly_chart(fig, use_container_width=True)
        
    elif chart_type == 'network':
        fig = create_blob_propagation_network_diagram(data)
        st.plotly_chart(fig, use_container_width=True)
        
    elif chart_type == 'dashboard':
        fig = create_blob_propagation_summary_dashboard(data)
        st.plotly_chart(fig, use_container_width=True)
    
    # Display raw data
    with st.expander("🔍 Raw Data"):
        st.dataframe(data, use_container_width=True)


def main():
    """Main function for the blob propagation analysis dashboard."""
    
    # Render global header
    render_global_header()
    
    # Get cluster and network
    cluster = get_global_cluster()
    network = get_global_network()
    
    # Parse URL parameters
    url_config = parse_url_params()
    
    # Render sidebar configuration
    config = render_sidebar_config(cluster, network, url_config)
    
    # Load and process data if requested
    if config['load_data']:
        with st.spinner("Loading blob propagation data..."):
            data = load_and_process_blob_propagation_data(config)
            
            if data is not None:
                st.success(f"Successfully loaded {len(data)} blob propagation records")
                render_blob_propagation_analysis(data, config)
            else:
                st.error("Failed to load blob propagation data")
    else:
        st.info("Click 'Load Blob Propagation Data' to start the analysis")


if __name__ == "__main__":
    main()
