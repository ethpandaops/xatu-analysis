#!/usr/bin/env python3
"""
Interactive Attestation Packing Analysis Dashboard

This Streamlit app provides an interactive interface for analyzing attestation packing metrics
from the Ethereum beacon chain. Users can select different parameters and view metrics dynamically.

Run with: streamlit run interactive_dashboard.py
"""

# Import all the split components
from config_utils import *
from data_loaders import (
    load_blockprint_clients,
    load_attestation_data_parquet, 
    fetch_proposer_indices_parquet
)
from metrics_calculators import (
    calculate_first_seen_attestations,
    calculate_slot_metrics
)
from plot_generators import (
    create_before_after_comparison,
    create_distribution_plot,
    create_time_series_plot,
    create_inclusion_distance_distribution
)

# Additional imports needed for main functionality
import shutil
import traceback

def main():
    
    # Header
    st.markdown('<h1 class="main-header">🔍 Attestation Packing Analysis Dashboard</h1>', unsafe_allow_html=True)
    
    # Sidebar configuration
    st.sidebar.header("⚙️ Configuration")
    
    # Network selection
    network = st.sidebar.selectbox(
        "Select Network",
        ["mainnet", "holesky", "sepolia"],
        index=0
    )
    
    # Time range configuration
    st.sidebar.subheader("Time Range Configuration")
    
    # Predefined time ranges
    time_range_option = st.sidebar.selectbox(
        "Select Time Range",
        ["Custom", "Mainnet Electra Fork Analysis (May 2025)", "Recent Week", "Recent Month"]
    )
    
    if time_range_option == "Mainnet Electra Fork Analysis (May 2025)":
        time_ranges = [
            ("2025-05-01T12:10:00Z", "2025-05-01T18:10:00Z"),  # Pre-Electra
            ("2025-05-20T12:10:00Z", "2025-05-20T18:10:00Z")   # Post-Electra
        ]
        event_date = pd.to_datetime("2025-05-07T10:00:00Z", utc=True)
    elif time_range_option == "Custom":
        st.sidebar.info("⚠️ Custom ranges download ALL days between start/end. For analysis, use 2 separate short periods.")
        
        custom_type = st.sidebar.radio(
            "Custom Range Type",
            ["Single Period", "Before/After Analysis"]
        )
        
        if custom_type == "Single Period":
            col1, col2 = st.sidebar.columns(2)
            with col1:
                start_date = st.date_input("Start Date")
                start_time = st.time_input("Start Time")
            with col2:
                end_date = st.date_input("End Date")
                end_time = st.time_input("End Time")
            
            start_datetime = datetime.combine(start_date, start_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            end_datetime = datetime.combine(end_date, end_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            time_ranges = [(start_datetime, end_datetime)]
            
            event_date_input = st.sidebar.date_input("Event Date (for Before/After)")
            event_time_input = st.sidebar.time_input("Event Time")
            event_date = pd.to_datetime(datetime.combine(event_date_input, event_time_input), utc=True)
        
        else:  # Before/After Analysis
            st.sidebar.write("**Before Period:**")
            col1, col2 = st.sidebar.columns(2)
            with col1:
                before_start_date = st.date_input("Before Start Date")
                before_start_time = st.time_input("Before Start Time")
            with col2:
                before_end_date = st.date_input("Before End Date")
                before_end_time = st.time_input("Before End Time")
            
            st.sidebar.write("**After Period:**")
            col1, col2 = st.sidebar.columns(2)
            with col1:
                after_start_date = st.date_input("After Start Date")
                after_start_time = st.time_input("After Start Time")
            with col2:
                after_end_date = st.date_input("After End Date")
                after_end_time = st.time_input("After End Time")
            
            before_start = datetime.combine(before_start_date, before_start_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            before_end = datetime.combine(before_end_date, before_end_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            after_start = datetime.combine(after_start_date, after_start_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            after_end = datetime.combine(after_end_date, after_end_time).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            time_ranges = [(before_start, before_end), (after_start, after_end)]
            
            # Event date is between the two periods
            event_date = pd.to_datetime(datetime.combine(after_start_date, after_start_time), utc=True)
    else:
        st.sidebar.warning("Other time ranges not implemented yet. Using Mainnet Electra Fork Analysis.")
        time_ranges = [
            ("2025-05-01T12:10:00Z", "2025-05-01T18:10:00Z"),  # Pre-Electra
            ("2025-05-20T12:10:00Z", "2025-05-20T18:10:00Z")   # Post-Electra
        ]
        event_date = pd.to_datetime("2025-05-07T10:00:00Z", utc=True)
    
    # Data loading section
    st.sidebar.subheader("Data Loading")
    
    # Add cache management
    cache_dir = get_cache_dir()
    
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("🗑️ Clear Cache"):
            st.cache_data.clear()
            # Also clear parquet file cache
            import shutil
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
                cache_dir.mkdir(parents=True, exist_ok=True)
            st.sidebar.success("Cache cleared!")
    
    with col2:
        # Show cache size
        cache_size = 0
        if cache_dir.exists():
            for file in cache_dir.glob("*.parquet"):
                cache_size += file.stat().st_size
        cache_size_mb = cache_size / (1024 * 1024)
        st.write(f"💾 {cache_size_mb:.1f}MB")
        
    st.sidebar.info("💡 Parquet files cached locally for faster re-use • Data cached for 1 hour")
    
    # Check if configuration changed
    current_config = (network, str(time_ranges), event_date)
    config_changed = st.session_state.last_config != current_config
    
    if config_changed and st.session_state.data_loaded:
        st.sidebar.warning("⚠️ Configuration changed. Click 'Load Data' to refresh.")
        st.session_state.data_loaded = False
    
    if st.sidebar.button("🔄 Load Data", type="primary"):
        with st.spinner("Loading data from Xatu parquet files..."):
            try:
                # Load blockprint clients (cached) - still uses ClickHouse for client mapping
                st.info("Loading blockprint clients...")
                validators = load_blockprint_clients(network)
                st.session_state.validators = validators
                
                # Load attestation data from parquet files (cached)
                st.info("Loading attestation data from parquet files...")
                all_attestations = load_attestation_data_parquet(str(time_ranges), network)
                
                # Load proposer indices from parquet files (cached)
                st.info("Loading proposer indices from parquet files...")
                proposer_indices = fetch_proposer_indices_parquet(str(time_ranges), network)
                
                # Add client information to proposer indices
                proposer_indices['client'] = proposer_indices['proposer_index'].apply(
                    lambda x: validators.get(x, 'unknown')
                )
                
                # Fill any remaining NaN values in client column
                proposer_indices['client'] = proposer_indices['client'].fillna('unknown')
                
                # Calculate basic slot metrics
                st.info("Calculating slot metrics...")
                slot_metrics_df = all_attestations.groupby('block_slot').apply(calculate_slot_metrics, include_groups=False)
                
                # Calculate first seen attestations with rolling window
                st.info("Calculating first seen attestations...")
                first_seen_counts = calculate_first_seen_attestations(all_attestations)
                
                # Reset index and merge with proposer data
                slot_metrics_df = slot_metrics_df.reset_index()
                
                # Add first seen attestations data
                slot_metrics_df['first_seen_attestations'] = slot_metrics_df['block_slot'].map(first_seen_counts).fillna(0)
                
                if len(proposer_indices) > 0:
                    slot_metrics_df = pd.merge(
                        slot_metrics_df,
                        proposer_indices[['slot', 'proposer_index', 'client']],
                        left_on='block_slot',
                        right_on='slot',
                        how='left'
                    )
                    # Drop the duplicate slot column if it exists
                    if 'slot' in slot_metrics_df.columns:
                        slot_metrics_df = slot_metrics_df.drop('slot', axis=1)
                else:
                    # If no proposer indices, add default columns
                    slot_metrics_df['proposer_index'] = None
                    slot_metrics_df['client'] = 'unknown'
                
                slot_metrics_df = slot_metrics_df.set_index('block_slot')
                
                # Fill any NaN values in client column that might have resulted from the merge
                slot_metrics_df['client'] = slot_metrics_df['client'].fillna('unknown')
                
                # Store in session state
                st.session_state.slot_metrics_df = slot_metrics_df
                st.session_state.data_loaded = True
                st.session_state.last_config = current_config
                
                st.success(f"✅ Data loaded successfully! {len(slot_metrics_df)} blocks analyzed.")
                
            except Exception as e:
                st.error(f"Error loading data: {e}")
                import traceback
                st.error(f"Full error: {traceback.format_exc()}")
    
    # Main content area
    if st.session_state.data_loaded and st.session_state.slot_metrics_df is not None:
        data = st.session_state.slot_metrics_df
        
        # Display enhanced data summary
        st.markdown("---")
        st.markdown("### 📊 Data Summary")
        
        # Calculate additional summary stats
        date_range_days = (data['block_slot_start_date_time'].max() - data['block_slot_start_date_time'].min()).days + 1
        avg_blocks_per_hour = len(data) / (date_range_days * 24) if date_range_days > 0 else 0
        
        # Before/After split for analysis
        temp_df = data.copy()
        temp_df['datetime'] = pd.to_datetime(temp_df['block_slot_start_date_time'])
        event_date_naive = pd.Timestamp(event_date).tz_localize(None) if hasattr(event_date, 'tzinfo') and event_date.tzinfo is not None else event_date
        before_count = len(temp_df[temp_df['datetime'] < event_date_naive])
        after_count = len(temp_df[temp_df['datetime'] >= event_date_naive])
        
        # Top row - main metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("🏗️ Total Blocks", f"{len(data):,}", "Analyzed")
            
        with col2:
            st.metric("⚡ Clients", data['client'].nunique(), "Unique consensus clients")
            
        with col3:
            st.metric("🌐 Network", network.upper(), "Ethereum network")
            
        with col4:
            st.metric("📅 Duration", f"{date_range_days} days", "Analysis period")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Second row - analysis-specific metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("📈 Before Event", f"{before_count:,}", "Blocks pre-event")
            
        with col2:
            st.metric("📉 After Event", f"{after_count:,}", "Blocks post-event")
            
        with col3:
            st.metric("⏰ Event Date", event_date.strftime("%b %d, %Y"), "Analysis split point")
            
        with col4:
            st.metric("📊 Block Rate", f"{avg_blocks_per_hour:.1f}/hr", "Average frequency")
        
        # Date range info
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Handle potential NaT values in datetime columns
        min_date = data['block_slot_start_date_time'].dropna().min()
        max_date = data['block_slot_start_date_time'].dropna().max()
        
        if pd.notna(min_date) and pd.notna(max_date):
            date_range_str = f"{min_date.strftime('%Y-%m-%d %H:%M')} to {max_date.strftime('%Y-%m-%d %H:%M')}"
        else:
            date_range_str = "Date range unavailable"
        
        st.markdown("""
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 10px; border-left: 4px solid #1f77b4;">
            <strong>📅 Analysis Time Range:</strong> {} 
            <br><strong>🔄 Data Coverage:</strong> {} blocks across {} days
        </div>
        """.format(
            date_range_str,
            len(data),
            date_range_days
        ), unsafe_allow_html=True)
        
        # Client selection
        st.subheader("🎯 Analysis Configuration")
        
        available_clients = sorted([c for c in data['client'].unique() if pd.notna(c)])
        
        col1, col2 = st.columns(2)
        with col1:
            selected_clients = st.multiselect(
                "Select Clients to Analyze",
                available_clients,
                default=available_clients[:5] if len(available_clients) > 5 else available_clients
            )
        
        with col2:
            selected_metric = st.selectbox(
                "Select Metric",
                [
                    # Core blog post metrics
                    "unique_validator_indexes",
                    "first_seen_attestations", 
                    "avg_attestation_inclusion_delay",
                    "optimal_inclusion_rate",
                    
                    # Additional inclusion delay metrics
                    "min_attestation_inclusion_delay",
                    "p50_attestation_inclusion_delay",
                    "p95_attestation_inclusion_delay",
                    "max_attestation_inclusion_delay",
                    
                    # Aggregation metrics
                    "aggregation_efficiency",
                    "total_attestations",
                    "avg_validators_per_attestation",
                    "optimal_inclusion_validators"
                ]
            )
        
        if selected_clients:
            # Plot selection
            st.subheader("📈 Visualizations")
            
            plot_type = st.selectbox(
                "Select Plot Type",
                ["Before/After Comparison", "Distribution", "Time Series", "Inclusion Distance Distribution"]
            )
            
            if plot_type == "Before/After Comparison":
                fig = create_before_after_comparison(data, selected_metric, selected_clients, event_date)
                st.plotly_chart(fig, use_container_width=True)
                
            elif plot_type == "Distribution":
                fig = create_distribution_plot(data, selected_metric, selected_clients, event_date)
                st.plotly_chart(fig, use_container_width=True)
                
            elif plot_type == "Time Series":
                fig = create_time_series_plot(data, selected_metric, selected_clients, event_date)
                st.plotly_chart(fig, use_container_width=True)
                
            elif plot_type == "Inclusion Distance Distribution":
                fig = create_inclusion_distance_distribution(data, selected_clients, event_date)
                st.plotly_chart(fig, use_container_width=True)
            
            # Statistics table
            st.subheader("📋 Statistics Summary")
            
            filtered_data = data[data['client'].isin(selected_clients)]
            
            # Calculate statistics by client
            stats = filtered_data.groupby('client')[selected_metric].agg([
                'count', 'mean', 'median', 'std', 'min', 'max'
            ]).round(3)
            
            st.dataframe(stats, use_container_width=True)
            
            # Raw data explorer
            st.subheader("🔍 Raw Data Explorer")
            
            if st.checkbox("Show raw data"):
                st.dataframe(
                    filtered_data[['client', 'block_slot_start_date_time', selected_metric]].head(100),
                    use_container_width=True
                )
        
        else:
            st.warning("Please select at least one client to analyze.")
    
    else:
        st.info("👆 Please configure your parameters in the sidebar and click 'Load Data' to begin analysis.")
        
        # Show example/demo data structure
        st.subheader("📝 About This Dashboard")
        
        st.markdown("""
        This interactive dashboard allows you to analyze Ethereum attestation packing metrics across different:
        
        - **Networks**: mainnet, holesky, sepolia
        - **Time Ranges**: Custom or predefined ranges around key events (e.g., Electra fork)
        - **Clients**: Different consensus client implementations (lighthouse, prysm, teku, etc.)
        - **Metrics**: Comprehensive attestation packing and efficiency metrics
        
        ### Key Metrics Available (based on [EthPandaOps blog analysis](https://ethpandaops.io/posts/hoodi-attestation-packing/)):
        
        **🎯 Core Attestation Packing Metrics:**
        - **Unique Validator Indexes**: Number of unique validators per block (blog: "Unique Validators Per Block")
        - **First Seen Attestations**: Fresh attestations not seen in previous blocks (blog: "Fresh Attestations")
        - **Avg Attestation Inclusion Delay**: Average delay in slots (blog: "Inclusion Distance")
        - **Optimal Inclusion Rate**: Percentage of validators included with 1-slot delay (blog: "Optimal Inclusion Distance")
        
        **📊 Additional Analysis Metrics:**
        - **Aggregation Efficiency**: Ratio of unique validators to total attestations
        - **Total Attestations**: Number of attestations per block
        - **Avg Validators per Attestation**: Average aggregation size
        - **Optimal Inclusion Validators**: Count of validators with 1-slot delay
        
        ### Getting Started:
        
        1. Configure your network and time range in the sidebar
        2. Click "Load Data" to fetch from ClickHouse
        3. Select clients and metrics to analyze
        4. Choose visualization type and explore!
        """)



if __name__ == "__main__":
    main()
