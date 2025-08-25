"""
Interactive Chain Reorganization Analysis Dashboard - Common Reorgs Focus
"""
import streamlit as st
import polars as pl
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np

# Import components
from config_utils import (
    get_metric_info, get_default_time_ranges, 
    get_depth_filter_config, get_aggregation_options
)
from data_loaders import (
    load_reorg_data, load_missed_slots_data, 
    load_reorg_episodes, load_client_metadata,
    deduplicate_reorg_events
)
from metrics_calculators import (
    calculate_basic_metrics, calculate_client_metrics,
    calculate_implementation_metrics, calculate_episode_metrics, 
    calculate_epoch_boundary_effects, correlate_with_missed_slots, 
    calculate_geographic_distribution
)
from plot_generators import (
    create_reorg_timeline, create_depth_distribution,
    create_client_comparison, create_epoch_boundary_heatmap,
    create_scatter_matrix, create_geographic_distribution
)
from shared.ui_components import add_ethPandaOps_logo, get_ethPandaOps_chart_config
from reorg_normalizer import (
    normalize_reorg_events, get_reorg_consensus_over_time,
    identify_significant_reorgs
)

# Import shared components  
from shared.ui_components import apply_ethPandaOps_styling
from shared.header import render_global_header, get_global_cluster, get_global_network

