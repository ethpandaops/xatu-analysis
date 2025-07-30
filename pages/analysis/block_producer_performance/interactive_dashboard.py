#!/usr/bin/env python3
"""
Interactive Block Producer Performance Dashboard

This Streamlit app provides an interactive interface for analyzing block producer performance metrics
including attestation packing efficiency from the Ethereum beacon chain. Users can select different 
parameters and view metrics dynamically.

Run with: streamlit run interactive_dashboard.py
"""

# Import all the split components
from config_utils import *
from data_loaders import (
    load_blockprint_clients,
    load_validators_from_ethseer,
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

# Import shared UI components
from shared.ui_components import apply_ethPandaOps_styling
from shared.filesystem import get_cache_dir

# Additional imports needed for main functionality
import streamlit as st
import shutil
import traceback
from datetime import datetime, timedelta, time
import pandas as pd
import numpy as np

def main():
    # Initialize session state variables
    if 'data_loaded' not in st.session_state:
        st.session_state.data_loaded = False
    if 'last_config' not in st.session_state:
        st.session_state.last_config = None
    if 'slot_metrics_df' not in st.session_state:
        st.session_state.slot_metrics_df = None
    if 'validators' not in st.session_state:
        st.session_state.validators = {}
    if 'entities' not in st.session_state:
        st.session_state.entities = {}
    
    # Header
    st.title("🏗️ Block Producer Performance")
    
    # Sidebar configuration
    st.sidebar.header("⚙️ Configuration")
    
    # Network selection
    from shared.config import get_supported_networks
    
    network = st.sidebar.selectbox(
        "Select Network",
        get_supported_networks(),
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
        custom_type = st.sidebar.radio(
            "Custom Range Type",
            ["Single Period", "Before/After Analysis"]
        )
        
        if custom_type == "Single Period":
            col1, col2 = st.sidebar.columns(2)
            with col1:
                start_date = st.date_input("Start Date")
                start_time = st.time_input("Start Time", help="Daily start time - applied to each day in range")
            with col2:
                end_date = st.date_input("End Date")
                end_time = st.time_input("End Time", help="Daily end time - applied to each day in range", value=time(14, 30))
            
            # Generate time ranges for each day in the date range
            time_ranges = []
            current_date = start_date
            while current_date <= end_date:
                day_start = datetime.combine(current_date, start_time).strftime("%Y-%m-%dT%H:%M:%SZ")
                day_end = datetime.combine(current_date, end_time).strftime("%Y-%m-%dT%H:%M:%SZ")
                time_ranges.append((day_start, day_end))
                current_date += timedelta(days=1)
            
            st.sidebar.info(f"📅 Will analyze {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')} for each day from {start_date} to {end_date} ({len(time_ranges)} day periods)")
            
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
                
                # Load ethseer validator entities (cached) - also uses ClickHouse
                st.info("Loading ethseer validator entities...")
                entities = load_validators_from_ethseer(network)
                st.session_state.entities = entities
                
                # Load attestation data from parquet files (cached)
                st.info("Loading attestation data from parquet files...")
                all_attestations = load_attestation_data_parquet(str(time_ranges), network, progress_callback=st.info)
                
                # Load proposer indices from parquet files (cached)
                st.info("Loading proposer indices from parquet files...")
                proposer_indices = fetch_proposer_indices_parquet(str(time_ranges), network, progress_callback=st.info)
                
                # Add client information to proposer indices
                proposer_indices['client'] = proposer_indices['proposer_index'].apply(
                    lambda x: validators.get(x, 'unknown')
                )
                
                # Add entity information to proposer indices
                proposer_indices['entity'] = proposer_indices['proposer_index'].apply(
                    lambda x: entities.get(x, 'unknown')
                )
                
                # Fill any remaining NaN values in client and entity columns
                proposer_indices['client'] = proposer_indices['client'].fillna('unknown')
                proposer_indices['entity'] = proposer_indices['entity'].fillna('unknown')
                
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
                        proposer_indices[['slot', 'proposer_index', 'client', 'entity']],
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
                    slot_metrics_df['entity'] = 'unknown'
                
                slot_metrics_df = slot_metrics_df.set_index('block_slot')
                
                # Fill any NaN values in client and entity columns that might have resulted from the merge
                slot_metrics_df['client'] = slot_metrics_df['client'].fillna('unknown')
                slot_metrics_df['entity'] = slot_metrics_df['entity'].fillna('unknown')
                
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
            if 'entity' in data.columns:
                entities_count = data['entity'].nunique()
                st.metric("⚡ Clients/Entities", f"{data['client'].nunique()}/{entities_count}", "Unique clients/entities")
            else:
                st.metric("⚡ Clients", data['client'].nunique(), "Unique consensus clients")
            
        with col3:
            st.metric("🌐 Network", network.upper(), "Ethereum network")
            
        with col4:
            st.metric("📅 Duration", f"{date_range_days} days", "Analysis period")
        
        st.write("")
        
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
        st.write("")
        
        # Handle potential NaT values in datetime columns
        min_date = data['block_slot_start_date_time'].dropna().min()
        max_date = data['block_slot_start_date_time'].dropna().max()
        
        if pd.notna(min_date) and pd.notna(max_date):
            date_range_str = f"{min_date.strftime('%Y-%m-%d %H:%M')} to {max_date.strftime('%Y-%m-%d %H:%M')}"
        else:
            date_range_str = "Date range unavailable"
        
        st.info(f"""
        📅 **Analysis Time Range:** {date_range_str}
        
        🔄 **Data Coverage:** {len(data):,} blocks across {date_range_days} days
        """)
        
        # Grouping type selection
        col1, col2 = st.columns(2)
        with col1:
            grouping_type = st.selectbox(
                "Group by",
                ["Blockprint Client", "Entity", "None"],
                help="Choose whether to group by blockprint client, entity, or view all data without grouping"
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
        
        # Add aggregate selection
        col1, col2 = st.columns(2)
        with col1:
            selected_aggregate = st.selectbox(
                "Select Aggregate",
                ["mean", "min", "p05", "p50", "p90", "p95", "p99", "max"],
                index=0,  # Default to mean
                help="Choose which statistical aggregate to display in visualizations"
            )
        with col2:
            show_network_average = st.checkbox(
                "Show Network Average",
                value=False,
                help="Add a baseline showing the network-wide average (all entities/clients combined) using the selected aggregation"
            )
        
        # Add annotation configuration
        st.subheader("📍 Chart Annotations")
        col1, col2 = st.columns(2)
        with col1:
            annotation_text = st.text_input(
                "Annotation Text",
                value="Pectra Fork",
                help="Text to display on charts at the specified date"
            )
        with col2:
            annotation_date = st.date_input(
                "Annotation Date",
                value=pd.to_datetime("2025-05-07").date(),
                help="Date to place the annotation on time-based charts"
            )
            annotation_time = st.time_input(
                "Annotation Time",
                value=pd.to_datetime("10:00:00").time(),
                help="Time to place the annotation"
            )
        
        # Combine date and time for annotation
        annotation_datetime = pd.to_datetime(datetime.combine(annotation_date, annotation_time), utc=True)
        
        # Initialize default values
        entity_selection_mode = "Top N Entities"
        top_n_entities = 10
        entities_to_show = []
        
        # Entity selection options (only shown when grouping by entity)
        if grouping_type == "Entity" and 'entity' in data.columns:
            st.subheader("🎯 Entity Selection")
            
            entity_selection_mode = st.radio(
                "Entity Selection Mode",
                ["Top N Entities", "Manual Selection"],
                help="Choose how to select entities for analysis"
            )
            
            if entity_selection_mode == "Top N Entities":
                col1, col2 = st.columns(2)
                with col1:
                    top_n_entities = st.selectbox(
                        "Top N Entities",
                        [5, 10, 20, 50, 100],
                        index=1,  # Default to 10
                        help="Select top N entities by block count to display"
                    )
                with col2:
                    # Show entity counts for reference
                    entity_counts = data['entity'].value_counts()
                    st.metric("📊 Total Entities", len(entity_counts), f"Available in dataset")
            else:
                # Manual selection mode
                entity_counts = data['entity'].value_counts()
                all_entities = entity_counts.index.tolist()
                
                # Search functionality
                search_term = st.text_input(
                    "🔍 Search Entities",
                    placeholder="Type to search entity names...",
                    help="Filter entities by name for easier selection"
                )
                
                # Filter entities based on search
                if search_term:
                    filtered_entities = [e for e in all_entities if search_term.lower() in str(e).lower()]
                else:
                    filtered_entities = all_entities
                
                # Show filtered count
                col1, col2 = st.columns(2)
                with col1:
                    st.info(f"📋 Showing {len(filtered_entities)} of {len(all_entities)} entities")
                with col2:
                    if st.button("🔄 Clear Search"):
                        st.rerun()
                
                # Manual entity selection with search results
                if len(filtered_entities) > 100:
                    st.warning(f"⚠️ Showing first 100 entities. Use search to narrow down selection.")
                    entities_to_show = filtered_entities[:100]
                else:
                    entities_to_show = filtered_entities
        
        # Group selection based on grouping type
        if grouping_type == "None":
            # When no grouping is selected, we'll use all data
            selected_groups = ["All Data"]
            group_column = None
        elif grouping_type == "Blockprint Client":
            available_groups = sorted([c for c in data['client'].unique() if pd.notna(c)])
            group_column = 'client'
            default_selection = available_groups[:5] if len(available_groups) > 5 else available_groups
            
            selected_groups = st.multiselect(
                f"Select {grouping_type}s to Analyze",
                available_groups,
                default=default_selection,
                help=f"Select which {grouping_type.lower()}s to include in the analysis"
            )
        else:  # Entity grouping
            if 'entity' in data.columns:
                group_column = 'entity'
                
                if entity_selection_mode == "Top N Entities":
                    # Get top N entities by block count
                    entity_counts = data['entity'].value_counts()
                    available_groups = entity_counts.head(top_n_entities).index.tolist()
                    default_selection = available_groups
                    
                    selected_groups = st.multiselect(
                        f"Select {grouping_type}s to Analyze",
                        available_groups,
                        default=default_selection,
                        help=f"Top {top_n_entities} entities by block count. Uncheck to exclude from analysis."
                    )
                else:  # Manual selection
                    # Show entity counts for better selection
                    st.write("**Entity Selection with Block Counts:**")
                    
                    # Quick selection helpers
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button("📈 Select Top 10"):
                            top_10_entities = entity_counts.head(10).index.tolist()
                            st.session_state.manual_entity_selection = [f"{entity} ({entity_counts[entity]:,} blocks)" for entity in top_10_entities if entity in entities_to_show]
                    with col2:
                        if st.button("🎯 Select Top 20"):
                            top_20_entities = entity_counts.head(20).index.tolist()
                            st.session_state.manual_entity_selection = [f"{entity} ({entity_counts[entity]:,} blocks)" for entity in top_20_entities if entity in entities_to_show]
                    with col3:
                        if st.button("🗑️ Clear Selection"):
                            st.session_state.manual_entity_selection = []
                    
                    # Create a more informative list with counts
                    entity_info = []
                    for entity in entities_to_show:
                        count = entity_counts[entity]
                        entity_info.append(f"{entity} ({count:,} blocks)")
                    
                    # Get current selection from session state
                    current_selection = getattr(st.session_state, 'manual_entity_selection', [])
                    
                    # Multiple selection with checkboxes
                    selected_entity_info = st.multiselect(
                        f"Select {grouping_type}s to Analyze",
                        entity_info,
                        default=current_selection,
                        help="Select specific entities for analysis. Numbers show block counts. Use buttons above for quick selection."
                    )
                    
                    # Store selection in session state for quick selection buttons
                    st.session_state.manual_entity_selection = selected_entity_info
                    
                    # Extract entity names from the selected info
                    selected_groups = []
                    for info in selected_entity_info:
                        entity_name = info.split(' (')[0]  # Extract name before the count
                        selected_groups.append(entity_name)
            else:
                st.warning("Entity data not available. Loading entity data...")
                available_groups = []
                group_column = 'entity'
                selected_groups = []
        
        if selected_groups:
            # Plot selection
            st.subheader("📈 Visualizations")
            
            plot_type = st.selectbox(
                "Select Plot Type",
                ["Before/After Comparison", "Distribution", "Time Series", "Inclusion Distance Distribution"]
            )
            
            # Use the appropriate column for plotting
            if grouping_type == "Blockprint Client":
                plot_group_column = 'client'
            elif grouping_type == "Entity":
                plot_group_column = 'entity'
            else:  # No grouping
                plot_group_column = None
            
            if plot_type == "Before/After Comparison":
                fig = create_before_after_comparison(data, selected_metric, selected_groups, event_date, group_column=plot_group_column, aggregate=selected_aggregate, annotation_date=annotation_datetime, annotation_text=annotation_text, show_network_average=show_network_average)
                st.plotly_chart(fig, use_container_width=True)
                
            elif plot_type == "Distribution":
                fig = create_distribution_plot(data, selected_metric, selected_groups, event_date, group_column=plot_group_column, aggregate=selected_aggregate, annotation_date=annotation_datetime, annotation_text=annotation_text, show_network_average=show_network_average)
                st.plotly_chart(fig, use_container_width=True)
                
            elif plot_type == "Time Series":
                fig = create_time_series_plot(data, selected_metric, selected_groups, event_date, group_column=plot_group_column, aggregate=selected_aggregate, annotation_date=annotation_datetime, annotation_text=annotation_text, show_network_average=show_network_average)
                st.plotly_chart(fig, use_container_width=True)
                
            elif plot_type == "Inclusion Distance Distribution":
                fig = create_inclusion_distance_distribution(data, selected_groups, event_date, group_column=plot_group_column, annotation_date=annotation_datetime, annotation_text=annotation_text, show_network_average=show_network_average)
                st.plotly_chart(fig, use_container_width=True)
            
            # Add period information for before/after analysis
            temp_df = data.copy()
            temp_df['datetime'] = pd.to_datetime(temp_df['block_slot_start_date_time'])
            event_date_naive = pd.Timestamp(event_date).tz_localize(None) if hasattr(event_date, 'tzinfo') and event_date.tzinfo is not None else event_date
            temp_df['period'] = np.where(temp_df['datetime'] < event_date_naive, 'Before', 'After')
            
            # Map p-values to pandas quantile functions
            agg_functions = {
                'count': 'count',
                'mean': 'mean', 
                'median': 'median',
                'std': 'std',
                'min': 'min',
                'max': 'max',
                'p05': lambda x: x.quantile(0.05),
                'p50': lambda x: x.quantile(0.50),
                'p90': lambda x: x.quantile(0.90),
                'p95': lambda x: x.quantile(0.95),
                'p99': lambda x: x.quantile(0.99)
            }
            
            # Helper function to make column names human-friendly
            def humanize_stat_name(stat_name):
                name_map = {
                    'count': 'Count',
                    'mean': 'Mean',
                    'median': 'Median',
                    'std': 'Std Dev',
                    'min': 'Min',
                    'max': 'Max',
                    'p05': 'P05',
                    'p50': 'P50',
                    'p90': 'P90',
                    'p95': 'P95',
                    'p99': 'P99'
                }
                return name_map.get(stat_name, stat_name.title())
            
            if grouping_type == "None":
                # Show stats for all data without grouping, but with before/after
                filtered_data = temp_df
                stats = filtered_data.groupby('period')[selected_metric].agg(list(agg_functions.values()))
                stats.columns = list(agg_functions.keys())
                # Reindex to ensure Before comes before After
                stats = stats.reindex(['Before', 'After'])
                # Transpose so periods are columns
                stats = stats.T
                # Apply rounding and format to 2 decimal places
                stats = stats.round(2)
                # Format all values to 2 decimal places
                stats = stats.applymap(lambda x: f"{x:.2f}" if pd.notna(x) else "")
                # Rename columns to be more human-friendly
                stats.columns = [f"{period}" for period in stats.columns]
                # Rename index to be more human-friendly
                stats.index = [humanize_stat_name(stat) for stat in stats.index]
            else:
                filtered_data = temp_df[temp_df[group_column].isin(selected_groups)]
                # Calculate statistics by group and period
                stats = filtered_data.groupby([group_column, 'period'])[selected_metric].agg(list(agg_functions.values()))
                stats.columns = list(agg_functions.keys())
                # Unstack to get periods as columns, ensuring Before comes before After
                stats = stats.unstack('period')
                # Reorder columns to ensure Before comes before After
                if 'Before' in stats.columns.get_level_values(1) and 'After' in stats.columns.get_level_values(1):
                    stats = stats.reindex(['Before', 'After'], axis=1, level=1)
                # Apply rounding and format to 2 decimal places
                stats = stats.round(2)
                # Format all values to 2 decimal places
                stats = stats.applymap(lambda x: f"{x:.2f}" if pd.notna(x) else "")
                # Flatten column names and make them human-friendly
                stats.columns = [f"{humanize_stat_name(stat)} ({period.lower()})" for stat, period in stats.columns]
            
            # Style the dataframe to highlight the selected aggregate
            def highlight_selected_aggregate(styler):
                # Get the human-friendly name for the selected aggregate
                selected_human_name = humanize_stat_name(selected_aggregate)
                
                if grouping_type == "None":
                    # For ungrouped data, highlight the exact row matching the selected aggregate
                    return styler.apply(lambda x: ['font-weight: bold' if x.name == selected_human_name else '' for _ in x], axis=1)
                else:
                    # For grouped data, highlight columns that start with the selected aggregate
                    def highlight_cells(_):
                        return 'font-weight: bold'
                    
                    # Apply highlighting to columns that contain the selected aggregate
                    selected_columns = [col for col in stats.columns if selected_human_name.lower() in col.lower()]
                    if selected_columns:
                        return styler.applymap(highlight_cells, subset=selected_columns)
                    else:
                        return styler
            
            st.dataframe(stats.style.pipe(highlight_selected_aggregate), use_container_width=True)
            
            # Raw data explorer
            st.subheader("🔍 Raw Data Explorer")
            
            if st.checkbox("Show raw data"):
                if grouping_type == "None":
                    columns_to_show = ['block_slot_start_date_time', selected_metric]
                else:
                    columns_to_show = [group_column, 'block_slot_start_date_time', selected_metric]
                st.dataframe(
                    filtered_data[columns_to_show].head(100),
                    use_container_width=True
                )
        
        else:
            st.warning(f"Please select at least one {grouping_type.lower()} to analyze.")
    
    else:
        st.info("👈 Please configure your parameters in the sidebar and click 'Load Data' to begin analysis.")
        
        st.markdown("""
        
        1. Configure your network and time range in the sidebar
        2. Click "Load Data" to fetch from ClickHouse
        3. Select clients and metrics to analyze
        4. Choose visualization type and explore!
        """)



if __name__ == "__main__":
    main()
