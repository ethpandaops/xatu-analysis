import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go
import plotly.express as px

# Import components
from config_utils import (
    get_metric_info, get_default_time_ranges, 
    get_supported_networks, get_grouping_options,
    get_data_source_options
)
from data_loaders import load_combined_analysis_data
from polars_data_loaders import load_raw_attestation_data_for_slow_analysis, load_proposer_duties_for_missed_slots
from metrics_calculators import calculate_node_cdf_metrics
from plot_generators import create_cdf_comparison_plot, create_missed_slots_by_proposer_entity_chart
from shared.ui_components import add_ethPandaOps_logo

# Import shared components  
from shared.ui_components import apply_ethPandaOps_styling
from shared.ethereum.validators import load_validators_from_ethseer, load_blockprint_clients


def main():
    """Main dashboard function."""
    
    # Apply consistent styling
    apply_ethPandaOps_styling()
    
    # Initialize session state
    if 'attestation_cdf_data_loaded' not in st.session_state:
        st.session_state.attestation_cdf_data_loaded = False
    if 'attestation_cdf_data' not in st.session_state:
        st.session_state.attestation_cdf_data = None
    if 'attestation_cdf_metrics' not in st.session_state:
        st.session_state.attestation_cdf_metrics = None
    
    # Header
    st.markdown('<h1 class="main-header">🚫 Attestation Analysis of Missed Slots</h1>', unsafe_allow_html=True)
    st.markdown("""
    <div class="header-description">
    Analyze attestation propagation patterns for missed slots (slots without blocks) across the Ethereum network. 
    Understand how attestations behave when blocks are not proposed and identify client performance during missed slots.
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar configuration
    st.sidebar.header("⚙️ Configuration")
    
    # Network selection
    network = st.sidebar.selectbox(
        "Select Network",
        get_supported_networks(),
        index=0,  # Default to mainnet
        help="Choose the Ethereum network to analyze"
    )
    
    # Time range selection
    from datetime import timezone
    
    # Custom time range option
    use_custom_range = st.sidebar.checkbox("Use Custom Time Range")
    
    if not use_custom_range:
        # Only show preset options when custom is NOT selected
        time_ranges = get_default_time_ranges()
        time_range_option = st.sidebar.selectbox(
            "Select Time Range",
            list(time_ranges.keys()),
            index=0,  # Default to "Last 1 Hour"
            help="Choose the time period for analysis"
        )
        
        # Calculate actual time range in UTC (database uses UTC)
        end_time = datetime.now(timezone.utc)
        start_time = end_time - time_ranges[time_range_option]
    else:
        # Custom time range inputs
        # Use session state to persist custom values or default to last hour
        default_end = datetime.now(timezone.utc)
        default_start = default_end - timedelta(hours=1)
        
        col1, col2 = st.sidebar.columns(2)
        with col1:
            start_date = st.date_input(
                "Start Date", 
                value=st.session_state.get('custom_start_date', default_start.date()),
                min_value=datetime(2020, 12, 1).date(),  # Ethereum beacon chain genesis
                max_value=datetime.now(timezone.utc).date(),
                key='custom_start_date'
            )
            start_time_input = st.time_input(
                "Start Time (UTC)", 
                value=st.session_state.get('custom_start_time', default_start.time()),
                key='custom_start_time'
            )
        with col2:
            end_date = st.date_input(
                "End Date", 
                value=st.session_state.get('custom_end_date', default_end.date()),
                min_value=datetime(2020, 12, 1).date(),
                max_value=datetime.now(timezone.utc).date(),
                key='custom_end_date'
            )
            end_time_input = st.time_input(
                "End Time (UTC)", 
                value=st.session_state.get('custom_end_time', default_end.time()),
                key='custom_end_time'
            )
        
        # Combine and add UTC timezone
        start_time = datetime.combine(start_date, start_time_input).replace(tzinfo=timezone.utc)
        end_time = datetime.combine(end_date, end_time_input).replace(tzinfo=timezone.utc)
        
        # Validate time range
        if start_time >= end_time:
            st.sidebar.error("Start time must be before end time")
        if (end_time - start_time).days > 30:
            st.sidebar.warning("Large time ranges may take longer to load")
    
    # Analysis configuration
    st.sidebar.subheader("Analysis Settings")
    
    # Data source selection
    data_source_options = get_data_source_options()
    data_source = st.sidebar.selectbox(
        "Attestation Data Source",
        list(data_source_options.keys()),
        index=0,  # Default to beacon_api
        format_func=lambda x: data_source_options[x]["name"],
        help="Choose the data source for attestation analysis"
    )
    
    # Show data source description
    with st.sidebar.expander("ℹ️ Data Source Info"):
        st.write(f"**{data_source_options[data_source]['name']}**")
        st.write(data_source_options[data_source]['description'])
        st.write(f"**Use Case**: {data_source_options[data_source]['use_case']}")
        st.write(f"**Table**: `{data_source_options[data_source]['table']}`")
    
    grouping_options = get_grouping_options()
    primary_grouping = st.sidebar.selectbox(
        "Primary Grouping",
        list(grouping_options.keys()),
        index=0,  # Default to client_type
        help="Primary dimension for grouping attestation data"
    )
    
    # Note about client filtering moved to main page
    st.sidebar.info("Client filtering options are available on the main page after loading data")
    
    # Data loading section
    st.sidebar.subheader("Data Loading")
    
    # Add clear cache button
    col1, col2 = st.sidebar.columns(2)
    with col1:
        load_button = st.button("🔄 Load Missed Slot Data", type="primary")
    with col2:
        clear_cache_button = st.button("🗑️ Clear Cache", type="secondary")
    
    # Handle clear cache button
    if clear_cache_button:
        # Clear session state related to attestation CDF
        if 'attestation_cdf_data_loaded' in st.session_state:
            st.session_state.attestation_cdf_data_loaded = False
        if 'attestation_cdf_data' in st.session_state:
            st.session_state.attestation_cdf_data = None
        if 'attestation_cdf_metrics' in st.session_state:
            st.session_state.attestation_cdf_metrics = None
        if 'start_time' in st.session_state:
            del st.session_state.start_time
        if 'end_time' in st.session_state:
            del st.session_state.end_time
        
        # Clear Streamlit cache
        st.cache_data.clear()
        
        # Show success message
        st.sidebar.success("✅ Cache cleared successfully!")
        st.rerun()
    
    if load_button:
        with st.spinner("Loading missed slot attestation data..."):
            try:
                # Load combined data with selected data source
                combined_data = load_combined_analysis_data(start_time, end_time, network, data_source)
                
                # Validate data quality
                data_quality = combined_data['data_quality']
                
                if data_quality['attestation_rows'] == 0:
                    st.error("No attestation data found for the selected time range and network.")
                    return
                
                # Calculate CDF metrics
                with st.spinner("Computing CDF metrics..."):
                    # Map grouping option to actual column name
                    if primary_grouping == 'client_type':
                        actual_grouping_column = 'meta_client_name'
                    elif primary_grouping == 'slot':
                        actual_grouping_column = 'slot'
                    else:
                        actual_grouping_column = 'meta_client_name'
                    
                    attestation_data_for_cdf = combined_data['attestations']
                    
                    cdf_metrics = calculate_node_cdf_metrics(
                        attestation_data_for_cdf,
                        combined_data['committees'],
                        grouping_column=actual_grouping_column
                    )
                    
                # Store in session state
                st.session_state.attestation_cdf_data = combined_data
                st.session_state.attestation_cdf_metrics = {
                    'raw_cdf': cdf_metrics,
                    'aggregated': None  # No longer aggregating across conditions
                }
                st.session_state.attestation_cdf_data_loaded = True
                st.session_state.start_time = start_time
                st.session_state.end_time = end_time
                
                st.success(f"✅ Loaded data for {data_quality['attestation_rows']} attestation records across {data_quality['slot_range']} slots")
                
            except Exception as e:
                st.error(f"Error loading data: {str(e)}")
                st.session_state.attestation_cdf_data_loaded = False
    
    # Display data quality information and client filtering controls
    if st.session_state.attestation_cdf_data_loaded and st.session_state.attestation_cdf_data:
        data_quality = st.session_state.attestation_cdf_data['data_quality']
        
        with st.sidebar.expander("📊 Data Quality"):
            st.write(f"**Attestation Records**: {data_quality['attestation_rows']:,}")
            st.write(f"**Slot Range**: {data_quality['slot_range']:,}")
            st.write(f"**Committee Slots**: {data_quality['committee_slots']:,}")
            st.write(f"**Networks**: {', '.join(data_quality['networks'])}")
            st.write(f"**Data Source**: {data_quality['data_source']}")
            st.write(f"**Table**: `{data_quality['data_source_table']}`")
    
    # Main dashboard content
    if st.session_state.attestation_cdf_data_loaded and st.session_state.attestation_cdf_metrics:
        render_analysis_dashboard(
            st.session_state.attestation_cdf_data,
            st.session_state.attestation_cdf_metrics
        )
    else:
        render_welcome_screen()


def apply_client_filters(combined_data, cdf_metrics, client_filters):
    """Apply client filtering to the data based on user selections."""
    
    filtered_data = combined_data.copy()
    filtered_metrics = cdf_metrics.copy()
    
    # Get attestation data for filtering
    attestations = filtered_data['attestations'].copy()
    
    # Apply client name filters
    if client_filters.get('selected_clients'):
        # Include only selected clients
        attestations = attestations[attestations['meta_client_name'].isin(client_filters['selected_clients'])]
    
    if client_filters.get('excluded_clients'):
        # Exclude specified clients
        attestations = attestations[~attestations['meta_client_name'].isin(client_filters['excluded_clients'])]
    
    # Apply consensus implementation filters if available
    if 'meta_consensus_implementation' in attestations.columns:
        if client_filters.get('selected_implementations'):
            attestations = attestations[attestations['meta_consensus_implementation'].isin(client_filters['selected_implementations'])]
        
        if client_filters.get('excluded_implementations'):
            attestations = attestations[~attestations['meta_consensus_implementation'].isin(client_filters['excluded_implementations'])]
    
    # Update filtered data
    filtered_data['attestations'] = attestations
    
    # Recalculate CDF metrics with filtered data
    if not attestations.empty:
        # Recalculate CDF metrics using the filtered attestation data
        recalculated_cdf = calculate_node_cdf_metrics(
            attestations,
            filtered_data['committees'],
            grouping_column='meta_client_name'
        )
        filtered_metrics['raw_cdf'] = recalculated_cdf
    else:
        # No data after filtering
        filtered_metrics['raw_cdf'] = pd.DataFrame()
    
    return filtered_data, filtered_metrics


def render_analysis_dashboard(combined_data, cdf_metrics):
    """Render the main analysis dashboard with optional client filtering."""
    
    # Client Filtering Section on Main Page
    st.subheader("🔧 Client Filtering")
    
    attestation_data = combined_data['attestations']
    available_clients = sorted(attestation_data['meta_client_name'].unique())
    
    # Check if we have consensus implementation data
    if 'meta_consensus_implementation' in attestation_data.columns:
        available_implementations = sorted(attestation_data['meta_consensus_implementation'].unique())
    else:
        available_implementations = []
    
    # Create filtering UI
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Include/Exclude Clients**")
        selected_clients = st.multiselect(
            "Select clients to analyze (leave empty for all):",
            available_clients,
            default=[],
            key="page_selected_clients",
            help="Choose specific clients to include in the analysis"
        )
        
        excluded_clients = st.multiselect(
            "Exclude these clients:",
            available_clients,
            default=[],
            key="page_excluded_clients",
            help="Choose clients to exclude from the analysis"
        )
    
    with col2:
        if available_implementations:
            st.markdown("**Include/Exclude Implementations**")
            selected_implementations = st.multiselect(
                "Select implementations to analyze (leave empty for all):",
                available_implementations,
                default=[],
                key="page_selected_implementations"
            )
            
            excluded_implementations = st.multiselect(
                "Exclude these implementations:",
                available_implementations,
                default=[],
                key="page_excluded_implementations"
            )
        else:
            selected_implementations = []
            excluded_implementations = []
            st.info("No consensus implementation data available")
    
    # Apply filters button
    apply_filters = st.button("Apply Filters", type="primary", key="apply_client_filters")
    
    # Store and apply filters
    if apply_filters or selected_clients or excluded_clients or selected_implementations or excluded_implementations:
        client_filters = {
            'enabled': True,
            'selected_clients': selected_clients,
            'excluded_clients': excluded_clients,
            'selected_implementations': selected_implementations,
            'excluded_implementations': excluded_implementations
        }
        
        filtered_data, filtered_metrics = apply_client_filters(combined_data, cdf_metrics, client_filters)
        
        # Show filter status
        filter_info = []
        if selected_clients:
            filter_info.append(f"Including: {', '.join(selected_clients)}")
        if excluded_clients:
            filter_info.append(f"Excluding: {', '.join(excluded_clients)}")
        if selected_implementations:
            filter_info.append(f"Implementations: {', '.join(selected_implementations)}")
        if excluded_implementations:
            filter_info.append(f"Excluding implementations: {', '.join(excluded_implementations)}")
        
        if filter_info:
            st.info("🔧 Filters applied: " + " | ".join(filter_info))
    else:
        filtered_data = combined_data
        filtered_metrics = cdf_metrics
    
    st.divider()
    
    st.subheader("📈 Missed Slot CDF Analysis")
    st.markdown("Attestation propagation times during missed slots (slots without blocks)")
    
    # Check if we have any data to plot
    has_raw_cdf = filtered_metrics.get('raw_cdf') is not None and not filtered_metrics['raw_cdf'].empty
    
    view_mode = "All Slots (Aggregated)"
    slot_filter = None
    plot_data = None
    
    if has_raw_cdf:
        # Add slot picker
        # Keep the original data for slot selection
        original_raw_cdf = filtered_metrics['raw_cdf']
        available_slots = sorted(original_raw_cdf['slot'].unique())
        
        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            view_mode = st.radio(
                "View Mode",
                ["All Slots (Aggregated)", "Per Slot"],
                help="Choose between viewing aggregated data across all slots or individual slot analysis"
            )
        
        if view_mode == "Per Slot":
            with col2:
                slot_filter = st.selectbox(
                    "Select Slot",
                    available_slots,
                    format_func=lambda x: f"Slot {x}",
                    help=f"Choose a specific slot to analyze ({len(available_slots)} slots available)"
                )
            
            # Filter data for selected slot but keep it separate
            plot_data = original_raw_cdf[original_raw_cdf['slot'] == slot_filter].copy()
            
            with col3:
                # Show slot info
                if not plot_data.empty:
                    st.metric("Nodes with data", plot_data['group_name'].nunique() if 'group_name' in plot_data.columns else plot_data['meta_client_name'].nunique())
        else:
            # Use all data for aggregated view
            plot_data = original_raw_cdf
        
    if has_raw_cdf and plot_data is not None:
        # Create CDF plot with client data only (no aggregated conditions)
        try:
            # Get total missed slots count from filtered_data
            slots_data = filtered_data.get('slots', pd.DataFrame())
            total_missed_slots = len(slots_data) if not slots_data.empty else len(available_slots)
            
            # Set plot title based on view mode
            if view_mode == "Per Slot" and slot_filter is not None:
                # Don't show time range for single slot view
                plot_title = f"Attestation Propagation CDF - Slot {slot_filter}"
            else:
                # Get time range from session state for subtitle (only for aggregated view)
                time_range_str = ""
                if 'start_time' in st.session_state and 'end_time' in st.session_state:
                    start_time = st.session_state.start_time
                    end_time = st.session_state.end_time
                    # Format as UTC strings
                    start_str = start_time.strftime('%Y-%m-%d %H:%M:%S UTC')
                    end_str = end_time.strftime('%Y-%m-%d %H:%M:%S UTC')
                    time_range_str = f"<br><sub>{start_str} to {end_str}</sub>"
                plot_title = f"Attestation Propagation CDF - {total_missed_slots} Missed Slots{time_range_str}"
            
            fig = create_cdf_comparison_plot(
                aggregated_data=None,
                client_data=plot_data,
                comparison_dimension=None,
                title=plot_title
            )
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Error creating CDF plot: {str(e)}")
            st.write("**Debug Info:**")
            st.write(f"Raw CDF columns: {list(filtered_metrics['raw_cdf'].columns)}")
            st.write(f"Raw CDF shape: {filtered_metrics['raw_cdf'].shape}")
    else:
        st.warning("No data available for CDF plotting. Try adjusting your filters or time range.")
    
    # Slow Period Analysis Section
    # Get network from data quality info
    network = filtered_data.get('data_quality', {}).get('networks', ['mainnet'])[0]
    # Pass client filters if they were applied
    active_filters = None
    if apply_filters or selected_clients or excluded_clients or selected_implementations or excluded_implementations:
        active_filters = {
            'selected_clients': selected_clients,
            'excluded_clients': excluded_clients,
            'selected_implementations': selected_implementations,
            'excluded_implementations': excluded_implementations
        }
    
    # Pass slot filter if in per-slot view mode
    current_slot_filter = slot_filter if view_mode == "Per Slot" else None
    render_slow_period_analysis(filtered_data, filtered_metrics, network, active_filters, current_slot_filter)
    
    # Debug section - show missed slots
    with st.expander("🔍 Debug: Missed Slots Information"):
        if st.session_state.attestation_cdf_data_loaded and st.session_state.attestation_cdf_data:
            slots_data = st.session_state.attestation_cdf_data.get('slots', pd.DataFrame())
            
            # Use filtered data if available, otherwise use original
            if has_raw_cdf and filtered_metrics.get('raw_cdf') is not None:
                # Convert back to regular attestation format from CDF format
                attestation_data = filtered_metrics['raw_cdf']
            else:
                attestation_data = st.session_state.attestation_cdf_data.get('attestations', pd.DataFrame())
            
            if not slots_data.empty:
                st.write(f"**Total missed slots found:** {len(slots_data)}")
                st.write(f"**Slot range:** {slots_data['slot'].min()} - {slots_data['slot'].max()}")
                
                # Show first 20 missed slots
                st.write("**First 20 missed slots:**")
                st.dataframe(
                    slots_data[['slot', 'epoch']].head(20),
                    use_container_width=True
                )
                
            if not attestation_data.empty:
                st.write("\n**Attestation data summary:**")
                st.write(f"Total attestation records: {len(attestation_data)}")
                st.write(f"Unique slots with attestations: {attestation_data['slot'].nunique()}")
                client_col = 'group_name' if 'group_name' in attestation_data.columns else 'meta_client_name'
                if client_col in attestation_data.columns:
                    st.write(f"Unique clients: {attestation_data[client_col].nunique()}")
                
                # Show sample of attestation data
                st.write("\n**Sample attestation data (first 10 rows):**")
                
                # Determine which columns to display based on what's available
                base_cols = ['slot', 'group_name', 'received_attestations']
                time_cols = ['p50_propagation_time', 'p90_propagation_time']
                
                # Check for original column names too
                if 'meta_client_name' in attestation_data.columns:
                    base_cols = ['slot', 'meta_client_name', 'total_attestations', 'unique_validators']
                
                # Check for propagation time columns in various formats
                if 'min_propagation' in attestation_data.columns:
                    time_cols = ['min_propagation', 'p50_propagation', 'p90_propagation', 'max_propagation']
                elif 'min_propagation_time' in attestation_data.columns:
                    time_cols = ['min_propagation_time', 'p50_propagation_time', 'p90_propagation_time', 'max_propagation_time']
                
                display_cols = base_cols + time_cols
                available_cols = [col for col in display_cols if col in attestation_data.columns]
                
                if available_cols:
                    display_df = attestation_data[available_cols].head(10).copy()
                    
                    # Format propagation times to show as milliseconds
                    for col in available_cols:
                        if 'propagation' in col and col in display_df.columns:
                            display_df[col] = display_df[col].round(0).astype(int)
                    
                    st.dataframe(display_df, use_container_width=True)
                
                # Show coverage info if available
                if filtered_metrics.get('raw_cdf') is not None and 'attestation_coverage_pct' in filtered_metrics['raw_cdf'].columns:
                    st.write("\n**Attestation Coverage Distribution:**")
                    coverage_summary = filtered_metrics['raw_cdf']['attestation_coverage_pct'].describe()
                    st.write(f"- Min: {coverage_summary['min']:.1f}%")
                    st.write(f"- Mean: {coverage_summary['mean']:.1f}%")
                    st.write(f"- Max: {coverage_summary['max']:.1f}%")
        else:
            st.info("Load data first to see debug information")


def render_welcome_screen():
    """Render welcome screen when no data is loaded."""
    
    st.info("👈 Configure parameters in the sidebar and click 'Load Missed Slot Data' to begin analysis.")
    
    # Show analysis overview
    st.subheader("🎯 About This Analysis")
    
    st.markdown("""
    This analysis provides insights into **attestation propagation patterns during missed slots** across the Ethereum network:
    
    **📊 What You'll See:**
    - **CDF Curves**: Cumulative distribution of attestation arrival times for missed slots only
    - **Performance Metrics**: P50/P90 propagation times and coverage ratios during missed slots
    - **Client Performance**: How different Ethereum clients handle attestations when blocks are missed
    - **Propagation Patterns**: Understanding attestation behavior in the absence of block proposals
    
    **🔍 Key Insights:**
    - **Network Resilience**: How attestations propagate when blocks are not proposed
    - **Client Behavior**: Performance variations across different Ethereum clients during missed slots
    - **Coverage Patterns**: Attestation coverage ratios when there's no block to attest to
    - **Timing Analysis**: How quickly attestations spread in missed slot scenarios
    
    **⚙️ Configuration Options:**
    - **Time Ranges**: Analyze recent periods or historical missed slot data
    - **Network Comparison**: Compare mainnet, testnets, and other networks
    - **Client Filtering**: Focus on specific Ethereum client implementations
    """)


def render_slow_period_analysis(combined_data, cdf_metrics, network, client_filters=None, slot_filter=None):
    """Render slow period analysis section with entity/client breakdown."""
    
    st.subheader("🐢 Slow Period Analysis")
    st.markdown("Analyze which validators are in the slow period/long tail of attestation propagation")
    
    # Check if we have data
    if cdf_metrics.get('raw_cdf') is None or cdf_metrics['raw_cdf'].empty:
        st.info("Load data first to see slow period analysis")
        return
        
    # Configuration section for slow period threshold
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("### Configuration")
        slow_threshold = st.slider(
            "Define slow period threshold (percentile)",
            min_value=50,
            max_value=99,
            value=90,
            step=1,
            help="Validators with propagation times above this percentile are considered 'slow'"
        )
    
    with col2:
        st.metric("Threshold", f"P{slow_threshold}")
    
    # Load raw attestation data with validator indices
    with st.spinner("Loading validator attestation data..."):
        # Get time range and data source from session state
        if 'start_time' in st.session_state and 'end_time' in st.session_state:
            start_time = st.session_state.start_time
            end_time = st.session_state.end_time
        else:
            # Use data quality info to get time range
            data_quality = combined_data.get('data_quality', {})
            # Default to last hour if not available
            from datetime import datetime, timezone, timedelta
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=1)
        
        # Get data source
        data_source = combined_data.get('data_quality', {}).get('data_source', 'beacon_api')
        
        # Get missed slots from combined data
        slots_data = combined_data.get('slots', pd.DataFrame())
        if not slots_data.empty:
            if slot_filter is not None:
                # If specific slot is selected, only analyze that slot
                missed_slots = [slot_filter]
                st.info(f"Analyzing slow period for slot {slot_filter} only")
            else:
                missed_slots = slots_data['slot'].tolist()
        else:
            missed_slots = None
        
        # Load raw attestation data
        import polars as pl
        raw_attestations_pl = load_raw_attestation_data_for_slow_analysis(
            start_time, end_time, network, data_source, missed_slots, client_filters
        )
        
        if raw_attestations_pl.is_empty():
            st.warning("No raw attestation data available for slow period analysis")
            return
        
        # Convert to pandas for easier manipulation
        raw_attestations = raw_attestations_pl.to_pandas()
    
    # Calculate the threshold time based on the selected percentile
    threshold_percentile = slow_threshold / 100.0
    
    # Get all propagation times to calculate the percentile threshold
    all_propagation_times = raw_attestations['propagation_time'].values
    threshold_time = np.percentile(all_propagation_times, slow_threshold)
    
    st.info(f"P{slow_threshold} threshold: {threshold_time:.0f}ms")
    
    # Get attestations in the slow period (those with propagation time above the threshold)
    slow_attestations = raw_attestations[raw_attestations['propagation_time'] > threshold_time]
    
    if slow_attestations.empty:
        st.info("No attestations found in the slow period with current threshold")
        return
    
    # Get unique validators who had slow attestations
    slow_validator_indices = slow_attestations['attesting_validator_index'].unique()
    
    # Calculate statistics per validator
    validator_stats = slow_attestations.groupby('attesting_validator_index').agg({
        'propagation_time': ['mean', 'min', 'max', 'count'],
        'slot': 'nunique'
    }).reset_index()
    
    validator_stats.columns = ['attesting_validator_index', 'avg_propagation_time', 
                              'min_propagation_time', 'max_propagation_time', 
                              'attestation_count', 'slot_count']
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Slow Validators", f"{len(slow_validator_indices):,}")
    with col2:
        st.metric("Slow Attestations", f"{len(slow_attestations):,}")
    with col3:
        st.metric("Affected Slots", f"{slow_attestations['slot'].nunique():,}")
    
    # Load entity and client mappings
    with st.spinner("Loading validator metadata..."):
        entities = load_validators_from_ethseer(network)
        clients = load_blockprint_clients(network)
    
    # Create entity breakdown
    entity_counts = {}
    client_counts = {}
    
    for val_idx in slow_validator_indices:
        entity = entities.get(val_idx, 'unknown')
        client = clients.get(val_idx, 'unknown')
        
        entity_counts[entity] = entity_counts.get(entity, 0) + 1
        client_counts[client] = client_counts.get(client, 0) + 1
    
    # Create visualizations
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Entity Breakdown")
        if entity_counts:
            # Check if all entities are 'unknown' (indicating no entity resolution data)
            if len(entity_counts) == 1 and 'unknown' in entity_counts:
                st.info(f"Entity resolution data not available for {network}. All validators shown as 'unknown'.")
                # Still show the chart for consistency
            
            # Sort by count and take top 20
            sorted_entities = sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)[:20]
            
            fig_entity = go.Figure(data=[
                go.Bar(
                    x=[e[0] for e in sorted_entities],
                    y=[e[1] for e in sorted_entities],
                    text=[e[1] for e in sorted_entities],
                    textposition='auto',
                    marker_color='indianred'
                )
            ])
            
            fig_entity.update_layout(
                title=f"Top 20 Entities in Slow Period (>{slow_threshold}th percentile)",
                xaxis_title="Entity",
                yaxis_title="Number of Validators",
                height=400,
                xaxis_tickangle=-45
            )
            
            st.plotly_chart(fig_entity, use_container_width=True)
            
            # Show percentage breakdown only if we have real entity data
            if not (len(entity_counts) == 1 and 'unknown' in entity_counts):
                total_slow = len(slow_validator_indices)
                with st.expander("Entity Details"):
                    for entity, count in sorted_entities[:10]:
                        pct = (count / total_slow) * 100
                        st.write(f"**{entity}**: {count} validators ({pct:.1f}%)")
        else:
            st.info("No entity data available")
    
    with col2:
        st.markdown("### Client Breakdown")
        if client_counts:
            # Sort by count and take top clients
            sorted_clients = sorted(client_counts.items(), key=lambda x: x[1], reverse=True)
            
            fig_client = go.Figure(data=[
                go.Bar(
                    x=[c[0] for c in sorted_clients],
                    y=[c[1] for c in sorted_clients],
                    text=[c[1] for c in sorted_clients],
                    textposition='auto',
                    marker_color='lightblue'
                )
            ])
            
            fig_client.update_layout(
                title=f"Client Distribution in Slow Period (>{slow_threshold}th percentile)",
                xaxis_title="Client",
                yaxis_title="Number of Validators",
                height=400,
                xaxis_tickangle=-45
            )
            
            st.plotly_chart(fig_client, use_container_width=True)
            
            # Show percentage breakdown
            with st.expander("Client Details"):
                for client, count in sorted_clients:
                    pct = (count / total_slow) * 100
                    st.write(f"**{client}**: {count} validators ({pct:.1f}%)")
        else:
            st.info("No client data available")
    
    # Add missed slots by proposer entity distribution chart
    st.divider()
    st.subheader("📊 Missed Block Proposals by Entity")
    st.markdown("Shows which entities were assigned to propose blocks but didn't (resulting in missed slots)")
    
    # Load proposer duties for the missed slots
    with st.spinner("Loading proposer duties for missed slots..."):
        # Get the list of missed slots
        if not slots_data.empty:
            missed_slots_list = slots_data['slot'].tolist()
        else:
            missed_slots_list = missed_slots
            
        # Load proposer duties
        proposer_duties_df = load_proposer_duties_for_missed_slots(missed_slots_list, network)
        
        if not proposer_duties_df.empty:
            # Check if entity data is available
            unique_entities = proposer_duties_df['proposer_validator_index'].map(
                lambda x: entities.get(x, 'unknown') if pd.notna(x) else 'unknown'
            ).unique()
            
            if len(unique_entities) == 1 and unique_entities[0] == 'unknown' and not entities:
                st.info(f"Entity resolution data not available for {network}. Showing validators without entity grouping.")
            
            # Create the chart
            missed_slots_fig = create_missed_slots_by_proposer_entity_chart(proposer_duties_df, entities, top_n=20)
            st.plotly_chart(missed_slots_fig, use_container_width=True)
            
            # Show summary statistics
            col1, col2, col3 = st.columns(3)
            with col1:
                total_entities_missed = proposer_duties_df['proposer_validator_index'].map(
                    lambda x: entities.get(x, 'unknown') if pd.notna(x) else 'unknown'
                ).nunique()
                st.metric("Entities with Missed Proposals", f"{total_entities_missed:,}")
            with col2:
                total_missed_proposals = len(proposer_duties_df)
                st.metric("Total Missed Proposals", f"{total_missed_proposals:,}")
            with col3:
                # Calculate percentage of missed slots with known proposer
                coverage_pct = (len(proposer_duties_df) / len(missed_slots_list) * 100) if missed_slots_list else 0
                st.metric("Proposer Data Coverage", f"{coverage_pct:.1f}%")
        else:
            st.warning("No proposer duty data found for the missed slots")
    
    # Entity Density Analysis across percentile thresholds
    st.divider()
    st.subheader("📊 Entity Density Analysis Across Percentile Thresholds")
    st.markdown("Shows how entity concentration changes as we vary the slowness threshold")
    
    # Check if we have entity data
    if not entities:
        st.info(f"Entity resolution data not available for {network}. Analysis will show all validators as 'unknown'.")
    
    with st.spinner("Calculating entity density across percentile thresholds..."):
        # Define percentile thresholds to analyze
        percentile_thresholds = [50, 60, 70, 80, 85, 90, 92, 94, 95, 96, 97, 98, 99]
        
        # Store entity percentages at each threshold
        entity_density_data = {}
        total_validators_by_threshold = {}
        
        for threshold in percentile_thresholds:
            # Calculate threshold time for this percentile
            threshold_time_pct = np.percentile(all_propagation_times, threshold)
            
            # Get attestations above this threshold
            slow_at_threshold = raw_attestations[raw_attestations['propagation_time'] > threshold_time_pct]
            
            if not slow_at_threshold.empty:
                # Get unique validators at this threshold
                validators_at_threshold = slow_at_threshold['attesting_validator_index'].unique()
                total_validators_by_threshold[threshold] = len(validators_at_threshold)
                
                # Count validators by entity
                entity_counts_at_threshold = {}
                for val_idx in validators_at_threshold:
                    entity = entities.get(val_idx, 'unknown')
                    entity_counts_at_threshold[entity] = entity_counts_at_threshold.get(entity, 0) + 1
                
                # Calculate percentages
                total_at_threshold = len(validators_at_threshold)
                for entity, count in entity_counts_at_threshold.items():
                    if entity not in entity_density_data:
                        entity_density_data[entity] = {}
                    entity_density_data[entity][threshold] = (count / total_at_threshold) * 100
        
        # Get top entities by their maximum percentage at any threshold
        entity_max_percentages = {}
        for entity, percentages in entity_density_data.items():
            if percentages:  # Check if entity has any data
                entity_max_percentages[entity] = max(percentages.values())
        
        # Get top 10 entities
        top_entities = sorted(entity_max_percentages.items(), key=lambda x: x[1], reverse=True)[:10]
        top_entity_names = [e[0] for e in top_entities]
        
        # Create stacked 100% bar chart
        fig_density = go.Figure()
        
        # Prepare data for stacked bar chart
        # We'll show top 8 entities + "Others"
        top_8_entities = top_entity_names[:8]
        
        # Add traces for each entity
        for entity in top_8_entities:
            y_values = []
            for threshold in percentile_thresholds:
                y_values.append(entity_density_data.get(entity, {}).get(threshold, 0))
            
            fig_density.add_trace(go.Bar(
                name=entity[:25] + '...' if len(entity) > 25 else entity,
                x=[f"P{p}" for p in percentile_thresholds],
                y=y_values,
                text=[f"{v:.1f}%" if v > 5 else "" for v in y_values],  # Only show text for bars > 5%
                textposition='inside',
                textfont=dict(size=10),
                hovertemplate='%{fullData.name}<br>%{y:.1f}%<extra></extra>'
            ))
        
        # Calculate and add "Others" category
        others_values = []
        for threshold in percentile_thresholds:
            total_top8 = sum(entity_density_data.get(entity, {}).get(threshold, 0) for entity in top_8_entities)
            others_values.append(100 - total_top8)
        
        fig_density.add_trace(go.Bar(
            name='Others',
            x=[f"P{p}" for p in percentile_thresholds],
            y=others_values,
            text=[f"{v:.1f}%" if v > 5 else "" for v in others_values],
            textposition='inside',
            textfont=dict(size=10),
            marker_color='lightgray',
            hovertemplate='Others<br>%{y:.1f}%<extra></extra>'
        ))
        
        # Add a vertical line or annotation for current threshold
        current_threshold_idx = percentile_thresholds.index(slow_threshold) if slow_threshold in percentile_thresholds else None
        
        fig_density.update_layout(
            title="Entity Distribution Across Percentile Thresholds<br><sub>Stacked 100% bar chart showing entity concentration</sub>",
            xaxis_title="Percentile Threshold",
            yaxis_title="Percentage of Slow Validators (%)",
            barmode='stack',
            height=600,
            showlegend=True,
            legend=dict(
                yanchor="top",
                y=0.99,
                xanchor="left",
                x=1.01
            ),
            hovermode='x unified'
        )
        
        # Add annotation for current threshold if it exists
        if current_threshold_idx is not None:
            fig_density.add_annotation(
                x=f"P{slow_threshold}",
                y=105,
                text=f"Current<br>threshold",
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowwidth=2,
                arrowcolor="red",
                ax=0,
                ay=-40,
                font=dict(size=12, color="red")
            )
        
        fig_density.update_yaxes(range=[0, 100])
        
        st.plotly_chart(add_ethPandaOps_logo(fig_density), use_container_width=True)
        
        # Show summary statistics
        col1, col2, col3 = st.columns(3)
        
        # Find the entity with highest percentage at P99
        if 99 in percentile_thresholds:
            p99_percentages = [(entity, entity_density_data.get(entity, {}).get(99, 0)) for entity in top_entity_names]
            dominant_entity_p99 = max(p99_percentages, key=lambda x: x[1])
            
            with col1:
                st.metric(
                    f"Dominant Entity at P99",
                    dominant_entity_p99[0][:20] + '...' if len(dominant_entity_p99[0]) > 20 else dominant_entity_p99[0],
                    f"{dominant_entity_p99[1]:.1f}%"
                )
        
        # Show how concentration changes
        if 90 in percentile_thresholds and 99 in percentile_thresholds:
            # Get the top entity's percentage at both thresholds
            top_entity = top_entity_names[0] if top_entity_names else None
            if top_entity and top_entity in entity_density_data:
                p90_pct = entity_density_data[top_entity].get(90, 0)
                p99_pct = entity_density_data[top_entity].get(99, 0)
                
                with col2:
                    st.metric(
                        f"{top_entity[:15]}... at P90",
                        f"{p90_pct:.1f}%",
                        f"{p99_pct - p90_pct:+.1f}% at P99"
                    )
        
        # Total validators at different thresholds
        if 99 in total_validators_by_threshold and 90 in total_validators_by_threshold:
            with col3:
                st.metric(
                    "Validators at P99",
                    f"{total_validators_by_threshold[99]:,}",
                    f"vs {total_validators_by_threshold[90]:,} at P90"
                )
        
        # Create a complementary stacked area chart
        with st.expander("View as Stacked Area Chart"):
            # Prepare data for stacked area chart
            stacked_data = []
            
            for threshold in percentile_thresholds:
                row = {'threshold': threshold}
                
                # Add top entities
                for entity in top_entity_names[:5]:  # Top 5 for clarity
                    row[entity] = entity_density_data.get(entity, {}).get(threshold, 0)
                
                # Calculate "Others" percentage
                total_top5 = sum(entity_density_data.get(entity, {}).get(threshold, 0) for entity in top_entity_names[:5])
                row['Others'] = 100 - total_top5
                
                stacked_data.append(row)
            
            stacked_df = pd.DataFrame(stacked_data)
            
            # Create stacked area chart
            fig_stacked = go.Figure()
            
            # Add traces for each entity
            for col in stacked_df.columns[1:]:  # Skip 'threshold' column
                fig_stacked.add_trace(go.Scatter(
                    x=stacked_df['threshold'],
                    y=stacked_df[col],
                    mode='lines',
                    stackgroup='one',
                    name=col[:30] + '...' if len(col) > 30 else col,
                    line=dict(width=0.5)
                ))
            
            fig_stacked.update_layout(
                title="Entity Distribution Across Percentile Thresholds (Stacked)",
                xaxis_title="Percentile Threshold",
                yaxis_title="Percentage of Slow Validators (%)",
                height=400,
                hovermode='x unified'
            )
            
            fig_stacked.update_xaxes(
                tickmode='array',
                tickvals=percentile_thresholds,
                ticktext=[f"P{p}" for p in percentile_thresholds]
            )
            
            st.plotly_chart(add_ethPandaOps_logo(fig_stacked), use_container_width=True)
    
    # Additional analysis - show time distribution
    with st.expander("Timing Distribution Analysis"):
        st.markdown("### Propagation Time Distribution")
        
        # Create histogram of propagation times for slow attestations
        fig_dist = px.histogram(
            slow_attestations,
            x='propagation_time',
            nbins=50,
            title=f"Propagation Time Distribution for Slow Attestations (>{slow_threshold}th percentile)",
            labels={'propagation_time': 'Propagation Time (ms)', 'count': 'Number of Attestations'}
        )
        
        fig_dist.add_vline(
            x=threshold_time,
            line_dash="dash",
            line_color="red",
            annotation_text=f"P{slow_threshold} threshold"
        )
        
        st.plotly_chart(add_ethPandaOps_logo(fig_dist), use_container_width=True)
        
        # Show timing statistics for slow attestations
        st.markdown("### Timing Statistics for Slow Attestations")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Min Time", f"{slow_attestations['propagation_time'].min():.0f}ms")
        with col2:
            st.metric("Median Time", f"{slow_attestations['propagation_time'].median():.0f}ms")
        with col3:
            st.metric("Max Time", f"{slow_attestations['propagation_time'].max():.0f}ms")
        with col4:
            st.metric("Unique Entities", f"{len(entity_counts):,}")
        
        # Show validator-level statistics
        if not validator_stats.empty:
            st.markdown("### Top 10 Validators by Average Propagation Time")
            top_validators = validator_stats.nlargest(10, 'avg_propagation_time')[
                ['attesting_validator_index', 'avg_propagation_time', 'attestation_count', 'slot_count']
            ].copy()
            
            # Add entity info if available
            top_validators['entity'] = top_validators['attesting_validator_index'].apply(
                lambda x: entities.get(x, 'unknown')
            )
            
            # Format for display
            display_df = top_validators[['attesting_validator_index', 'entity', 'avg_propagation_time', 
                                        'attestation_count', 'slot_count']].copy()
            display_df.columns = ['Validator Index', 'Entity', 'Avg Time (ms)', 'Attestations', 'Slots']
            display_df['Avg Time (ms)'] = display_df['Avg Time (ms)'].round(0).astype(int)
            
            st.dataframe(display_df, use_container_width=True, hide_index=True)
    
    # Observer Consensus Analysis
    with st.expander("🔍 Observer Consensus Analysis", expanded=True):
        st.markdown("### How many observation nodes saw each validator as slow?")
        st.info("This analysis shows whether validators are consistently slow across multiple observation nodes or if it's isolated to specific nodes (which could indicate network/peering issues).")
        
        # Load detailed observer node data
        with st.spinner("Loading detailed observer node data..."):
            observer_attestations_pl = load_raw_attestation_data_for_slow_analysis(
                start_time, end_time, network, data_source, missed_slots, client_filters, include_observer_nodes=True
            )
            
            if observer_attestations_pl.is_empty():
                st.warning("No observer node data available")
                return
            
            observer_attestations = observer_attestations_pl.to_pandas()
        
        # Apply the same threshold to identify slow attestations
        slow_observer_attestations = observer_attestations[observer_attestations['propagation_time'] > threshold_time]
        
        if slow_observer_attestations.empty:
            st.info("No slow attestations found in observer data")
            return
        
        # Calculate observer consensus
        observer_consensus = slow_observer_attestations.groupby('attesting_validator_index')['observer_node'].nunique().reset_index()
        observer_consensus.columns = ['attesting_validator_index', 'observer_count']
        
        # Create consensus distribution
        consensus_dist = observer_consensus['observer_count'].value_counts().sort_index()
        
        # Visualize observer consensus distribution
        col1, col2 = st.columns([2, 1])
        
        with col1:
            fig_consensus = go.Figure(data=[
                go.Bar(
                    x=consensus_dist.index,
                    y=consensus_dist.values,
                    text=consensus_dist.values,
                    textposition='auto',
                    marker_color='skyblue'
                )
            ])
            
            fig_consensus.update_layout(
                title="Distribution of Observer Consensus",
                xaxis_title="Number of Observers Reporting Slow",
                yaxis_title="Number of Validators",
                height=400
            )
            
            st.plotly_chart(fig_consensus, use_container_width=True)
        
        with col2:
            st.markdown("### Summary")
            total_observers = observer_attestations['observer_node'].nunique()
            st.metric("Total Observers", total_observers)
            
            # Calculate percentage seen by multiple observers
            multi_observer = (observer_consensus['observer_count'] > 1).sum()
            multi_observer_pct = (multi_observer / len(observer_consensus)) * 100
            st.metric("Multi-Observer %", f"{multi_observer_pct:.1f}%")
            
            st.metric("Max Observers", observer_consensus['observer_count'].max())
        
        # Create entity/observer heatmap
        st.markdown("### Entity vs Observer Node Heatmap")
        
        # Add entity information to slow attestations
        slow_observer_attestations['entity'] = slow_observer_attestations['attesting_validator_index'].map(
            lambda x: entities.get(x, 'unknown')
        )
        
        # Aggregate by entity and observer node
        entity_observer_matrix = slow_observer_attestations.groupby(['entity', 'observer_node']).size().reset_index(name='attestation_count')
        
        # Pivot to create matrix
        pivot_matrix = entity_observer_matrix.pivot(index='entity', columns='observer_node', values='attestation_count').fillna(0)
        
        # Sort by total attestations
        pivot_matrix['total'] = pivot_matrix.sum(axis=1)
        pivot_matrix = pivot_matrix.sort_values('total', ascending=False).drop('total', axis=1)
        
        # Take top 20 entities
        top_entities_matrix = pivot_matrix.head(20)
        
        # Create heatmap
        fig_heatmap = go.Figure(data=go.Heatmap(
            z=top_entities_matrix.values,
            x=top_entities_matrix.columns,
            y=top_entities_matrix.index,
            colorscale='YlOrRd',
            text=top_entities_matrix.values.astype(int),
            texttemplate='%{text}',
            textfont={"size": 10},
            hoverongaps=False
        ))
        
        fig_heatmap.update_layout(
            title="Slow Attestations by Entity and Observer Node (Top 20 Entities)",
            xaxis_title="Observer Node",
            yaxis_title="Entity",
            height=600,
            xaxis={'tickangle': -45}
        )
        
        st.plotly_chart(fig_heatmap, use_container_width=True)
        
        # Client breakdown by observer
        st.markdown("### Client vs Observer Node Analysis")
        
        # Add client information
        slow_observer_attestations['client'] = slow_observer_attestations['attesting_validator_index'].map(
            lambda x: clients.get(x, 'unknown')
        )
        
        # Aggregate by client and observer node
        client_observer_matrix = slow_observer_attestations.groupby(['client', 'observer_node']).size().reset_index(name='attestation_count')
        
        # Pivot to create matrix
        client_pivot = client_observer_matrix.pivot(index='client', columns='observer_node', values='attestation_count').fillna(0)
        
        # Create heatmap for clients
        fig_client_heatmap = go.Figure(data=go.Heatmap(
            z=client_pivot.values,
            x=client_pivot.columns,
            y=client_pivot.index,
            colorscale='Blues',
            text=client_pivot.values.astype(int),
            texttemplate='%{text}',
            textfont={"size": 10},
            hoverongaps=False
        ))
        
        fig_client_heatmap.update_layout(
            title="Slow Attestations by Client Type and Observer Node",
            xaxis_title="Observer Node",
            yaxis_title="Client Type",
            height=400,
            xaxis={'tickangle': -45}
        )
        
        st.plotly_chart(fig_client_heatmap, use_container_width=True)
        
        # Slot occurrence distribution
        st.divider()
        st.markdown("### Slot Occurrence Distribution")
        st.info("Shows how many missed slots each slow validator appeared in. Higher counts indicate consistently slow validators.")
        
        # Calculate slot occurrences per validator
        slot_occurrences = slow_observer_attestations.groupby('attesting_validator_index')['slot'].nunique().reset_index()
        slot_occurrences.columns = ['attesting_validator_index', 'slot_count']
        
        # Create distribution of slot counts
        slot_count_dist = slot_occurrences['slot_count'].value_counts().sort_index()
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            fig_slot_dist = go.Figure(data=[
                go.Bar(
                    x=slot_count_dist.index,
                    y=slot_count_dist.values,
                    text=slot_count_dist.values,
                    textposition='auto',
                    marker_color='lightgreen'
                )
            ])
            
            fig_slot_dist.update_layout(
                title="Distribution: Number of Slow Validators by Slot Occurrence Count",
                xaxis_title="Number of Missed Slots Appeared In",
                yaxis_title="Number of Validators",
                height=400
            )
            
            st.plotly_chart(fig_slot_dist, use_container_width=True)
        
        with col2:
            st.markdown("### Summary")
            total_missed_slots = slow_observer_attestations['slot'].nunique()
            st.metric("Total Missed Slots", total_missed_slots)
            
            # Validators appearing in multiple slots
            multi_slot_validators = (slot_occurrences['slot_count'] > 1).sum()
            multi_slot_pct = (multi_slot_validators / len(slot_occurrences)) * 100
            st.metric("Multi-Slot %", f"{multi_slot_pct:.1f}%")
            
            # Max slots per validator
            st.metric("Max Slots/Validator", slot_occurrences['slot_count'].max())
        
        # Show validators that appear in many slots
        if not slot_occurrences.empty:
            st.markdown("#### Validators Appearing in Most Slots")
            top_slot_validators = slot_occurrences.nlargest(10, 'slot_count').copy()
            
            # Add entity and client info
            top_slot_validators['entity'] = top_slot_validators['attesting_validator_index'].map(
                lambda x: entities.get(x, 'unknown')
            )
            top_slot_validators['client'] = top_slot_validators['attesting_validator_index'].map(
                lambda x: clients.get(x, 'unknown')
            )
            
            # Get average propagation time
            validator_avg_times = slow_observer_attestations.groupby('attesting_validator_index')['propagation_time'].mean()
            top_slot_validators['avg_propagation_time'] = top_slot_validators['attesting_validator_index'].map(validator_avg_times)
            
            # Format for display
            display_slots = top_slot_validators[['attesting_validator_index', 'entity', 'client', 
                                                'slot_count', 'avg_propagation_time']].copy()
            display_slots.columns = ['Validator Index', 'Entity', 'Client', 'Slots Appeared', 'Avg Time (ms)']
            display_slots['Avg Time (ms)'] = display_slots['Avg Time (ms)'].round(0).astype(int)
            
            st.dataframe(display_slots, use_container_width=True, hide_index=True)
        
        # Detailed validator analysis
        st.divider()
        st.markdown("### Validators Seen as Slow by Multiple Observers")
        
        # Get validators seen by multiple observers
        multi_observer_validators = observer_consensus[observer_consensus['observer_count'] > 1].copy()
        
        # Calculate average propagation time per validator from slow attestations
        if 'validator_stats' in locals():
            multi_observer_validators = multi_observer_validators.merge(
                validator_stats[['attesting_validator_index', 'avg_propagation_time']], 
                on='attesting_validator_index', 
                how='left'
            )
        else:
            # Calculate from slow_observer_attestations
            validator_avg_times = slow_observer_attestations.groupby('attesting_validator_index')['propagation_time'].mean().reset_index()
            validator_avg_times.columns = ['attesting_validator_index', 'avg_propagation_time']
            multi_observer_validators = multi_observer_validators.merge(
                validator_avg_times,
                on='attesting_validator_index',
                how='left'
            )
        
        # Add entity and client info
        multi_observer_validators['entity'] = multi_observer_validators['attesting_validator_index'].map(
            lambda x: entities.get(x, 'unknown')
        )
        multi_observer_validators['client'] = multi_observer_validators['attesting_validator_index'].map(
            lambda x: clients.get(x, 'unknown')
        )
        
        # Sort by observer count
        multi_observer_validators = multi_observer_validators.sort_values('observer_count', ascending=False).head(20)
        
        # Format for display
        display_multi = multi_observer_validators[['attesting_validator_index', 'entity', 'client', 
                                                 'observer_count', 'avg_propagation_time']].copy()
        display_multi.columns = ['Validator Index', 'Entity', 'Client', 'Observer Count', 'Avg Time (ms)']
        display_multi['Avg Time (ms)'] = display_multi['Avg Time (ms)'].round(0).astype(int)
        
        st.dataframe(display_multi, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()