"""
Interactive dashboard for Blob Mempool Analysis.

Analyzes blob transactions in the mempool compared to blobs included in canonical beacon blocks,
tracking mempool presence and inclusion rates across different clients.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
import logging
from urllib.parse import urlencode

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import shared components
from shared.header import render_global_header, get_global_cluster, get_global_network
from shared.database import get_database_connection

# Import local modules
from pages.analysis.blob_mempool_analysis.loader import (
    load_eligible_slots,
    load_available_clients,
    load_canonical_blob_data,
    load_mempool_blob_data,
    load_combined_blob_analysis,
    load_blob_inclusion_summary,
    load_blob_timeline_data,
    validate_data_availability
)
from pages.analysis.blob_mempool_analysis.plot_generators import (
    create_blob_count_timeline,
    create_match_percentage_chart,
    create_client_comparison_bar,
    create_blob_correlation_scatter,
    create_hourly_heatmap,
    create_summary_metrics_cards,
    create_dual_axis_chart,
    create_blob_gas_analysis_chart,
    create_blob_size_analysis_chart
)
from pages.analysis.blob_mempool_analysis.config_utils import (
    get_analysis_config,
    get_visualization_options,
    get_time_range_presets,
    get_metric_options,
    validate_analysis_params
)


def parse_url_params() -> Dict[str, Any]:
    """Parse URL query parameters and return configuration dict."""
    params = st.query_params
    config = {}

    # Parse period parameter (for quick time selections)
    if 'period' in params:
        config['period'] = params['period']

    # Parse datetime parameters
    if 'start_date' in params:
        try:
            config['start_datetime'] = datetime.fromisoformat(params['start_date'])
        except:
            pass

    if 'end_date' in params:
        try:
            config['end_datetime'] = datetime.fromisoformat(params['end_date'])
        except:
            pass

    # Parse string parameters
    for key in ['chart_type', 'view_mode', 'metric_type']:
        if key in params:
            config[key] = params[key]

    # Parse list parameters (comma-separated)
    if 'selected_clients' in params:
        values = params['selected_clients'].split(',')
        config['selected_clients'] = [v.strip() for v in values if v.strip()]

    # Parse boolean parameters
    if 'filter_zero_blobs' in params:
        config['filter_zero_blobs'] = params['filter_zero_blobs'].lower() == 'true'

    return config


def generate_url_params(config: Dict[str, Any]) -> str:
    """Generate URL parameters from configuration."""
    params = {}

    # Add period parameter
    if 'period' in config and config['period']:
        params['period'] = config['period']

    # Add datetime parameters
    if 'start_datetime' in config and config['start_datetime']:
        params['start_date'] = config['start_datetime'].isoformat()

    if 'end_datetime' in config and config['end_datetime']:
        params['end_date'] = config['end_datetime'].isoformat()

    # Add other parameters
    simple_params = ['chart_type', 'view_mode', 'metric_type', 'filter_zero_blobs']
    for key in simple_params:
        if key in config and config[key] is not None:
            params[key] = str(config[key])

    # Add list parameters
    if 'selected_clients' in config and config['selected_clients']:
        params['selected_clients'] = ','.join(config['selected_clients'])

    return params


def update_url_with_config(config: Dict[str, Any]):
    """Update the browser URL with the current configuration."""
    params = generate_url_params(config)
    st.query_params.update(params)


def initialize_session_state():
    """Initialize session state variables."""
    if 'blob_mempool_data_loaded' not in st.session_state:
        st.session_state.blob_mempool_data_loaded = False
    if 'blob_mempool_analysis_data' not in st.session_state:
        st.session_state.blob_mempool_analysis_data = {}
    if 'blob_mempool_last_config' not in st.session_state:
        st.session_state.blob_mempool_last_config = None
    
    # Load URL parameters on first run for initial configuration
    if 'blob_mempool_url_params_loaded' not in st.session_state:
        st.session_state.blob_mempool_url_params_loaded = True
        st.session_state.blob_mempool_url_config = parse_url_params()


def render_sidebar_configuration() -> Dict[str, Any]:
    """
    Render sidebar configuration for Blob Mempool analysis.
    
    Returns:
        Configuration dictionary
    """
    cluster = get_global_cluster()
    network = get_global_network()
    
    if not cluster or not network:
        st.error("Please select a cluster and network from the header")
        return None
    
    # Check if cluster or network changed
    prev_cluster = st.session_state.get('blob_mempool_previous_cluster', None)
    prev_network = st.session_state.get('blob_mempool_previous_network', None)
    
    if (prev_cluster and prev_cluster != cluster) or (prev_network and prev_network != network):
        logger.info(f"Cluster/Network changed from {prev_cluster}/{prev_network} to {cluster}/{network}, clearing cache")
        st.cache_data.clear()
        st.session_state.blob_mempool_analysis_data = {}
        st.session_state.blob_mempool_data_loaded = False
    
    st.session_state.blob_mempool_previous_cluster = cluster
    st.session_state.blob_mempool_previous_network = network
    
    st.sidebar.header("📊 Analysis Configuration")
    
    # Time range selection
    st.sidebar.subheader("📅 Time Range")
    
    # Get query parameters for persistence
    query_params = st.query_params
    
    # Check if we have saved time range in query params
    saved_period = query_params.get("period", None)
    saved_start = query_params.get("start", None)
    saved_end = query_params.get("end", None)
    saved_start_time = query_params.get("start_time", None)
    saved_end_time = query_params.get("end_time", None)
    
    # Quick period selection
    time_options = {
        "Last 1 Hour": timedelta(hours=1),
        "Last 6 Hours": timedelta(hours=6),
        "Last 12 Hours": timedelta(hours=12),
        "Last 24 Hours": timedelta(hours=24),
        "Last 3 Days": timedelta(days=3),
        "Last 7 Days": timedelta(days=7),
        "Custom": None
    }
    
    # Determine default period based on saved query params
    if saved_period and saved_period in time_options:
        default_period_index = list(time_options.keys()).index(saved_period)
    else:
        default_period_index = 1  # Default to "Last 6 Hours"
    
    selected_period = st.sidebar.selectbox(
        "Quick Period Selection",
        options=list(time_options.keys()),
        index=default_period_index,
        help="Select a predefined period or choose Custom for manual selection"
    )
    
    # Set dates based on selection
    if selected_period != "Custom":
        time_delta = time_options[selected_period]
        end_date = datetime.now().date()
        start_date = (datetime.now() - time_delta).date()
        
        # Show the selected range (read-only)
        col1, col2 = st.sidebar.columns(2)
        with col1:
            st.date_input(
                "Start Date",
                value=start_date,
                disabled=True,
                key="start_date_display"
            )
        with col2:
            st.date_input(
                "End Date",
                value=end_date,
                disabled=True,
                key="end_date_display"
            )
    else:
        # Custom date selection
        # Parse saved dates/times if available
        from datetime import time as datetime_time
        
        if saved_start:
            try:
                default_start_date = datetime.strptime(saved_start, "%Y-%m-%d").date()
            except:
                default_start_date = (datetime.now() - timedelta(hours=6)).date()
        else:
            default_start_date = (datetime.now() - timedelta(hours=6)).date()
        
        if saved_end:
            try:
                default_end_date = datetime.strptime(saved_end, "%Y-%m-%d").date()
            except:
                default_end_date = datetime.now().date()
        else:
            default_end_date = datetime.now().date()
        
        if saved_start_time:
            try:
                default_start_time = datetime.strptime(saved_start_time, "%H:%M:%S").time()
            except:
                default_start_time = (datetime.now() - timedelta(hours=6)).time()
        else:
            default_start_time = (datetime.now() - timedelta(hours=6)).time()
        
        if saved_end_time:
            try:
                default_end_time = datetime.strptime(saved_end_time, "%H:%M:%S").time()
            except:
                default_end_time = datetime.now().time()
        else:
            default_end_time = datetime.now().time()
        
        col1, col2 = st.sidebar.columns(2)
        with col1:
            start_date = st.date_input(
                "Start Date",
                value=default_start_date,
                max_value=datetime.now().date(),
                key="start_date_custom"
            )
            start_time = st.time_input(
                "Start Time",
                value=default_start_time,
                key="start_time_custom",
                step=300  # 5 minute intervals
            )
        
        with col2:
            end_date = st.date_input(
                "End Date",
                value=default_end_date,
                max_value=datetime.now().date(),
                key="end_date_custom"
            )
            end_time = st.time_input(
                "End Time",
                value=default_end_time,
                key="end_time_custom",
                step=300  # 5 minute intervals
            )
    
    # Convert to datetime objects
    if selected_period == "Custom":
        start_datetime = datetime.combine(start_date, start_time)
        end_datetime = datetime.combine(end_date, end_time)
    else:
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.max.time())
    
    # Analysis type selection
    st.sidebar.subheader("📊 Analysis Type")
    analysis_type = st.sidebar.radio(
        "Visualization Type",
        options=['overview', 'detailed', 'comparison'],
        format_func=lambda x: {
            'overview': 'Overview (Timeline Charts)',
            'detailed': 'Detailed (Individual Client Analysis)',
            'comparison': 'Comparison (Client Performance)'
        }.get(x, x),
        index=0,
        help="Choose visualization type: Overview for general trends, Detailed for individual analysis, Comparison for performance differences"
    )
    
    # Chart type selection
    st.sidebar.subheader("📈 Chart Options")
    chart_type = st.sidebar.selectbox(
        "Chart Type",
        options=['line_chart', 'bar_chart', 'scatter_plot', 'heatmap'],
        format_func=lambda x: {
            'line_chart': 'Line Chart (Timeline)',
            'bar_chart': 'Bar Chart (Comparison)',
            'scatter_plot': 'Scatter Plot (Correlation)',
            'heatmap': 'Heatmap (Patterns)'
        }.get(x, x),
        index=0,
        help="Select the type of visualization"
    )
    
    # Filter options
    st.sidebar.subheader("🔍 Filters")
    filter_zero_blobs = st.sidebar.checkbox(
        "Filter out slots with zero blobs",
        value=True,
        help="Exclude slots that don't contain any blobs"
    )
    
    # Advanced options
    with st.sidebar.expander("Advanced Options", expanded=False):
        show_summary_stats = st.checkbox(
            "Show Summary Statistics",
            value=True,
            help="Display summary metrics cards"
        )
        
        show_blob_gas_analysis = st.checkbox(
            "Show Blob Gas Analysis",
            value=False,
            help="Display blob gas usage patterns"
        )
        
        show_blob_size_analysis = st.checkbox(
            "Show Blob Size Analysis",
            value=False,
            help="Display blob sidecar size patterns"
        )
        
        show_data_quality = st.checkbox(
            "Show Data Quality Info",
            value=False,
            help="Display data availability and quality metrics"
        )
    
    # Load data button
    load_data = st.sidebar.button(
        "🔄 Load Analysis Data",
        type="primary",
        help="Load blob mempool analysis data with current settings"
    )
    
    # Build configuration
    config = {
        'cluster': cluster,
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
        'start_datetime': start_datetime,
        'end_datetime': end_datetime,
        'analysis_type': analysis_type,
        'chart_type': chart_type,
        'filter_zero_blobs': filter_zero_blobs,
        'show_summary_stats': show_summary_stats,
        'show_blob_gas_analysis': show_blob_gas_analysis,
        'show_blob_size_analysis': show_blob_size_analysis,
        'show_data_quality': show_data_quality,
        'load_data': load_data
    }
    
    return config


def load_analysis_data(config: Dict[str, Any], cluster: str, network: str, selected_clients: List[str]) -> Dict[str, Any]:
    """Load analysis data based on configuration."""
    
    try:
        with st.spinner("Loading blob mempool analysis data..."):
            # Validate data availability first
            validation = validate_data_availability(
                network,
                config['start_datetime'],
                config['end_datetime'],
                cluster
            )
            
            if validation['errors']:
                for error in validation['errors']:
                    st.error(error)
                return {}
            
            # Load all required data
            data = {}
            
            # Load combined analysis data (main dataset)
            data['analysis_data'] = load_combined_blob_analysis(
                network,
                config['start_datetime'],
                config['end_datetime'],
                selected_clients,
                cluster
            )
            
            # Debug: Log data loading results
            st.write("🔍 **Debug: Data Loading Results**")
            st.write(f"**Analysis data loaded:** {len(data['analysis_data'])} records")
            if not data['analysis_data'].empty:
                st.write(f"**Columns:** {', '.join(data['analysis_data'].columns.tolist())}")
                st.write(f"**Sample data:**")
                st.dataframe(data['analysis_data'].head(5), use_container_width=True)
            else:
                st.warning("⚠️ No analysis data loaded!")
            
            # Calculate summary statistics from combined data
            data['summary_stats'] = calculate_summary_statistics(data['analysis_data'])
            
            # Load timeline data for heatmaps
            data['timeline_data'] = load_blob_timeline_data(
                network,
                config['start_datetime'],
                config['end_datetime'],
                selected_clients,
                cluster
            )
            
            # Add validation info
            data['validation'] = validation
            
            logger.info(f"Loaded blob mempool analysis data for {len(selected_clients)} clients")
            
            return data
    
    except Exception as e:
        logger.error(f"Error loading analysis data: {e}")
        st.error(f"Failed to load analysis data: {str(e)}")
        return {}


def render_summary_metrics(data: Dict[str, Any]):
    """Render summary metrics cards."""
    if 'summary_stats' not in data or data['summary_stats'].empty:
        st.warning("No summary statistics available")
        return
    
    summary_df = data['summary_stats']
    metrics = create_summary_metrics_cards(summary_df)
    
    # Create columns for metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            label="Total Clients",
            value=metrics['total_clients'],
            help="Number of clients analyzed"
        )
    
    with col2:
        st.metric(
            label="Overall Match Rate",
            value=f"{metrics['avg_match_rate']:.1f}%",
            help="Percentage of canonical blobs found in mempool"
        )
    
    with col3:
        st.metric(
            label="Total Canonical Blobs",
            value=f"{metrics['total_canonical_blobs']:,}",
            help="Total blobs included in canonical blocks"
        )
    
    with col4:
        st.metric(
            label="Total Mempool Blobs",
            value=f"{metrics['total_mempool_blobs']:,}",
            help="Total blob transactions observed in mempool"
        )
    
    # Additional metrics in expandable section
    with st.expander("Additional Metrics", expanded=False):
        col5, col6, col7 = st.columns(3)
        
        with col5:
            st.metric(
                label="Slots Analyzed",
                value=f"{metrics['total_slots']:,}",
                help="Total number of slots with data"
            )
        
        with col6:
            st.metric(
                label="Best Performing Client",
                value=metrics['best_client'],
                help="Client with highest match percentage"
            )
        
        with col7:
            st.metric(
                label="Lowest Performing Client",
                value=metrics['worst_client'],
                help="Client with lowest match percentage"
            )


def render_visualizations(data: Dict[str, Any], config: Dict[str, Any]):
    """Render visualizations based on view mode and chart type."""
    
    if 'combined_analysis' not in data or data['combined_analysis'].empty:
        st.warning("No analysis data available for visualization")
        return
    
    df = data['combined_analysis']
    
    # Apply filters
    if config.get('filter_zero_blobs', True):
        df = df[df['canonical_blob_count'] > 0]
    
    if df.empty:
        st.warning("No data remaining after applying filters")
        return
    
    analysis_type = config.get('analysis_type', 'overview')
    chart_type = config.get('chart_type', 'line_chart')
    
    if analysis_type == 'overview':
        render_overview_view(df, config)
    elif analysis_type == 'detailed':
        render_detailed_view(df, config)
    elif analysis_type == 'comparison':
        render_comparison_view(df, data.get('summary_stats', pd.DataFrame()), config)


def render_overview_view(df: pd.DataFrame, config: Dict[str, Any]):
    """Render overview visualizations."""
    
    st.subheader("📈 Blob Count Timeline")
    
    # Main timeline chart
    timeline_fig = create_blob_count_timeline(df, config.get('selected_clients'))
    st.plotly_chart(timeline_fig, use_container_width=True)
    
    # Two column layout for additional charts
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("💯 Match Percentage")
        match_fig = create_match_percentage_chart(df, config.get('selected_clients'))
        st.plotly_chart(match_fig, use_container_width=True)
    
    with col2:
        st.subheader("🔗 Blob Correlation")
        correlation_fig = create_blob_correlation_scatter(df)
        st.plotly_chart(correlation_fig, use_container_width=True)
    
    # Raw data section for overview
    st.markdown("---")
    st.subheader("🔍 Raw Data Explorer")
    
    show_raw_overview = st.checkbox(
        "Show Raw Data Overview",
        value=False,
        help="Display raw analysis data for debugging and inspection"
    )
    
    if show_raw_overview:
        if not df.empty:
            st.markdown("#### Raw Analysis Data Sample")
            st.write(f"**Total Records:** {len(df):,}")
            st.write(f"**Time Range:** {df['slot_start_date_time'].min()} to {df['slot_start_date_time'].max()}")
            
            # Show key columns
            key_cols = [
                'slot', 'slot_start_date_time', 'client_name',
                'canonical_blob_count', 'mempool_blob_count', 'matching_blob_count', 'match_percentage'
            ]
            
            available_key_cols = [col for col in key_cols if col in df.columns]
            st.dataframe(
                df[available_key_cols].head(50),
                use_container_width=True,
                hide_index=True
            )
            
            # Quick stats
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Unique Slots", f"{df['slot'].nunique():,}")
                st.metric("Unique Clients", f"{df['client_name'].nunique():,}")
            with col2:
                st.metric("Avg Blobs/Slot", f"{df['canonical_blob_count'].mean():.1f}")
                st.metric("Avg Mempool Blobs", f"{df['mempool_blob_count'].mean():.1f}")
            with col3:
                st.metric("Avg Match Rate", f"{df['match_percentage'].mean():.1f}%")
                st.metric("Max Match Rate", f"{df['match_percentage'].max():.1f}%")
        else:
            st.info("No data available to display. Try adjusting your filters or time range.")


def render_detailed_view(df: pd.DataFrame, config: Dict[str, Any]):
    """Render detailed visualizations."""
    
    # Dual-axis chart combining counts and percentages
    st.subheader("📊 Detailed Analysis: Counts and Match Rates")
    dual_fig = create_dual_axis_chart(df)
    st.plotly_chart(dual_fig, use_container_width=True)
    
    # Blob gas analysis if enabled
    if config.get('show_blob_gas_analysis', False):
        st.subheader("⛽ Blob Gas Analysis")
        gas_fig = create_blob_gas_analysis_chart(df)
        st.plotly_chart(gas_fig, use_container_width=True)
    
    # Blob size analysis if enabled
    if config.get('show_blob_size_analysis', False):
        st.subheader("📏 Blob Size Analysis")
        size_fig = create_blob_size_analysis_chart(df)
        st.plotly_chart(size_fig, use_container_width=True)
    
    # Individual client breakdown
    selected_clients = config.get('blob_mempool_client_filter', [])
    
    if len(selected_clients) > 1:
        st.subheader("👥 Individual Client Performance")
        
        for client in selected_clients:
            with st.expander(f"Client: {client}", expanded=False):
                client_data = df[df['client_name'] == client]
                
                if not client_data.empty:
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        client_timeline = create_blob_count_timeline(client_data, [client])
                        st.plotly_chart(client_timeline, use_container_width=True)
                    
                    with col2:
                        client_match = create_match_percentage_chart(client_data, [client])
                        st.plotly_chart(client_match, use_container_width=True)
                    
                    # Client statistics
                    stats = client_data.agg({
                        'canonical_blob_count': 'sum',
                        'mempool_blob_count': 'sum',
                        'matching_blob_count': 'sum',
                        'match_percentage': 'mean'
                    })
                    
                    col3, col4, col5, col6 = st.columns(4)
                    with col3:
                        st.metric("Canonical Blobs", f"{int(stats['canonical_blob_count']):,}")
                    with col4:
                        st.metric("Mempool Blobs", f"{int(stats['mempool_blob_count']):,}")
                    with col5:
                        st.metric("Matching Blobs", f"{int(stats['matching_blob_count']):,}")
                    with col6:
                        st.metric("Avg Match %", f"{stats['match_percentage']:.1f}%")
                else:
                    st.info(f"No data available for client {client}")


def render_comparison_view(df: pd.DataFrame, summary_df: pd.DataFrame, config: Dict[str, Any]):
    """Render comparison visualizations."""
    
    if summary_df.empty:
        st.warning("No summary data available for comparison")
        return
    
    metric_type = config.get('metric_type', 'match_percentage')
    
    # Map metric types to summary DataFrame columns
    metric_mapping = {
        'match_percentage': 'avg_match_percentage',
        'blob_count': 'total_canonical_blobs',
        'mempool_tx_count': 'total_mempool_blobs',
        'inclusion_efficiency': 'avg_match_percentage'  # Use match percentage as proxy
    }
    
    summary_metric = metric_mapping.get(metric_type, 'avg_match_percentage')
    
    st.subheader(f"🏆 Client Comparison: {metric_type.replace('_', ' ').title()}")
    
    # Bar chart comparison
    comparison_fig = create_client_comparison_bar(summary_df, summary_metric)
    st.plotly_chart(comparison_fig, use_container_width=True)
    
    # Heatmap if timeline data available
    if 'timeline_data' in st.session_state.blob_mempool_analysis_data:
        timeline_data = st.session_state.blob_mempool_analysis_data['timeline_data']
        if not timeline_data.empty:
            st.subheader("🔥 Hourly Performance Heatmap")
            heatmap_fig = create_hourly_heatmap(timeline_data, summary_metric)
            st.plotly_chart(heatmap_fig, use_container_width=True)
    
    # Summary table
    st.subheader("📋 Client Performance Summary")
    
    # Format summary table for display
    display_df = summary_df.copy()
    
    # Round percentage columns
    percentage_cols = [col for col in display_df.columns if 'percentage' in col]
    for col in percentage_cols:
        display_df[col] = display_df[col].round(1)
    
    # Format large numbers
    large_number_cols = ['total_canonical_blobs', 'total_mempool_blobs', 'total_matching_blobs']
    for col in large_number_cols:
        if col in display_df.columns:
            display_df[col] = display_df[col].astype(int)
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )
    
    # Raw data section
    st.markdown("---")
    st.subheader("🔍 Raw Data Explorer")
    
    col1, col2 = st.columns(2)
    
    with col1:
        show_raw_data = st.checkbox(
            "Show Raw Analysis Data",
            value=False,
            help="Display the raw combined analysis data for debugging and detailed inspection"
        )
    
    with col2:
        show_canonical_data = st.checkbox(
            "Show Canonical Blob Data",
            value=False,
            help="Display the canonical blob data from beacon blocks"
        )
    
    if show_raw_data:
        if not data.empty:
            st.markdown("#### Raw Combined Analysis Data")
            st.write(f"**Total Records:** {len(data):,}")
            st.write(f"**Columns:** {', '.join(data.columns.tolist())}")
            
            # Show sample of raw data
            raw_display_cols = [
                'slot', 'slot_start_date_time', 'client_name', 
                'canonical_blob_count', 'mempool_blob_count', 'matching_blob_count', 
                'match_percentage', 'avg_blob_gas', 'avg_blob_gas_fee_cap'
            ]
            
            available_cols = [col for col in raw_display_cols if col in data.columns]
            st.dataframe(
                data[available_cols].head(100),
                use_container_width=True,
                hide_index=True
            )
            
            # Show data summary
            st.markdown("#### Data Summary")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Slots", f"{data['slot'].nunique():,}")
                st.metric("Total Clients", f"{data['client_name'].nunique():,}")
            
            with col2:
                st.metric("Avg Canonical Blobs/Slot", f"{data['canonical_blob_count'].mean():.1f}")
                st.metric("Avg Mempool Blobs/Client", f"{data['mempool_blob_count'].mean():.1f}")
            
            with col3:
                st.metric("Avg Match %", f"{data['match_percentage'].mean():.1f}%")
                st.metric("Slots with Blobs", f"{(data['canonical_blob_count'] > 0).sum():,}")
        else:
            st.info("No data available to display. Try adjusting your filters or time range.")
    
    if show_canonical_data:
        if not data.empty:
            st.markdown("#### Canonical Blob Data by Slot")
            
            # Group by slot to show canonical data
            canonical_summary = data.groupby(['slot', 'slot_start_date_time']).agg({
                'canonical_blob_count': 'first',
                'canonical_blob_hashes': 'first',
                'block_root': 'first',
                'proposer_index': 'first'
            }).reset_index()
            
            st.write(f"**Slots with Blob Data:** {len(canonical_summary[canonical_summary['canonical_blob_count'] > 0]):,}")
            st.write(f"**Total Slots:** {len(canonical_summary):,}")
            
            # Show slots with blobs
            slots_with_blobs = canonical_summary[canonical_summary['canonical_blob_count'] > 0].copy()
            if not slots_with_blobs.empty:
                st.dataframe(
                    slots_with_blobs.head(50),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No slots with blob data found in the selected time range")
        else:
            st.info("No data available to display. Try adjusting your filters or time range.")


def render_data_quality_info(data: Dict[str, Any]):
    """Render data quality and availability information."""
    
    if 'validation' not in data:
        return
    
    validation = data['validation']
    
    with st.expander("Data Quality Information", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Data Availability")
            st.write(f"**Canonical Data Available:** {'✅' if validation['has_canonical_data'] else '❌'}")
            st.write(f"**Mempool Data Available:** {'✅' if validation['has_mempool_data'] else '❌'}")
            st.write(f"**Eligible Slots:** {validation['eligible_slots']:,}")
            st.write(f"**Available Clients:** {validation['available_clients']}")
        
        with col2:
            st.subheader("Data Quality Notes")
            if validation['errors']:
                for error in validation['errors']:
                    st.error(error)
            else:
                st.success("All data quality checks passed")
            
            st.info("Note: Mempool data is matched within 24 seconds before slot start time")


def calculate_summary_statistics(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate summary statistics from combined analysis data."""
    
    if df.empty:
        return pd.DataFrame()
    
    # Group by client to calculate summary statistics
    summary_stats = df.groupby('client_name').agg({
        'slot': 'nunique',  # Number of unique slots
        'canonical_blob_count': 'sum',  # Total canonical blobs
        'mempool_blob_count': 'sum',  # Total mempool blobs
        'matching_blob_count': 'sum',  # Total matching blobs
        'match_percentage': 'mean',  # Average match percentage
        'avg_blob_gas': 'mean',  # Average blob gas
        'avg_blob_gas_fee_cap': 'mean',  # Average blob gas fee cap
        'total_blob_sidecars_size': 'sum'  # Total blob sidecar size
    }).reset_index()
    
    # Rename columns for consistency
    summary_stats.columns = [
        'client_name',
        'slots_with_data',
        'total_canonical_blobs',
        'total_mempool_blobs', 
        'total_matching_blobs',
        'avg_match_percentage',
        'avg_blob_gas',
        'avg_blob_gas_fee_cap',
        'total_blob_sidecars_size'
    ]
    
    # Calculate additional metrics
    summary_stats['match_percentage'] = summary_stats['avg_match_percentage'].round(1)
    summary_stats['blob_efficiency'] = (summary_stats['total_matching_blobs'] / 
                                      summary_stats['total_canonical_blobs'] * 100).round(1)
    summary_stats['blob_efficiency'] = summary_stats['blob_efficiency'].fillna(0)
    
    # Sort by match percentage descending
    summary_stats = summary_stats.sort_values('match_percentage', ascending=False)
    
    return summary_stats


