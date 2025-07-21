import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

# Import components
from config_utils import (
    get_metric_info, get_default_time_ranges, 
    get_supported_networks, get_grouping_options,
    get_data_source_options
)
from data_loaders import load_combined_analysis_data
from metrics_calculators import calculate_node_cdf_metrics
from plot_generators import create_cdf_comparison_plot

# Import shared components  
from shared.ui_components import apply_ethPandaOps_styling


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
    time_ranges = get_default_time_ranges()
    time_range_option = st.sidebar.selectbox(
        "Select Time Range",
        list(time_ranges.keys()),
        index=0,  # Default to "Last 1 Hour"
        help="Choose the time period for analysis"
    )
    
    # Calculate actual time range in UTC (database uses UTC)
    from datetime import timezone
    end_time = datetime.now(timezone.utc)
    start_time = end_time - time_ranges[time_range_option]
    
    # Custom time range option
    use_custom_range = st.sidebar.checkbox("Use Custom Time Range")
    if use_custom_range:
        col1, col2 = st.sidebar.columns(2)
        with col1:
            start_date = st.date_input("Start Date", start_time.date())
            start_time_input = st.time_input("Start Time", start_time.time())
        with col2:
            end_date = st.date_input("End Date", end_time.date())
            end_time_input = st.time_input("End Time", end_time.time())
        
        start_time = datetime.combine(start_date, start_time_input)
        end_time = datetime.combine(end_date, end_time_input)
    
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
    
    # Client filtering section
    st.sidebar.subheader("🔧 Client Filtering")
    
    # Client filtering controls - will be populated after data load
    client_filter_enabled = st.sidebar.checkbox("Enable Client Filtering", value=False)
    
    if client_filter_enabled:
        st.sidebar.info("Load data first to see available clients for filtering")
    
    # Data loading section
    st.sidebar.subheader("Data Loading")
    load_button = st.sidebar.button("🔄 Load Missed Slot Data", type="primary")
    
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
        
        # Client filtering controls now that data is loaded
        if client_filter_enabled:
            attestation_data = st.session_state.attestation_cdf_data['attestations']
            
            # Get unique client names and consensus implementations
            available_clients = sorted(attestation_data['meta_client_name'].unique())
            
            # Check if we have consensus implementation data
            if 'meta_consensus_implementation' in attestation_data.columns:
                available_implementations = sorted(attestation_data['meta_consensus_implementation'].unique())
            else:
                available_implementations = []
            
            with st.sidebar.expander("🎯 Select Clients to Include/Exclude"):
                # Client name filtering
                st.write("**Filter by Client Name:**")
                selected_clients = st.multiselect(
                    "Include only these clients (leave empty to include all):",
                    available_clients,
                    default=[],
                    key="selected_clients"
                )
                
                excluded_clients = st.multiselect(
                    "Exclude these clients:",
                    available_clients,
                    default=[],
                    key="excluded_clients"
                )
                
                # Consensus implementation filtering
                if available_implementations:
                    st.write("**Filter by Consensus Implementation:**")
                    selected_implementations = st.multiselect(
                        "Include only these implementations (leave empty to include all):",
                        available_implementations,
                        default=[],
                        key="selected_implementations"
                    )
                    
                    excluded_implementations = st.multiselect(
                        "Exclude these implementations:",
                        available_implementations,
                        default=[],
                        key="excluded_implementations"
                    )
                else:
                    selected_implementations = []
                    excluded_implementations = []
                    st.info("No consensus implementation data available in current dataset.")
            
            # Store filter settings in session state
            st.session_state.client_filters = {
                'enabled': True,
                'selected_clients': selected_clients,
                'excluded_clients': excluded_clients,
                'selected_implementations': selected_implementations,
                'excluded_implementations': excluded_implementations
            }
        else:
            # Clear filters when disabled
            st.session_state.client_filters = {'enabled': False}
    
    # Main dashboard content
    if st.session_state.attestation_cdf_data_loaded and st.session_state.attestation_cdf_metrics:
        render_analysis_dashboard(
            st.session_state.attestation_cdf_data,
            st.session_state.attestation_cdf_metrics,
            getattr(st.session_state, 'client_filters', {'enabled': False})
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
    
    # Update raw CDF metrics to match filtered data
    if 'raw_cdf' in filtered_metrics:
        raw_cdf = filtered_metrics['raw_cdf']
        
        # Handle both possible column names for backward compatibility
        group_column = 'group_name' if 'group_name' in raw_cdf.columns else 'meta_client_name'
        
        if group_column in raw_cdf.columns:
            # Filter by the same criteria
            if client_filters.get('selected_clients'):
                raw_cdf = raw_cdf[raw_cdf[group_column].isin(client_filters['selected_clients'])]
            if client_filters.get('excluded_clients'):
                raw_cdf = raw_cdf[~raw_cdf[group_column].isin(client_filters['excluded_clients'])]
            
            filtered_metrics['raw_cdf'] = raw_cdf
    
    return filtered_data, filtered_metrics


def render_analysis_dashboard(combined_data, cdf_metrics, client_filters=None):
    """Render the main analysis dashboard with optional client filtering."""
    
    # Apply client filtering if enabled
    if client_filters and client_filters.get('enabled', False):
        filtered_data, filtered_metrics = apply_client_filters(combined_data, cdf_metrics, client_filters)
        st.info(f"🔧 Client filtering applied. Showing filtered results.")
    else:
        filtered_data = combined_data
        filtered_metrics = cdf_metrics
    
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
            # Set plot title based on view mode
            if view_mode == "Per Slot" and slot_filter is not None:
                plot_title = f"Attestation Propagation CDF - Slot {slot_filter}"
            else:
                plot_title = "Attestation Propagation CDF - All Missed Slots"
            
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


if __name__ == "__main__":
    main()