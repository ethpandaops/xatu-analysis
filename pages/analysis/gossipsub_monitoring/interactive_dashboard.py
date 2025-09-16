"""
Interactive dashboard for Gossipsub Monitoring.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import shared components
from shared.ui_components import apply_ethPandaOps_styling
from shared.header import render_global_header, get_global_cluster, get_global_network

# Import local modules
from config_utils import (
    get_default_time_ranges,
    get_supported_networks,
    get_data_source_options,
    get_analysis_config
)
from data_loaders_reverse import (
    load_gossipsub_data_reverse as load_gossipsub_data,
    get_latest_slot_with_ihave as get_latest_slot,
    get_available_slots_with_ihave as get_available_slots,
    calculate_cdf_by_continent,
    calculate_cdf_by_slot,
    calculate_percentiles_by_continent,
    calculate_percentiles_by_slot,
    load_comparison_data
)
from plot_generators import (
    create_continent_cdf_plot,
    create_slot_cdf_plot,
    create_percentile_comparison_chart,
    create_peer_distribution_map,
    create_time_series_analysis
)


def main():
    """Main dashboard function."""
    # Render the global header
    render_global_header()
    
    # Apply consistent styling
    apply_ethPandaOps_styling()
    
    # Initialize session state
    if 'gossipsub_data_loaded' not in st.session_state:
        st.session_state.gossipsub_data_loaded = False
    if 'gossipsub_data' not in st.session_state:
        st.session_state.gossipsub_data = None
    if 'gossipsub_metrics' not in st.session_state:
        st.session_state.gossipsub_metrics = None
    
    # Header
    st.markdown('<h1 class="main-header">🌐 Gossipsub Monitoring</h1>', unsafe_allow_html=True)
    st.markdown("""
    <div class="header-description">
    Monitor Ethereum block propagation across the global P2P network. Analyze how quickly blocks spread 
    through gossipsub and track performance differences across continents and peer nodes.
    </div>
    """, unsafe_allow_html=True)
    
    # Get global cluster and network from header
    cluster = get_global_cluster()
    network = get_global_network()
    
    if not cluster or not network:
        st.error("Please select a cluster and network from the header above")
        return
    
    # Sidebar configuration
    st.sidebar.header("⚙️ Configuration")
    
    # Analysis mode selection
    st.sidebar.subheader("🎯 Analysis Mode")
    analysis_mode = st.sidebar.radio(
        "Select Analysis Type",
        ["Single Slot", "Time Range"],
        index=0,
        help="Choose between analyzing a single slot or a time range"
    )
    
    # Message type selection
    st.sidebar.subheader("📬 Message Type")
    message_type = st.sidebar.radio(
        "Select Message Type",
        ["IHAVE", "IDONTWANT", "COMBINED", "COMPARISON"],
        index=0,
        help="Choose which control messages to analyze"
    )
    
    # Visualization mode selection  
    st.sidebar.subheader("📊 Visualization Mode")
    viz_mode = st.sidebar.radio(
        "CDF Grouping",
        ["By Continent", "By Slot"],
        index=0,
        help="Group CDF data by continent (all slots) or by individual slot"
    )
    
    # Latency adjustment option
    st.sidebar.subheader("🔧 Advanced Options")
    subtract_latency = st.sidebar.checkbox(
        "Subtract Network Latency",
        value=True,
        help="Adjust propagation times by subtracting one-way network latency (RTT/2) between the observer and peer. This provides a more accurate measure of actual propagation time."
    )
    
    if analysis_mode == "Single Slot":
        # Get latest slot for reference (from 15 minutes ago due to data delay)
        with st.spinner("Getting latest available slot..."):
            latest_slot = get_latest_slot(network, cluster)
        
        st.sidebar.subheader("🎰 Slot Selection")
        
        if latest_slot:
            st.sidebar.info(f"Latest slot: {latest_slot:,}")
        
        # Simple slot input
        if not latest_slot:
            st.sidebar.error("Cannot determine latest slot. Please check database connection.")
            return
        
        target_slot = st.sidebar.number_input(
            "Enter slot number",
            min_value=1,
            max_value=latest_slot,
            value=latest_slot,
            step=1,
            help="Enter the specific slot number you want to analyze"
        )
        
        # For single slot, use current time as reference
        slot_time = datetime.now(timezone.utc)
        start_time = slot_time - timedelta(hours=1)
        end_time = slot_time
        
    else:  # Time Range mode
        st.sidebar.subheader("📅 Time Range")
        
        # Quick period selection (like PeerDAS)
        time_options = {
            "Last 1 Hour": timedelta(hours=1),
            "Last 6 Hours": timedelta(hours=6),
            "Last 12 Hours": timedelta(hours=12),
            "Last 24 Hours": timedelta(hours=24),
            "Last 3 Days": timedelta(days=3),
            "Custom": None
        }
        
        selected_period = st.sidebar.selectbox(
            "Quick Period Selection",
            options=list(time_options.keys()),
            index=0,  # Default to "Last 1 Hour"
            help="Select a predefined period or choose Custom for manual selection"
        )
        
        # Set dates based on selection
        if selected_period != "Custom":
            time_delta = time_options[selected_period]
            end_time = datetime.now(timezone.utc)
            start_time = end_time - time_delta
            
            # Show the selected range (read-only)
            col1, col2 = st.sidebar.columns(2)
            with col1:
                st.date_input(
                    "Start Date",
                    value=start_time.date(),
                    disabled=True,
                    key="start_date_display"
                )
            with col2:
                st.date_input(
                    "End Date",
                    value=end_time.date(),
                    disabled=True,
                    key="end_date_display"
                )
        else:
            # Custom date selection
            default_end = datetime.now(timezone.utc)
            default_start = default_end - timedelta(hours=1)
            
            col1, col2 = st.sidebar.columns(2)
            with col1:
                start_date = st.date_input(
                    "Start Date",
                    value=default_start.date(),
                    max_value=datetime.now().date(),
                    key='custom_start_date'
                )
                start_time_input = st.time_input(
                    "Start Time (UTC)",
                    value=default_start.time(),
                    key='custom_start_time'
                )
            with col2:
                end_date = st.date_input(
                    "End Date",
                    value=default_end.date(),
                    max_value=datetime.now().date(),
                    key='custom_end_date'
                )
                end_time_input = st.time_input(
                    "End Time (UTC)",
                    value=default_end.time(),
                    key='custom_end_time'
                )
            
            start_time = datetime.combine(start_date, start_time_input).replace(tzinfo=timezone.utc)
            end_time = datetime.combine(end_date, end_time_input).replace(tzinfo=timezone.utc)
        
        target_slot = None
    
    # Analysis settings
    st.sidebar.subheader("⚙️ Analysis Settings")
    
    config = get_analysis_config()
    
    min_peers = st.sidebar.slider(
        "Minimum peers per continent",
        min_value=1,
        max_value=20,
        value=config['min_peers_for_analysis'],
        help="Minimum number of peers required for continent to appear in analysis"
    )
    
    # Show slot limit for time range mode
    if analysis_mode == "Time Range":
        slot_limit = st.sidebar.slider(
            "Maximum slots to analyze",
            min_value=10,
            max_value=500,
            value=100,
            step=10,
            help="Limit the number of slots to analyze for performance"
        )
    else:
        slot_limit = 1
    
    # Data loading section
    st.sidebar.markdown("---")
    
    col1, col2 = st.sidebar.columns([2, 1])
    with col1:
        load_button = st.button("🚀 Load Data", type="primary", use_container_width=True)
    with col2:
        clear_cache_button = st.button("🗑️ Clear", type="secondary", use_container_width=True)
    
    if clear_cache_button:
        st.session_state.gossipsub_data_loaded = False
        st.session_state.gossipsub_data = None
        st.session_state.gossipsub_metrics = None
        st.cache_data.clear()
        st.sidebar.success("✅ Cache cleared successfully!")
        st.rerun()
    
    # Check if viz_mode changed and data needs recalculation
    if (st.session_state.gossipsub_data_loaded and 
        st.session_state.get('viz_mode', 'By Continent') != viz_mode):
        # Recalculate metrics for the new viz_mode
        data = st.session_state.gossipsub_data
        with st.spinner("Recalculating metrics for new visualization mode..."):
            if viz_mode == "By Continent":
                cdf_data, peer_counts = calculate_cdf_by_continent(data, return_peer_counts=True)
                percentiles = calculate_percentiles_by_continent(data)
                grouping_count = len(cdf_data)
                grouping_type = "continents"
            else:  # By Slot
                cdf_data, peer_counts = calculate_cdf_by_slot(data, return_peer_counts=True)
                percentiles = calculate_percentiles_by_slot(data)
                grouping_count = len(cdf_data)
                grouping_type = "slots"
            
            metrics = {
                'cdf_data': cdf_data,
                'peer_counts': peer_counts,
                'percentiles': percentiles,
                'total_peers': data['peer_id'].nunique() if 'peer_id' in data.columns else 0,
                'total_slots': data['slot'].nunique() if 'slot' in data.columns else 0,
                'continents': data['continent'].nunique() if 'continent' in data.columns else 0,
                'grouping_count': grouping_count,
                'grouping_type': grouping_type
            }
            
            st.session_state.gossipsub_metrics = metrics
            st.session_state.viz_mode = viz_mode
            st.success(f"✅ Recalculated metrics for {grouping_type} view")
    
    if load_button:
        with st.spinner("Loading gossipsub data..."):
            try:
                # Handle comparison mode separately
                if message_type == "COMPARISON":
                    # Load both IHAVE and IDONTWANT for comparison
                    ihave_data, idontwant_data = load_comparison_data(
                        start_time=start_time,
                        end_time=end_time,
                        network=network,
                        cluster=cluster,
                        slot_limit=slot_limit,
                        subtract_latency=subtract_latency
                    )
                    
                    if ihave_data.empty and idontwant_data.empty:
                        st.error("No data found for comparison")
                        return
                    
                    # Store comparison data separately
                    st.session_state.comparison_mode = True
                    st.session_state.ihave_data = ihave_data
                    st.session_state.idontwant_data = idontwant_data
                    st.session_state.gossipsub_data_loaded = True
                    
                    st.success(f"✅ Loaded {len(ihave_data)} IHAVE and {len(idontwant_data)} IDONTWANT records")
                    
                else:
                    # Load single message type data
                    st.session_state.comparison_mode = False
                    
                    if analysis_mode == "Single Slot":
                        if target_slot is None:
                            st.error("Please specify a valid slot number")
                            return
                            
                        data = load_gossipsub_data(
                            start_time=start_time,
                            end_time=end_time,
                            network=network,
                            cluster=cluster,
                            target_slot=target_slot,
                            slot_limit=slot_limit,
                            message_type=message_type,
                            subtract_latency=subtract_latency
                        )
                    else:
                        data = load_gossipsub_data(
                            start_time=start_time,
                            end_time=end_time,
                            network=network,
                            cluster=cluster,
                            target_slot=None,
                            slot_limit=slot_limit,
                            message_type=message_type,
                            subtract_latency=subtract_latency
                        )
                    
                    if data.empty:
                        if analysis_mode == "Single Slot":
                            st.error(f"No {message_type} data found for slot {target_slot} in network {network}.")
                        else:
                            st.error(f"No {message_type} data found for the selected time range and network.")
                        return
                    
                    # Calculate metrics based on visualization mode
                    with st.spinner("Computing metrics..."):
                        if viz_mode == "By Continent":
                            cdf_data, peer_counts = calculate_cdf_by_continent(data, return_peer_counts=True)
                            percentiles = calculate_percentiles_by_continent(data)
                            grouping_count = len(cdf_data)
                            grouping_type = "continents"
                        else:  # By Slot
                            cdf_data, peer_counts = calculate_cdf_by_slot(data, return_peer_counts=True)
                            percentiles = calculate_percentiles_by_slot(data)
                            grouping_count = len(cdf_data)
                            grouping_type = "slots"
                        
                        metrics = {
                            'cdf_data': cdf_data,
                            'peer_counts': peer_counts,
                            'percentiles': percentiles,
                            'total_peers': data['peer_id'].nunique() if 'peer_id' in data.columns else 0,
                            'total_slots': data['slot'].nunique() if 'slot' in data.columns else 0,
                            'continents': data['continent'].nunique() if 'continent' in data.columns else 0,
                            'grouping_count': grouping_count,
                            'grouping_type': grouping_type,
                            'message_type': message_type
                        }
                    
                    # Store in session state
                    st.session_state.gossipsub_data = data
                    st.session_state.gossipsub_metrics = metrics
                    st.session_state.gossipsub_data_loaded = True
                    st.session_state.viz_mode = viz_mode
                    
                    st.success(f"✅ Loaded {len(data)} {message_type} records from {metrics['total_slots']} slots with {metrics['total_peers']} unique peers")
                
            except Exception as e:
                st.error(f"Error loading data: {str(e)}")
                logger.error(f"Error in data loading: {e}", exc_info=True)
                st.session_state.gossipsub_data_loaded = False
    
    # Display data quality information
    if st.session_state.gossipsub_data_loaded and st.session_state.gossipsub_metrics:
        metrics = st.session_state.gossipsub_metrics
        
        with st.sidebar.expander("📊 Data Quality", expanded=True):
            st.write(f"**Total Peers**: {metrics['total_peers']:,}")
            st.write(f"**Total Slots**: {metrics['total_slots']:,}")
            st.write(f"**Continents**: {metrics.get('continents', 'N/A')}")
            # Handle backward compatibility for older metrics
            if 'grouping_count' in metrics and 'grouping_type' in metrics:
                st.write(f"**Groups in CDF**: {metrics['grouping_count']} {metrics['grouping_type']}")
            elif 'cdf_data' in metrics:
                # Fallback for older metrics structure
                group_count = len(metrics['cdf_data'])
                group_type = "groups"
                st.write(f"**Groups in CDF**: {group_count} {group_type}")
            st.write(f"**Network**: {network}")
            st.write(f"**Cluster**: {cluster}")
    
    # Main dashboard content
    if st.session_state.gossipsub_data_loaded:
        if st.session_state.get('comparison_mode', False):
            # Render comparison dashboard
            render_comparison_dashboard(
                st.session_state.ihave_data,
                st.session_state.idontwant_data,
                target_slot if analysis_mode == "Single Slot" else None,
                viz_mode
            )
        elif st.session_state.gossipsub_metrics:
            # Render regular dashboard
            viz_mode = st.session_state.get('viz_mode', 'By Continent')
            render_analysis_dashboard(
                st.session_state.gossipsub_data,
                st.session_state.gossipsub_metrics,
                target_slot if analysis_mode == "Single Slot" else None,
                viz_mode
            )
    else:
        render_welcome_screen()


def render_analysis_dashboard(data: pd.DataFrame, metrics: Dict[str, Any], slot: Optional[int] = None, viz_mode: str = "By Continent"):
    """Render the main analysis dashboard."""
    
    # Main CDF Analysis
    if viz_mode == "By Continent":
        st.subheader("📈 Propagation CDF by Continent")
    else:
        st.subheader("📈 Propagation CDF by Slot")
    
    if slot:
        st.info(f"Analyzing slot {slot:,}")
    
    if metrics['cdf_data']:
        # Create and display CDF plot based on viz_mode
        peer_counts = metrics.get('peer_counts', {})
        if viz_mode == "By Continent":
            cdf_fig = create_continent_cdf_plot(metrics['cdf_data'], slot, peer_counts=peer_counts)
        else:  # By Slot
            cdf_fig = create_slot_cdf_plot(metrics['cdf_data'], peer_counts=peer_counts)
        
        st.plotly_chart(cdf_fig, use_container_width=True)
        
        # Show percentile comparison
        if isinstance(metrics['percentiles'], pd.DataFrame) and not metrics['percentiles'].empty:
            if viz_mode == "By Continent":
                st.subheader("📊 Percentile Comparison by Continent")
            else:
                st.subheader("📊 Percentile Comparison by Slot")
            
            percentile_fig = create_percentile_comparison_chart(metrics['percentiles'], slot)
            st.plotly_chart(percentile_fig, use_container_width=True)
        
        # Show metrics summary
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Peers", f"{metrics['total_peers']:,}")
        
        with col2:
            st.metric("Continents", metrics.get('continents', data['continent'].nunique() if 'continent' in data.columns else 0))
        
        with col3:
            if 'propagation_delay_ms' in data.columns:
                median_delay = data['propagation_delay_ms'].median() / 1000.0
                st.metric("Global Median", f"{median_delay:.2f}s")
        
        with col4:
            if 'propagation_delay_ms' in data.columns:
                p90_delay = data['propagation_delay_ms'].quantile(0.9) / 1000.0
                st.metric("Global P90", f"{p90_delay:.2f}s")
        
        # Geographic distribution
        st.divider()
        st.subheader("🗺️ Geographic Distribution")
        geo_fig = create_peer_distribution_map(data, slot)
        st.plotly_chart(geo_fig, use_container_width=True)
        
        # Time series analysis (if multiple slots)
        if metrics['total_slots'] > 1:
            st.divider()
            st.subheader("📉 Time Series Analysis")
            ts_fig = create_time_series_analysis(data)
            st.plotly_chart(ts_fig, use_container_width=True)
        
        # Detailed statistics
        with st.expander("📊 Detailed Statistics"):
            if not metrics['percentiles'].empty:
                st.markdown("### Percentiles by Continent (milliseconds)")
                
                # Format percentiles table
                display_df = metrics['percentiles'].copy()
                for col in ['p50', 'p75', 'p90', 'p95', 'p99']:
                    if col in display_df.columns:
                        display_df[col] = display_df[col].round(0).astype(int)
                
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            # Show peer distribution
            if 'continent' in data.columns:
                st.markdown("### Peer Distribution by Continent")
                continent_counts = data.groupby('continent')['peer_id'].nunique().sort_values(ascending=False)
                
                col1, col2 = st.columns(2)
                with col1:
                    st.dataframe(
                        continent_counts.reset_index().rename(columns={'peer_id': 'peer_count'}),
                        use_container_width=True,
                        hide_index=True
                    )
                
                with col2:
                    # Show percentage distribution
                    total_peers = continent_counts.sum()
                    continent_pct = (continent_counts / total_peers * 100).round(1)
                    st.dataframe(
                        continent_pct.reset_index().rename(columns={'peer_id': 'percentage'}),
                        use_container_width=True,
                        hide_index=True
                    )
        
        # Raw data preview
        with st.expander("🔍 Raw Data Preview"):
            st.markdown("### Sample of Gossipsub Data (first 100 rows)")
            
            # Select columns to display
            display_cols = ['slot', 'peer_id', 'continent', 'country', 'propagation_delay_ms', 
                          'ihave_time', 'block_propagation_time']
            available_cols = [col for col in display_cols if col in data.columns]
            
            sample_data = data[available_cols].head(100).copy()
            
            # Format times
            if 'propagation_delay_ms' in sample_data.columns:
                sample_data['propagation_delay_ms'] = sample_data['propagation_delay_ms'].round(0).astype(int)
            if 'ihave_time' in sample_data.columns:
                sample_data['ihave_time'] = sample_data['ihave_time'].round(0).astype(int)
            if 'block_propagation_time' in sample_data.columns:
                sample_data['block_propagation_time'] = sample_data['block_propagation_time'].round(0).astype(int)
            
            st.dataframe(sample_data, use_container_width=True, hide_index=True)
    else:
        st.warning("No data available for CDF analysis. Try adjusting your filters.")


def render_comparison_dashboard(ihave_data: pd.DataFrame, idontwant_data: pd.DataFrame, slot: Optional[int] = None, viz_mode: str = "By Continent"):
    """Render comparison dashboard for IHAVE vs IDONTWANT."""
    
    st.subheader("📊 IHAVE vs IDONTWANT Comparison")
    
    if slot:
        st.info(f"Comparing slot {slot:,}")
    
    # Create tabs for different views
    tab1, tab2, tab3, tab4 = st.tabs(["📈 Side-by-side CDFs", "📊 Metrics Comparison", "🔍 Per-Slot Analysis", "📉 Raw Data"])
    
    with tab1:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### IHAVE Messages")
            if not ihave_data.empty:
                # Calculate and show IHAVE CDF
                if viz_mode == "By Continent":
                    ihave_cdf, ihave_peer_counts = calculate_cdf_by_continent(ihave_data, return_peer_counts=True)
                    if ihave_cdf:
                        fig = create_continent_cdf_plot(ihave_cdf, slot, peer_counts=ihave_peer_counts)
                        st.plotly_chart(fig, use_container_width=True)
                else:
                    ihave_cdf, ihave_peer_counts = calculate_cdf_by_slot(ihave_data, return_peer_counts=True)
                    if ihave_cdf:
                        fig = create_slot_cdf_plot(ihave_cdf, peer_counts=ihave_peer_counts)
                        st.plotly_chart(fig, use_container_width=True)
                
                # Show metrics
                st.metric("Total IHAVE", f"{len(ihave_data):,}")
                st.metric("Unique Peers", f"{ihave_data['peer_id'].nunique():,}")
                if 'propagation_delay_ms' in ihave_data.columns:
                    st.metric("Median Delay", f"{ihave_data['propagation_delay_ms'].median()/1000:.2f}s")
            else:
                st.warning("No IHAVE data available")
        
        with col2:
            st.markdown("### IDONTWANT Messages")
            if not idontwant_data.empty:
                # Calculate and show IDONTWANT CDF
                if viz_mode == "By Continent":
                    idontwant_cdf, idontwant_peer_counts = calculate_cdf_by_continent(idontwant_data, return_peer_counts=True)
                    if idontwant_cdf:
                        fig = create_continent_cdf_plot(idontwant_cdf, slot, peer_counts=idontwant_peer_counts)
                        st.plotly_chart(fig, use_container_width=True)
                else:
                    idontwant_cdf, idontwant_peer_counts = calculate_cdf_by_slot(idontwant_data, return_peer_counts=True)
                    if idontwant_cdf:
                        fig = create_slot_cdf_plot(idontwant_cdf, peer_counts=idontwant_peer_counts)
                        st.plotly_chart(fig, use_container_width=True)
                
                # Show metrics
                st.metric("Total IDONTWANT", f"{len(idontwant_data):,}")
                st.metric("Unique Peers", f"{idontwant_data['peer_id'].nunique():,}")
                if 'propagation_delay_ms' in idontwant_data.columns:
                    st.metric("Median Delay", f"{idontwant_data['propagation_delay_ms'].median()/1000:.2f}s")
            else:
                st.warning("No IDONTWANT data available")
    
    with tab2:
        st.markdown("### Performance Metrics Comparison")
        
        # Calculate percentiles for both
        if not ihave_data.empty and not idontwant_data.empty:
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### IHAVE Percentiles")
                if viz_mode == "By Continent":
                    ihave_percentiles = calculate_percentiles_by_continent(ihave_data)
                else:
                    ihave_percentiles = calculate_percentiles_by_slot(ihave_data)
                
                if not ihave_percentiles.empty:
                    st.dataframe(ihave_percentiles, use_container_width=True)
            
            with col2:
                st.markdown("#### IDONTWANT Percentiles")
                if viz_mode == "By Continent":
                    idontwant_percentiles = calculate_percentiles_by_continent(idontwant_data)
                else:
                    idontwant_percentiles = calculate_percentiles_by_slot(idontwant_data)
                
                if not idontwant_percentiles.empty:
                    st.dataframe(idontwant_percentiles, use_container_width=True)
            
            # Create comparison chart
            st.markdown("### Median Propagation Delay Comparison")
            if 'propagation_delay_ms' in ihave_data.columns and 'propagation_delay_ms' in idontwant_data.columns:
                import plotly.graph_objects as go
                
                fig = go.Figure()
                
                # Add IHAVE line
                ihave_median = ihave_data['propagation_delay_ms'].median() / 1000
                idontwant_median = idontwant_data['propagation_delay_ms'].median() / 1000
                
                fig.add_trace(go.Bar(
                    x=['IHAVE', 'IDONTWANT'],
                    y=[ihave_median, idontwant_median],
                    text=[f'{ihave_median:.2f}s', f'{idontwant_median:.2f}s'],
                    textposition='auto',
                    marker_color=['blue', 'orange']
                ))
                
                fig.update_layout(
                    title="Median Propagation Delay Comparison",
                    yaxis_title="Delay (seconds)",
                    showlegend=False
                )
                
                st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.markdown("### Per-Slot Analysis")
        
        # Get common slots
        if not ihave_data.empty and not idontwant_data.empty and 'slot' in ihave_data.columns and 'slot' in idontwant_data.columns:
            common_slots = set(ihave_data['slot'].unique()) & set(idontwant_data['slot'].unique())
            
            if common_slots:
                st.info(f"Found {len(common_slots)} slots with both IHAVE and IDONTWANT data")
                
                # Create comparison plot
                import plotly.graph_objects as go
                from plotly.subplots import make_subplots
                
                comparison_data = []
                for slot in sorted(list(common_slots))[:20]:  # Limit to 20 slots for readability
                    ihave_slot_data = ihave_data[ihave_data['slot'] == slot]['propagation_delay_ms']
                    idontwant_slot_data = idontwant_data[idontwant_data['slot'] == slot]['propagation_delay_ms']
                    
                    comparison_data.append({
                        'slot': slot,
                        'ihave_median': ihave_slot_data.median() / 1000,
                        'idontwant_median': idontwant_slot_data.median() / 1000,
                        'ihave_count': len(ihave_slot_data),
                        'idontwant_count': len(idontwant_slot_data)
                    })
                
                comp_df = pd.DataFrame(comparison_data)
                
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=comp_df['slot'],
                    y=comp_df['ihave_median'],
                    mode='lines+markers',
                    name='IHAVE',
                    line=dict(color='blue')
                ))
                fig.add_trace(go.Scatter(
                    x=comp_df['slot'],
                    y=comp_df['idontwant_median'],
                    mode='lines+markers',
                    name='IDONTWANT',
                    line=dict(color='orange')
                ))
                
                fig.update_layout(
                    title="Median Propagation Delay by Slot",
                    xaxis_title="Slot",
                    yaxis_title="Median Delay (seconds)",
                    hovermode='x unified'
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # Show difference table
                st.markdown("### Difference Analysis")
                comp_df['difference'] = comp_df['idontwant_median'] - comp_df['ihave_median']
                comp_df['difference_pct'] = (comp_df['difference'] / comp_df['ihave_median'] * 100).round(1)
                
                st.dataframe(
                    comp_df[['slot', 'ihave_median', 'idontwant_median', 'difference', 'difference_pct']].round(3),
                    use_container_width=True
                )
            else:
                st.warning("No common slots found between IHAVE and IDONTWANT data")
        else:
            st.warning("Slot data not available for comparison")
    
    with tab4:
        st.markdown("### Raw Data Preview")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### IHAVE Data (first 100 rows)")
            if not ihave_data.empty:
                display_cols = ['slot', 'peer_id', 'propagation_delay_ms', 'continent', 'country']
                available_cols = [col for col in display_cols if col in ihave_data.columns]
                st.dataframe(ihave_data[available_cols].head(100), use_container_width=True)
        
        with col2:
            st.markdown("#### IDONTWANT Data (first 100 rows)")
            if not idontwant_data.empty:
                display_cols = ['slot', 'peer_id', 'propagation_delay_ms', 'continent', 'country']
                available_cols = [col for col in display_cols if col in idontwant_data.columns]
                st.dataframe(idontwant_data[available_cols].head(100), use_container_width=True)


def render_welcome_screen():
    """Render welcome screen when no data is loaded."""
    
    st.info("👈 Configure parameters in the sidebar and click 'Load Data' to begin analysis.")
    
    st.subheader("🎯 About Gossipsub Monitoring")
    
    st.markdown("""
    This analysis provides insights into **Ethereum block propagation** across the global P2P network:
    
    **📊 What You'll See:**
    - **Continental CDF**: Cumulative distribution of block propagation times by continent
    - **Performance Metrics**: P50/P90/P95 propagation times for each geographic region
    - **Geographic Distribution**: Visual map of peer locations and their performance
    - **Time Series**: Track propagation performance over time
    
    **🔍 Key Insights:**
    - **Network Latency**: Understand how geographic distance affects propagation
    - **Continental Performance**: Compare block propagation speeds across regions
    - **Peer Distribution**: See where Ethereum nodes are concentrated globally
    - **Network Health**: Monitor overall P2P network performance
    
    **📡 Data Sources:**
    - **libp2p_gossipsub_beacon_block**: Block propagation messages
    - **libp2p_rpc_meta_control_ihave**: IHAVE control messages from peers
    - **libp2p_rpc_meta_control_idontwant**: IDONTWANT control messages from peers
    - **libp2p_connected**: Peer connection metadata with geographic info
    
    **🆕 Message Types:**
    - **IHAVE**: Traditional gossipsub control messages indicating block availability
    - **IDONTWANT**: New optimization messages to prevent redundant transmissions
    - **COMBINED**: Merged view taking the earliest signal from either message type
    - **COMPARISON**: Side-by-side analysis of IHAVE vs IDONTWANT performance
    
    **💡 Use Cases:**
    - Monitor global network health
    - Identify geographic bottlenecks
    - Optimize node placement strategies
    - Understand P2P network topology
    """)


if __name__ == "__main__":
    main()