def render_blob_mempool_dashboard():
    """Main dashboard rendering function."""
    st.title("🧊 Blob Mempool Analysis")
    
    # Initialize session state
    initialize_session_state()
    
    # Render header for cluster/network selection
    cluster, network = render_global_header()
    
    if not cluster or not network:
        st.warning("Please select a cluster and network to begin analysis")
        return
    
    # Get configuration from sidebar
    config = render_sidebar_configuration()
    
    if not config:
        return
    
    # Main content area
    st.markdown("---")
    
    # Client filtering section on main page
    with st.expander("🖥️ Client Selection", expanded=True):
        # Create a cache key for the current configuration
        cache_key = f"{config['network']}_{config['start_date']}_{config['end_date']}_{config['cluster']}"
        
        # Check if configuration changed and clear client selection if needed
        if 'blob_mempool_last_client_cache_key' not in st.session_state:
            st.session_state.blob_mempool_last_client_cache_key = None
        
        if st.session_state.blob_mempool_last_client_cache_key != cache_key:
            # Configuration changed, reset client selection
            if 'blob_mempool_client_filter' in st.session_state:
                del st.session_state.blob_mempool_client_filter
            st.session_state.blob_mempool_last_client_cache_key = cache_key
        
        # Get unique clients for the selected time range
        with st.spinner("Loading available clients..."):
            available_clients = load_available_clients(
                network=config['network'],
                start_date=config['start_datetime'],
                end_date=config['end_datetime'],
                cluster_name=config['cluster']
            )
        
        # Client name filter - multiselect with all selected by default
        if available_clients:
            # Sort clients alphabetically for easier navigation
            available_clients = sorted(available_clients)
            
            # Show count first
            st.caption(f"Found {len(available_clients)} unique clients with blob transaction data in the selected time range")
            
            # Initialize session state for client selection if needed
            if 'blob_mempool_client_selection_override' not in st.session_state:
                st.session_state.blob_mempool_client_selection_override = None
            
            # Create columns for better layout
            col1, col2 = st.columns([4, 1])
            
            with col2:
                st.write("")  # Add spacing
                # Add select all/none buttons for convenience
                if st.button("Select All", use_container_width=True, key="select_all_btn"):
                    st.session_state.blob_mempool_client_selection_override = 'all'
                    st.rerun()
                if st.button("Clear All", use_container_width=True, key="clear_all_btn"):
                    st.session_state.blob_mempool_client_selection_override = 'none'
                    st.rerun()
            
            with col1:
                # Determine default selection based on override
                if st.session_state.blob_mempool_client_selection_override == 'all':
                    default_selection = available_clients
                    st.session_state.blob_mempool_client_selection_override = None  # Reset override
                elif st.session_state.blob_mempool_client_selection_override == 'none':
                    default_selection = []
                    st.session_state.blob_mempool_client_selection_override = None  # Reset override
                else:
                    # Use previous selection if exists, otherwise all
                    # But filter to only include clients that still exist
                    previous_selection = st.session_state.get('blob_mempool_client_filter', available_clients)
                    if isinstance(previous_selection, list):
                        # Keep only clients that are still available
                        default_selection = [c for c in previous_selection if c in available_clients]
                        # If nothing was kept, default to all
                        if not default_selection:
                            default_selection = available_clients
                    else:
                        default_selection = available_clients
                
                selected_clients = st.multiselect(
                    "Filter by Client Name",
                    options=available_clients,
                    default=default_selection,
                    help="Select which client names to include in the analysis. Deselect clients to exclude them.",
                    key="client_filter"
                )
            
            # Show count of selected clients
            if len(selected_clients) == len(available_clients):
                st.success(f"✅ All {len(available_clients)} clients selected")
            elif len(selected_clients) == 0:
                st.warning("⚠️ No clients selected - please select at least one client")
            else:
                st.info(f"📊 Selected {len(selected_clients)} of {len(available_clients)} clients")
        else:
            selected_clients = []
            st.warning("No clients found for the selected time range")
    
    # Add client filter to config
    config['blob_mempool_client_filter'] = selected_clients if selected_clients else None
    
    st.markdown("---")
    
    # Process data if button clicked
    if config.get('load_data', False):
        with st.spinner("🔄 Loading blob mempool analysis data..."):
            try:
                # First validate data availability
                validation = validate_data_availability(
                    network=config['network'],
                    start_date=config['start_datetime'],
                    end_date=config['end_datetime'],
                    cluster_name=config['cluster']
                )
                
                if validation['errors']:
                    for error in validation['errors']:
                        st.error(error)
                    return
                
                # Show data stats
                st.info(f"Found {validation['eligible_slots']:,} slots with {validation['available_clients']} unique clients")
                
                # Load analysis data
                data = load_analysis_data(config, config['cluster'], config['network'], selected_clients)
                
                if data:
                    st.session_state.blob_mempool_analysis_data = data
                    st.session_state.blob_mempool_data_loaded = True
                    st.session_state.blob_mempool_last_config = config
                    st.success("✅ Analysis data loaded successfully!")
                else:
                    st.warning("No data found for the selected time range")
                    return
                
            except Exception as e:
                logger.error(f"Error loading data: {e}")
                st.error(f"Failed to load analysis data: {str(e)}")
                return
    
    # Check if we have data to display
    if not st.session_state.blob_mempool_data_loaded:
        st.info("👆 Click 'Load Analysis Data' in the sidebar to begin analysis")
        return
    
    data = st.session_state.blob_mempool_analysis_data
    
    # Display current time range
    st.info(f"📅 Analyzing period: {config['start_date']} to {config['end_date']}")
    
    # Show summary metrics if enabled
    if config.get('show_summary_stats', True):
        render_summary_metrics(data)
        st.markdown("---")
    
    # Render main visualizations
    render_visualizations(data, config)
    
    # Show data quality info if enabled
    if config.get('show_data_quality', False):
        st.markdown("---")
        render_data_quality_info(data)
    
    # Show help information
    with st.expander("ℹ️ About Blob Mempool Analysis", expanded=False):
        st.markdown("""
        ### What is Blob Mempool Analysis?
        This dashboard analyzes blob transactions in the mempool compared to blobs included in canonical beacon blocks,
        providing insights into mempool presence and inclusion rates across different Ethereum clients.
        
        ### Key Metrics:
        - **Canonical Blob Count**: Number of blobs in canonical beacon blocks per slot
        - **Mempool Blob Count**: Number of blob transactions observed in mempool (type 3 transactions)
        - **Matching Blobs**: Blobs that were present in mempool before inclusion
        - **Match Percentage**: Ratio of matching blobs to canonical blobs
        
        ### Understanding the Charts:
        - **Overview**: Shows timeline charts of blob counts and match percentages
        - **Detailed**: Individual client breakdown with performance metrics
        - **Comparison**: Side-by-side client performance analysis
        - **Correlation**: Relationship between canonical and mempool blob counts
        - **Heatmaps**: Hourly patterns by client and time
        
        ### Data Sources:
        - **Canonical Data**: `beacon_api_eth_v2_beacon_block` + `beacon_api_eth_v1_events_blob_sidecar`
        - **Mempool Data**: `mempool_transaction` table (filtered for type 3 blob transactions)
        - **Time Window**: Mempool transactions matched within 24 seconds before slot start time
        """)


def main():
    """Entry point for the dashboard."""
    render_blob_mempool_dashboard()


if __name__ == "__main__":
    main()