def main():
    """Main dashboard function."""
    
    # Render the global header
    render_global_header()
    
    # Apply consistent styling
    apply_ethPandaOps_styling()
    
    # Initialize session state
    if 'reorg_data_loaded' not in st.session_state:
        st.session_state.reorg_data_loaded = False
    if 'reorg_data' not in st.session_state:
        st.session_state.reorg_data = None
    if 'reorg_metrics' not in st.session_state:
        st.session_state.reorg_metrics = None
    
    # Header
    st.markdown('<h1 class="main-header">🔄 Chain Reorganization Analysis</h1>', unsafe_allow_html=True)
    st.markdown("""
    <div class="header-description">
    Analyze blockchain reorganization events across the Ethereum network. 
    Track reorg frequency, depth distribution, and identify patterns that may indicate network instability.
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
    
    # Time range selection
    use_custom_range = st.sidebar.checkbox("Use Custom Time Range")
    
    if not use_custom_range:
        time_ranges = get_default_time_ranges()
        time_range_option = st.sidebar.selectbox(
            "Select Time Range",
            list(time_ranges.keys()),
            index=5,  # Default to "Last 7 Days"
            help="Choose the time period for analysis"
        )
        
        end_time = datetime.now(timezone.utc)
        start_time = end_time - time_ranges[time_range_option]
    else:
        # Custom time range inputs
        default_end = datetime.now(timezone.utc)
        default_start = default_end - timedelta(days=7)
        
        col1, col2 = st.sidebar.columns(2)
        with col1:
            start_date = st.date_input(
                "Start Date", 
                value=default_start.date(),
                min_value=datetime(2020, 12, 1).date(),
                max_value=datetime.now(timezone.utc).date()
            )
            start_time_input = st.time_input("Start Time", value=default_start.time())
        with col2:
            end_date = st.date_input(
                "End Date",
                value=default_end.date(),
                min_value=datetime(2020, 12, 1).date(),
                max_value=datetime.now(timezone.utc).date()
            )
            end_time_input = st.time_input("End Time", value=default_end.time())
        
        # Combine date and time
        start_time = datetime.combine(start_date, start_time_input).replace(tzinfo=timezone.utc)
        end_time = datetime.combine(end_date, end_time_input).replace(tzinfo=timezone.utc)
    
    # Display selected time range
    st.sidebar.info(f"**Time Range:**\n{start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')} UTC")
    
    # Depth filter
    st.sidebar.subheader("Depth Filtering")
    depth_config = get_depth_filter_config()
    
    exclude_invalid = st.sidebar.checkbox(
        "Exclude Invalid Depths",
        value=True,
        help="Filter out known invalid depth values (e.g., integer overflows)"
    )
    
    max_depth = st.sidebar.slider(
        "Maximum Depth",
        min_value=1,
        max_value=depth_config['default_max_depth'],
        value=depth_config['default_max_depth'],
        help="Filter out reorgs deeper than this value"
    )
    
    # Include ethpandaops nodes option
    include_ethpandaops = st.sidebar.checkbox(
        "Include ethpandaops nodes",
        value=False,
        help="Include ethpandaops nodes in the analysis (default: excluded)"
    )
    
    # Slot Position Filter
    st.sidebar.subheader("Slot Position Filtering")
    filter_by_slot_position = st.sidebar.checkbox(
        "Filter by Slot Position",
        value=False,
        help="Show only reorgs where blocks at specific positions within an epoch (0-31) were reorged out"
    )
    
    slot_position_filter = None
    if filter_by_slot_position:
        slot_position_filter = st.sidebar.selectbox(
            "Slot Position in Epoch",
            options=list(range(32)),
            format_func=lambda x: f"Position {x}" + (" (epoch start)" if x == 0 else " (epoch end)" if x == 31 else ""),
            help="Select the slot position within the epoch (0-31). This filters reorgs based on the position of the block that was reorged out."
        )
    
    # Set default values for previously advanced options
    time_bucket = "1 hour"  # Default value
    episode_window = 4  # Default value in seconds
    
    # Load Data button
    if st.sidebar.button("🔄 Load Data", type="primary", use_container_width=True):
        with st.spinner("Loading reorg data..."):
            try:
                # Load raw reorg data
                raw_df = load_reorg_data(
                    start_time, end_time,
                    network=network,
                    cluster=cluster,
                    max_depth=max_depth,
                    exclude_invalid=exclude_invalid,
                    include_ethpandaops=include_ethpandaops
                )
                
                if raw_df.is_empty():
                    st.error("No reorg data found for the selected time range")
                    return
                
                # Apply slot position filter if enabled
                if slot_position_filter is not None:
                    original_count = len(raw_df)
                    raw_df = raw_df.filter(pl.col("slot_in_epoch") == slot_position_filter)
                    filtered_count = original_count - len(raw_df)
                    
                    if raw_df.is_empty():
                        st.error(f"No reorgs found at slot position {slot_position_filter}")
                        return
                    
                    st.info(f"🎯 Filtered to slot position {slot_position_filter}: {len(raw_df)} reorgs found (filtered out {filtered_count} reorgs at other positions)")
                
                # Normalize reorg events to identify common events
                normalized_df, event_clusters = normalize_reorg_events(
                    raw_df,
                    time_window_seconds=60,  # 60s window for grouping
                    match_old_head=False
                )
                
                # Load episode data
                episode_df = load_reorg_episodes(raw_df, episode_window)
                
                # Load missed slots data for correlation
                missed_slots_df = load_missed_slots_data(
                    start_time, end_time,
                    network=network,
                    cluster=cluster
                )
                
                # Store data in session state
                st.session_state.reorg_data = {
                    'raw': raw_df,
                    'normalized': normalized_df,
                    'event_clusters': event_clusters,
                    'episodes': episode_df,
                    'missed_slots': missed_slots_df
                }
                st.session_state.reorg_data_loaded = True
                
                # Calculate metrics
                metrics = {
                    'basic': calculate_basic_metrics(raw_df),
                    'client': calculate_client_metrics(raw_df),
                    'implementation': calculate_implementation_metrics(raw_df),
                    'episodes': calculate_episode_metrics(episode_df),
                    'boundary_effects': calculate_epoch_boundary_effects(raw_df),
                    'correlation': correlate_with_missed_slots(raw_df, missed_slots_df),
                    'geographic': calculate_geographic_distribution(raw_df)
                }
                st.session_state.reorg_metrics = metrics
                
                # Create success message with optional slot position info
                success_msg = f"✅ Loaded {len(raw_df)} reorg events"
                if slot_position_filter is not None:
                    success_msg += f" at slot position {slot_position_filter}"
                st.success(success_msg)
                
            except Exception as e:
                st.error(f"Error loading data: {str(e)}")
                return
    
    # Check if data is loaded
    if not st.session_state.reorg_data_loaded:
        st.info("👈 Please configure parameters and click 'Load Data' to begin analysis")
        return
    
    data = st.session_state.reorg_data
    metrics = st.session_state.reorg_metrics
    
    
    # Reorg Analysis
    st.header("🔄 Reorg Analysis")
    
    if 'normalized' in data and not data['normalized'].is_empty():
        # Ensure active_node_count exists in normalized data
        if "active_node_count" not in data['normalized'].columns:
            st.error("Active node count data is missing. Cannot proceed with analysis.")
            return
        
        # Calculate observer percentage using active node counts
        normalized_df = data['normalized'].with_columns([
            (pl.col("observer_count") / pl.col("active_node_count") * 100).round(1).alias("observer_percentage")
        ])
        
        # Get average active nodes for display
        avg_active_nodes = normalized_df['active_node_count'].mean()
        total_nodes = int(avg_active_nodes) if avg_active_nodes else 100
        
        # Display active node information
        st.info(f"📊 **Active Nodes**: Average of {total_nodes} nodes were active during reorg events (based on block production within ±5 minutes)")
        
        # Filter options
        col1, col2, col3 = st.columns(3)
        with col1:
            min_observers = st.slider(
                "Minimum Observers",
                min_value=1,
                max_value=min(20, total_nodes),
                value=1,
                help="Show only reorgs seen by at least this many nodes"
            )
        with col2:
            min_depth_filter = st.slider(
                "Minimum Depth",
                min_value=1,
                max_value=10,
                value=1,
                help="Show only reorgs of at least this depth"
            )
        with col3:
            show_percentage = st.checkbox(
                "Show as Percentage",
                value=True,
                help="Display observer count as percentage of active nodes"
            )
        
        # Filter the normalized data
        filtered_normalized = normalized_df.filter(
            (pl.col("observer_count") >= min_observers) &
            (pl.col("consensus_depth") >= min_depth_filter)
        )
        
        if not filtered_normalized.is_empty():
            # Create the new heatmap visualizations
            render_reorg_heatmaps(filtered_normalized, total_nodes)
            
            # Add data download section
            st.divider()
            st.subheader("📥 Download Detailed Data")
            
            # Define all known implementations
            known_implementations = [
                "lighthouse", "prysm", "teku", "nimbus", 
                "lodestar", "grandine", "caplin"
            ]
            
            # Check if we have event clusters for implementation details
            has_event_clusters = "event_clusters" in data and not data["event_clusters"].is_empty()
            
            # If we have event clusters, calculate implementation counts
            if has_event_clusters:
                # Join event clusters to get implementation counts per cluster
                impl_data = data["event_clusters"].join(
                    data["raw"].select(["meta_client_name", "meta_consensus_implementation"]).unique(),
                    left_on="meta_client_name",
                    right_on="meta_client_name",
                    how="left"
                ).group_by(["cluster_id", "meta_consensus_implementation"]).agg(
                    pl.count().alias("count")
                ).pivot(
                    values="count",
                    index="cluster_id",
                    columns="meta_consensus_implementation",
                    aggregate_function="first"
                ).fill_null(0)
                
                # Ensure all implementation columns exist
                for impl in known_implementations:
                    col_name = f"{impl}_observers"
                    if impl not in impl_data.columns:
                        impl_data = impl_data.with_columns(
                            pl.lit(0).cast(pl.Int32).alias(impl)
                        )
                    if impl in impl_data.columns:
                        impl_data = impl_data.rename({impl: col_name})
                
                # Join implementation counts with normalized df
                normalized_with_impl = filtered_normalized.join(
                    impl_data,
                    on="cluster_id",
                    how="left"
                )
                
                # Fill nulls for any missing implementation columns
                for impl in known_implementations:
                    col_name = f"{impl}_observers"
                    if col_name in normalized_with_impl.columns:
                        normalized_with_impl = normalized_with_impl.with_columns(
                            pl.col(col_name).fill_null(0)
                        )
            else:
                normalized_with_impl = filtered_normalized
                # Add empty implementation columns if no event clusters
                for impl in known_implementations:
                    col_name = f"{impl}_observers"
                    normalized_with_impl = normalized_with_impl.with_columns(
                        pl.lit(0).cast(pl.Int32).alias(col_name)
                    )
            
            # Create columns for the CSV export
            csv_columns = [
                pl.col("first_detection").dt.strftime("%Y-%m-%d %H:%M:%S").alias("detection_time"),
                pl.col("slot").alias("slot"),
                pl.col("consensus_depth").alias("depth"),
                pl.col("observer_count").alias("total_observers"),
                pl.col("active_node_count").alias("active_nodes"),
                pl.col("observer_percentage").round(1).alias("observer_percentage"),
                pl.col("unique_implementations").alias("unique_implementations"),
                pl.col("confidence_score").round(3).alias("confidence_score"),
                pl.col("detection_span_seconds").round(1).alias("detection_span_seconds"),
                pl.col("avg_propagation_delay").round(0).alias("avg_propagation_delay_ms"),
                pl.col("new_head_block").alias("new_head_block"),
                pl.col("old_head_block").alias("old_head_block"),
                pl.col("cluster_id").alias("event_id")
            ]
            
            # Add implementation observer counts
            for impl in known_implementations:
                col_name = f"{impl}_observers"
                if col_name in normalized_with_impl.columns:
                    csv_columns.append(pl.col(col_name).alias(col_name))
            
            # Add observer list if available
            if "observer_list" in normalized_with_impl.columns:
                csv_columns.append(
                    pl.col("observer_list").list.join(", ").alias("observer_nodes")
                )
            
            # Prepare the full export dataframe
            export_df = normalized_with_impl.select(csv_columns).sort("detection_time", descending=True)
            
            # Convert to pandas for CSV export
            export_pandas = export_df.to_pandas()
            
            # Create CSV download button
            csv_data = export_pandas.to_csv(index=False)
            
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                st.download_button(
                    label="📥 Download Full Reorg Data (CSV)",
                    data=csv_data,
                    file_name=f"reorg_analysis_{filtered_normalized['first_detection'].min().strftime('%Y%m%d')}_{filtered_normalized['first_detection'].max().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    help="Download complete reorg analysis data with all columns including per-client observations"
                )
            
            with col2:
                st.info(f"**{len(export_df):,} total reorg events** with {len(csv_columns)} data columns")
            
            # Show preview of the data
            with st.expander("📋 Preview Data (First 100 rows)"):
                st.dataframe(export_pandas.head(100), use_container_width=True)
        else:
            st.info("No reorgs found matching the filter criteria")
    else:
        st.info("No normalized reorg data available")

def render_reorg_heatmaps(normalized_df: pl.DataFrame, total_nodes: int):
    """
    Render heatmap visualizations for reorg depth vs observer metrics.
    
    Args:
        normalized_df: Normalized reorg events with observer data
        total_nodes: Total number of active nodes
    """
    st.subheader("🗺️ Reorg Observer Heatmaps")
    
    # Calculate statistics for subtitles
    if 'first_detection' in normalized_df.columns:
        time_range_start = normalized_df['first_detection'].min()
        time_range_end = normalized_df['first_detection'].max()
        time_range_str = f"{time_range_start.strftime('%Y-%m-%d %H:%M')} to {time_range_end.strftime('%Y-%m-%d %H:%M')} UTC"
    else:
        time_range_str = "Full time range"
    
    total_events = len(normalized_df)
    avg_observers = normalized_df['observer_count'].mean()
    
    # Calculate max depth dynamically
    max_depth_value = int(normalized_df['consensus_depth'].max())
    depth_buckets = list(range(1, max_depth_value + 2))  # +2 to include max_depth + 1
    
    # Create two columns for the heatmaps
    col1, col2 = st.columns(2)
    
    with col1:
        # Depth vs Observer Percentage Heatmap
        st.markdown("**Depth vs Observer Percentage**")
        st.caption(f"Time: {time_range_str} | Events: {total_events:,} | Avg Active Nodes: {total_nodes}")
        
        # Create buckets for observer percentage (5% buckets)
        observer_pct_buckets = list(range(0, 105, 5))
        
        # Prepare data for heatmap
        heatmap_data = normalized_df.with_columns([
            # Bucket observer percentage
            ((pl.col("observer_percentage") / 5).floor() * 5).alias("observer_pct_bucket"),
            # Keep depth as is (already integer)
            pl.col("consensus_depth").alias("depth_bucket")
        ])
        
        # Count events in each bucket
        pivot_data = heatmap_data.group_by(["depth_bucket", "observer_pct_bucket"]).agg(
            pl.count().alias("event_count")
        )
        
        # Create matrix for heatmap
        z_matrix = []
        text_matrix = []
        
        for depth in depth_buckets:
            row_z = []
            row_text = []
            for pct in observer_pct_buckets[:-1]:  # Exclude 100% as upper bound
                count_df = pivot_data.filter(
                    (pl.col("depth_bucket") == depth) &
                    (pl.col("observer_pct_bucket") == pct)
                )
                count = count_df["event_count"][0] if len(count_df) > 0 else 0
                row_z.append(count)
                row_text.append(str(count) if count > 0 else "")
            z_matrix.append(row_z)
            text_matrix.append(row_text)
        
        # Create heatmap
        fig1 = go.Figure(data=go.Heatmap(
            z=z_matrix,
            x=[f"{pct}-{pct+5}%" for pct in observer_pct_buckets[:-1]],
            y=[str(d) for d in depth_buckets],
            text=text_matrix,
            texttemplate="<b>%{text}</b>",
            textfont={"size": 12},
            colorscale='Reds',
            colorbar=dict(title="Events"),
            hovertemplate='Depth: %{y}<br>Observer %: %{x}<br>Events: %{z}<extra></extra>',
            hoverongaps=False
        ))
        
        fig1.update_layout(
            xaxis_title="Observer Percentage",
            yaxis_title="Reorg Depth",
            height=450,
            margin=dict(l=50, r=20, t=30, b=50),
            yaxis=dict(
                tickmode='array',
                tickvals=depth_buckets,
                ticktext=[str(d) for d in depth_buckets]
            )
        )
        
        # Add ethPandaOps branding
        fig1 = add_ethPandaOps_logo(fig1)
        
        # Display with ethPandaOps branding config
        st.plotly_chart(fig1, use_container_width=True, config=get_ethPandaOps_chart_config())
    
    with col2:
        # Depth vs Observer Count Heatmap
        st.markdown("**Depth vs Observer Count**")
        st.caption(f"Time: {time_range_str} | Events: {total_events:,} | Avg Observers: {avg_observers:.1f}")
        
        # Create buckets for observer count (5 nodes per bucket)
        max_observers = int(normalized_df["observer_count"].max())
        observer_count_buckets = list(range(0, min(max_observers + 10, 105), 5))
        
        # Prepare data for heatmap
        heatmap_data2 = normalized_df.with_columns([
            # Bucket observer count
            ((pl.col("observer_count") / 5).floor() * 5).alias("observer_count_bucket"),
            # Keep depth as is (already integer)
            pl.col("consensus_depth").alias("depth_bucket")
        ])
        
        # Count events in each bucket
        pivot_data2 = heatmap_data2.group_by(["depth_bucket", "observer_count_bucket"]).agg(
            pl.count().alias("event_count")
        )
        
        # Create matrix for heatmap
        z_matrix2 = []
        text_matrix2 = []
        
        for depth in depth_buckets:
            row_z = []
            row_text = []
            for count_bucket in observer_count_buckets[:-1]:  # Exclude last as upper bound
                count_df = pivot_data2.filter(
                    (pl.col("depth_bucket") == depth) &
                    (pl.col("observer_count_bucket") == count_bucket)
                )
                count = count_df["event_count"][0] if len(count_df) > 0 else 0
                row_z.append(count)
                row_text.append(str(count) if count > 0 else "")
            z_matrix2.append(row_z)
            text_matrix2.append(row_text)
        
        # Create heatmap
        fig2 = go.Figure(data=go.Heatmap(
            z=z_matrix2,
            x=[f"{c}-{c+5}" for c in observer_count_buckets[:-1]],
            y=[str(d) for d in depth_buckets],
            text=text_matrix2,
            texttemplate="<b>%{text}</b>",
            textfont={"size": 12},
            colorscale='Blues',
            colorbar=dict(title="Events"),
            hovertemplate='Depth: %{y}<br>Observers: %{x}<br>Events: %{z}<extra></extra>',
            hoverongaps=False
        ))
        
        fig2.update_layout(
            xaxis_title="Observer Count",
            yaxis_title="Reorg Depth",
            height=450,
            margin=dict(l=50, r=20, t=30, b=50),
            yaxis=dict(
                tickmode='array',
                tickvals=depth_buckets,
                ticktext=[str(d) for d in depth_buckets]
            )
        )
        
        # Add ethPandaOps branding
        fig2 = add_ethPandaOps_logo(fig2)
        
        # Display with ethPandaOps branding config
        st.plotly_chart(fig2, use_container_width=True, config=get_ethPandaOps_chart_config())
    


def apply_client_filters(data, selected_clients, excluded_clients, 
                         selected_implementations, excluded_implementations):
    """Apply client and implementation filters to data."""
    filtered_raw = data['raw']
    
    # Apply client filters
    if selected_clients:
        filtered_raw = filtered_raw.filter(pl.col("meta_client_name").is_in(selected_clients))
    if excluded_clients:
        filtered_raw = filtered_raw.filter(~pl.col("meta_client_name").is_in(excluded_clients))
    
    # Apply implementation filters
    if selected_implementations:
        filtered_raw = filtered_raw.filter(pl.col("meta_consensus_implementation").is_in(selected_implementations))
    if excluded_implementations:
        filtered_raw = filtered_raw.filter(~pl.col("meta_consensus_implementation").is_in(excluded_implementations))
    
    # Re-normalize the filtered data
    if not filtered_raw.is_empty():
        normalized_df, event_clusters = normalize_reorg_events(
            filtered_raw,
            time_window_seconds=60,
            match_old_head=False
        )
        
        return {
            'raw': filtered_raw,
            'normalized': normalized_df,
            'event_clusters': event_clusters,
            'episodes': data.get('episodes', pl.DataFrame()),
            'missed_slots': data.get('missed_slots', pl.DataFrame())
        }
    else:
        return {
            'raw': filtered_raw,
            'normalized': pl.DataFrame(),
            'event_clusters': pl.DataFrame(),
            'episodes': pl.DataFrame(),
            'missed_slots': pl.DataFrame()
        }

if __name__ == "__main__":
    main()