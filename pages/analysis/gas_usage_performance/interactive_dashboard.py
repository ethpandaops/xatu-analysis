"""
Interactive dashboard for gas usage performance analysis.

This module provides the main Streamlit interface for analyzing the relationship
between gas usage and block arrival times in Ethereum networks.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, List
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from shared.ui_components import apply_ethPandaOps_styling
from config_utils import (
    get_metric_info, get_analysis_config, get_default_periods,
    validate_analysis_config
)
from data_loaders import load_complete_analysis_data, validate_data_quality
# Import polars-optimized functions first, fall back to pandas if needed
try:
    from polars_metrics_calculators import (
        create_time_buckets_polars as create_time_buckets,
        create_gas_buckets_polars as create_gas_buckets, 
        calculate_bucket_metrics_polars as calculate_bucket_metrics,
        aggregate_data_polars as aggregate_data,
        calculate_correlation_analysis_polars,
        calculate_temporal_trends_polars as calculate_temporal_trends,
        calculate_percentile_analysis_polars as calculate_percentile_analysis,
        sample_large_dataset as prepare_large_dataset
    )
    # Import pandas fallbacks for functions not yet in polars
    from metrics_calculators import (
        calculate_consensus_performance_ranking,
        calculate_gas_binned_analysis,
        calculate_comparative_analysis
    )
    USING_POLARS_METRICS = True
except ImportError:
    # Fallback to pandas versions
    from metrics_calculators import (
        create_time_buckets, create_gas_buckets, calculate_bucket_metrics, aggregate_data, calculate_consensus_performance_ranking,
        calculate_gas_binned_analysis, calculate_temporal_trends, calculate_percentile_analysis,
        calculate_comparative_analysis, prepare_large_dataset
    )
    USING_POLARS_METRICS = False
from plot_generators import (
    create_gas_vs_arrival_scatter, create_time_series_comparison, create_consensus_performance_heatmap,
    create_box_plot_comparison, create_correlation_matrix, create_geographic_performance_plot,
    create_gas_binned_performance_plot, create_multi_y_correlation_plot
)


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def initialize_session_state():
    """Initialize session state variables."""
    if 'data_loaded' not in st.session_state:
        st.session_state.data_loaded = False
    if 'analysis_data' not in st.session_state:
        st.session_state.analysis_data = {}
    if 'last_config' not in st.session_state:
        st.session_state.last_config = None
    if 'time_buckets_data' not in st.session_state:
        st.session_state.time_buckets_data = {}
    if 'selected_metrics' not in st.session_state:
        st.session_state.selected_metrics = ['gas_used', 'block_gossip_time_mean']


def render_sidebar_configuration() -> Dict[str, Any]:
    """
    Render sidebar configuration panel and return selected parameters.
    
    Returns:
        Dictionary with configuration parameters
    """
    st.sidebar.header("⚙️ Analysis Configuration")
    
    # Network selection
    config = get_analysis_config()
    network = st.sidebar.selectbox(
        "Select Network",
        config['supported_networks'],
        index=0,
        help="Ethereum network to analyze"
    )
    
    # Time range configuration
    st.sidebar.subheader("📅 Analysis Periods")
    
    # Quick period selection
    default_periods = get_default_periods()
    period_options = ["Custom"] + list(default_periods.keys())
    
    selected_period = st.sidebar.selectbox(
        "Quick Period Selection",
        period_options,
        index=period_options.index("Last 1 Day") if "Last 1 Day" in period_options else 1,
        help="Select a predefined period or choose Custom for manual selection"
    )
    
    # Period 1 configuration
    st.sidebar.write("**Period 1**")
    period1_col1, period1_col2 = st.sidebar.columns(2)
    
    if selected_period != "Custom":
        period_config = default_periods[selected_period]
        default_start = period_config["start"].date()
        default_end = period_config["end"].date()
    else:
        default_start = (datetime.now() - timedelta(days=7)).date()
        default_end = datetime.now().date()
    
    with period1_col1:
        period1_start = st.date_input(
            "Start Date", 
            value=default_start,
            max_value=datetime.now().date(),
            key="period1_start"
        )
    with period1_col2:
        period1_end = st.date_input(
            "End Date", 
            value=default_end,
            max_value=datetime.now().date(),
            key="period1_end"
        )
    
    # Period comparison option
    enable_comparison = st.sidebar.checkbox(
        "Enable Period Comparison", 
        help="Compare metrics between two time periods"
    )
    
    period2_start, period2_end = None, None
    if enable_comparison:
        st.sidebar.write("**Period 2**")
        period2_col1, period2_col2 = st.sidebar.columns(2)
        
        with period2_col1:
            period2_start = st.date_input(
                "Start Date", 
                value=(datetime.now() - timedelta(days=14)).date(),
                max_value=datetime.now().date(),
                key="period2_start"
            )
        with period2_col2:
            period2_end = st.date_input(
                "End Date", 
                value=(datetime.now() - timedelta(days=7)).date(),
                max_value=datetime.now().date(),
                key="period2_end"
            )
    
    # Advanced settings
    with st.sidebar.expander("🔧 Advanced Settings"):
        time_buckets = st.number_input(
            "Number of Time Buckets", 
            min_value=config['min_time_buckets'], 
            max_value=config['max_time_buckets'], 
            value=config['default_time_buckets'],
            help="Number of equal-duration time periods for temporal analysis"
        )
        
        min_samples = st.number_input(
            "Minimum Samples per Analysis", 
            min_value=100, 
            value=config['min_samples_per_analysis'],
            help="Minimum number of data points required for analysis"
        )
        
        max_propagation = st.number_input(
            "Max Propagation Time (ms)",
            min_value=1000,
            max_value=30000,
            value=config['max_propagation_time_ms'],
            help="Maximum propagation time to include in analysis"
        )
    
    # Set performance settings internally (removed from UI)
    enable_chunking = True
    chunk_size_days = 1  # Fixed to 1 day as requested
    
    return {
        'network': network,
        'period1_start': period1_start,
        'period1_end': period1_end,
        'period2_start': period2_start,
        'period2_end': period2_end,
        'enable_comparison': enable_comparison,
        'time_buckets': time_buckets,
        'min_samples': min_samples,
        'max_propagation': max_propagation,
        'enable_chunking': enable_chunking,
        'chunk_size_days': chunk_size_days,
    }




def load_and_validate_data(config: Dict[str, Any]) -> bool:
    """
    Load and validate analysis data based on configuration.
    
    Args:
        config: Configuration parameters
        
    Returns:
        True if data loaded successfully, False otherwise
    """
    with st.spinner("🔄 Loading gas usage and performance data..."):
        try:
            # Validate configuration
            validation_errors = validate_analysis_config(
                config['network'],
                datetime.combine(config['period1_start'], datetime.min.time()),
                datetime.combine(config['period1_end'], datetime.min.time()),
                config['time_buckets']
            )
            
            if validation_errors:
                for error in validation_errors:
                    st.error(f"❌ Configuration error: {error}")
                return False
            
            # Load Period 1 data
            period1_data = load_complete_analysis_data(
                config['network'],
                datetime.combine(config['period1_start'], datetime.min.time()),
                datetime.combine(config['period1_end'], datetime.min.time()),
                "Period 1"
            )
            
            st.session_state.analysis_data['period1'] = period1_data
            
            # Load Period 2 data if comparison enabled
            if config['enable_comparison']:
                period2_data = load_complete_analysis_data(
                    config['network'],
                    datetime.combine(config['period2_start'], datetime.min.time()),
                    datetime.combine(config['period2_end'], datetime.min.time()),
                    "Period 2"
                )
                st.session_state.analysis_data['period2'] = period2_data
            
            # Validate data quality
            period1_quality = validate_data_quality(period1_data['combined_data'])
            if not period1_quality['valid']:
                st.warning("⚠️ Data quality issues detected:")
                for warning in period1_quality['warnings']:
                    st.warning(f"• {warning}")
            
            # Create time buckets using Polars-optimized functions
            if not period1_data['combined_data'].empty:
                try:
                    logger.info(f"Creating time buckets for {len(period1_data['combined_data']):,} records using Polars")
                    bucketed_data = create_time_buckets(
                        period1_data['combined_data'], 
                        config['time_buckets']
                    )
                    st.session_state.time_buckets_data['period1'] = bucketed_data
                    logger.info(f"Successfully created {config['time_buckets']} time buckets")
                except Exception as e:
                    logger.error(f"Error creating time buckets: {e}")
                    st.error(f"Failed to create time buckets: {str(e)}")
                    return False
                
                if config['enable_comparison'] and not st.session_state.analysis_data['period2']['combined_data'].empty:
                    bucketed_data2 = create_time_buckets(
                        st.session_state.analysis_data['period2']['combined_data'],
                        config['time_buckets']
                    )
                    st.session_state.time_buckets_data['period2'] = bucketed_data2
            
            st.session_state.data_loaded = True
            st.success("✅ Data loaded successfully!")
            
            # Display data summary
            summary = period1_data['summary_stats']
            
            # Check if we have gas data
            has_gas_data = summary.get('avg_gas_used', 0) > 0
            
            if has_gas_data:
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Records", f"{summary.get('total_blocks', 0):,}")
                with col2:
                    st.metric("Avg Gas Used", f"{summary.get('avg_gas_used', 0):.0f}")
                with col3:
                    st.metric("Avg Gas Utilization", f"{summary.get('avg_gas_utilization', 0):.1f}%")
                with col4:
                    st.metric("Avg Block Gossip Time", f"{summary.get('avg_block_gossip_time', 0):.1f}ms")
            else:
                st.info("ℹ️ **Timing-Only Analysis Mode**: No gas usage data available for this network/period. Analysis will focus on block propagation timing metrics.")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Records", f"{summary.get('total_blocks', 0):,}")
                with col2:
                    st.metric("Avg Block Gossip Time", f"{summary.get('avg_block_gossip_time', 0):.1f}ms")
                with col3:
                    st.metric("Avg Head Time", f"{summary.get('avg_head_time', 0):.1f}ms")
            
            return True
            
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            st.error(f"❌ Error loading data: {str(e)}")
            st.session_state.data_loaded = False
            return False


def render_analysis_controls() -> Dict[str, Any]:
    """
    Render analysis controls including metrics, aggregation, and grouping.
    
    Returns:
        Dictionary with analysis configuration
    """
    st.subheader("📊 Analysis Configuration")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.write("**Metrics**")
        # Available metrics (now using raw column names from client-level data)
        gas_metrics = st.multiselect(
            "Gas metrics:",
            ['gas_used', 'gas_utilization', 'blob_count'],
            default=['gas_used', 'gas_utilization', 'blob_count'],
            key="gas_metrics"
        )
        
        perf_metrics = st.multiselect(
            "Performance metrics:",
            ['block_gossip_time', 'head_time', 'time_difference'],
            default=['block_gossip_time', 'head_time', 'time_difference'],
            key="perf_metrics"
        )
        
        selected_metrics = gas_metrics + perf_metrics
    
    with col2:
        st.write("**Aggregation Level**")
        aggregation_options = {
            'Client Level': None,  # No aggregation - raw client data
            'Slot Level': ['slot'],
            'Consensus Implementation': ['meta_consensus_implementation'],
            'Time Bucket': ['bucket_number'],
            'Gas Bucket': ['gas_bucket'],
            'Implementation + Time': ['meta_consensus_implementation', 'bucket_number'],
            'Implementation + Gas': ['meta_consensus_implementation', 'gas_bucket'],
            'Continent': ['meta_client_geo_continent_code'],
            'Continent + Time': ['meta_client_geo_continent_code', 'bucket_number']
        }
        
        aggregation_level = st.selectbox(
            "Group data by:",
            list(aggregation_options.keys()),
            index=4,  # Default to Gas Bucket
            key="aggregation_level"
        )
        
        group_by = aggregation_options[aggregation_level]
    
    with col3:
        st.write("**Aggregation Function**")
        agg_function = st.selectbox(
            "How to aggregate:",
            ['mean', 'median', 'p95', 'p99', 'min', 'max'],
            index=0,
            key="agg_function"
        )
        
        st.write("**Gas Bucket Size**")
        gas_bucket_size = st.selectbox(
            "Gas bucket size (gas units):",
            [500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000],
            index=2,  # Default to 2M
            format_func=lambda x: f"{x/1_000_000:.1f}M",
            key="gas_bucket_size"
        )
    
    # Chart configuration options
    st.write("**Chart Options**")
    col4, col5 = st.columns(2)
    with col4:
        start_y_from_zero = st.checkbox(
            "Start Y-axis from 0",
            value=True,
            key="start_y_from_zero",
            help="Force Y-axis to start from zero for better comparison"
        )
    with col5:
        show_attestation_deadline = st.checkbox(
            "Show 4s attestation deadline",
            value=True,
            key="show_attestation_deadline",
            help="Display a reference line at 4000ms for attestation timing analysis"
        )
    
    # Don't store widget values in session state - they're already managed by the widgets
    # Just return the configuration
    return {
        'metrics': selected_metrics,
        'group_by': group_by,
        'agg_function': agg_function,
        'aggregation_level': aggregation_level,
        'gas_bucket_size': gas_bucket_size,
        'start_y_from_zero': start_y_from_zero,
        'show_attestation_deadline': show_attestation_deadline
    }


def render_analysis_dashboard():
    """Render the main analysis dashboard with all visualizations."""
    if not st.session_state.data_loaded or 'period1' not in st.session_state.analysis_data:
        st.warning("⚠️ No data loaded. Please configure analysis parameters and load data.")
        return
    
    period1_data = st.session_state.analysis_data['period1']['combined_data']
    period1_bucketed = st.session_state.time_buckets_data.get('period1', pd.DataFrame())
    
    if period1_data.empty:
        st.error("❌ No data available for analysis")
        return
    
    # Analysis controls
    analysis_config = render_analysis_controls()
    
    if not analysis_config['metrics']:
        st.warning("⚠️ Please select at least one metric for analysis")
        return
    
    # Apply user-controlled aggregation
    if analysis_config['group_by'] is not None:
        # Check if time bucket aggregation is requested
        needs_time_bucketed_data = any('bucket_number' in str(col) for col in analysis_config['group_by'])
        
        # Check if gas bucket aggregation is requested
        needs_gas_bucketed_data = any('gas_bucket' in str(col) for col in analysis_config['group_by'])
        
        if needs_time_bucketed_data and not period1_bucketed.empty:
            # Use pre-bucketed data for time bucket aggregations
            source_data = period1_bucketed
        elif needs_gas_bucketed_data:
            # Create gas buckets for gas-based aggregations
            source_data = create_gas_buckets(period1_data, bucket_size=analysis_config['gas_bucket_size'])
            if 'gas_bucket' not in source_data.columns:
                st.warning("⚠️ Could not create gas buckets - using original data")
                source_data = period1_data
        else:
            # Use original data for non-bucket aggregations
            source_data = period1_data
        
        # Aggregate the data according to user selection using Polars
        with st.spinner(f"Aggregating {len(source_data):,} records using Polars..."):
            if USING_POLARS_METRICS:
                logger.info(f"Using Polars aggregation for {len(source_data):,} records")
            aggregated_data = aggregate_data(
                source_data,
                group_by=analysis_config['group_by'],
                metrics=analysis_config['metrics'],
                agg_function=analysis_config['agg_function']
            )
        
        # If aggregated data is still too large, suggest higher-level aggregation
        max_chart_points = 5000  # Optimal for interactive charts
        if len(aggregated_data) > max_chart_points:
            st.warning(f"⚠️ Aggregated dataset still large ({len(aggregated_data):,} records). Consider using higher-level aggregation (Time Bucket, Implementation, etc.) for better performance.")
            # Don't sample - use all data but warn about performance
            display_data = aggregated_data
        else:
            display_data = aggregated_data
    else:
        # Use raw client-level data - strongly encourage aggregation for large datasets
        max_raw_points = 50000  # Increased since we're not sampling
        if len(period1_data) > max_raw_points:
            st.error(f"❌ Dataset too large ({len(period1_data):,} records). Please select an aggregation level to analyze this data effectively.")
            st.info("💡 Try 'Slot Level' aggregation to reduce ~200K client records to ~7K slot records")
            return  # Don't render charts with massive datasets
        else:
            display_data = period1_data
    
    # Correlation Analysis (only visualization option)
    with st.spinner("Generating correlation analysis..."):
        render_correlation_analysis(display_data, analysis_config['metrics'], analysis_config['agg_function'], 
                                   analysis_config, st.session_state.analysis_data.get('period1', {}))
    


def create_chart_metadata(analysis_config: Dict[str, Any], period_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create metadata dictionary for chart annotations."""
    metadata = {}
    
    # Extract time range
    if 'start_date' in period_data and 'end_date' in period_data:
        start_str = period_data['start_date'].strftime('%Y-%m-%d')
        end_str = period_data['end_date'].strftime('%Y-%m-%d')
        metadata['time_range'] = f"{start_str} to {end_str}"
    
    # Extract network
    if 'network' in period_data:
        metadata['network'] = period_data['network']
    
    # Extract block counts
    if 'combined_data' in period_data and not period_data['combined_data'].empty:
        # Count unique blocks (slots)
        unique_blocks = period_data['combined_data']['slot'].nunique() if 'slot' in period_data['combined_data'].columns else len(period_data['combined_data'])
        metadata['total_blocks'] = unique_blocks
    
    return metadata


def render_correlation_analysis(data: pd.DataFrame, metrics: List[str], agg_function: str = "mean", 
                               analysis_config: Dict[str, Any] = None, period_data: Dict[str, Any] = None):
    """Render correlation analysis section."""
    
    if data.empty:
        st.warning("No data available for correlation analysis")
        return
    
    if len(metrics) < 2:
        st.warning("Need at least 2 metrics for correlation analysis")
        return
    
    # get_metric_info is already imported at the top
    
    # Handle aggregated data - map original metrics to their aggregated versions
    available_metrics = []
    metric_mapping = {}  # original -> aggregated column name
    
    for metric in metrics:
        # Check for original metric name
        if metric in data.columns and data[metric].notna().sum() > 0:
            available_metrics.append(metric)
            metric_mapping[metric] = metric
        # Check for aggregated metric name (e.g., gas_used -> gas_used_mean)
        else:
            for agg_suffix in ['_mean', '_median', '_p95', '_p99', '_min', '_max']:
                agg_metric = f"{metric}{agg_suffix}"
                if agg_metric in data.columns and data[agg_metric].notna().sum() > 0:
                    available_metrics.append(metric)  # Keep original name for UI
                    metric_mapping[metric] = agg_metric  # Map to actual column
                    break
    
    if len(available_metrics) < 2:
        st.warning(f"Need at least 2 metrics with data. Available metrics: {available_metrics}")
        st.write(f"Selected metrics: {metrics}")
        st.write(f"Data columns: {list(data.columns)}")
        return
    
    # Clear session state for correlation selectors if the selected metrics are no longer available
    if "corr_x_metric" in st.session_state and st.session_state.corr_x_metric not in available_metrics:
        del st.session_state.corr_x_metric
    if "corr_y_metrics" in st.session_state:
        # Filter out metrics that are no longer available
        valid_y_metrics = [m for m in st.session_state.corr_y_metrics if m in available_metrics]
        if len(valid_y_metrics) != len(st.session_state.corr_y_metrics):
            st.session_state.corr_y_metrics = valid_y_metrics
    
    # Metric pair selection
    col1, col2 = st.columns(2)
    with col1:
        gas_metrics = [m for m in available_metrics if 'gas' in m.lower()]
        if not gas_metrics:
            gas_metrics = available_metrics
        x_metric = st.selectbox(
            "X-axis metric:",
            gas_metrics,
            key="corr_x_metric"
        )
    with col2:
        perf_metrics = [m for m in available_metrics if m != x_metric]
        y_metrics = st.multiselect(
            "Y-axis metrics:",
            perf_metrics,
            default=perf_metrics[:2] if len(perf_metrics) >= 2 else perf_metrics,
            key="corr_y_metrics"
        )
    
    if x_metric and y_metrics:
        try:
            # Prepare data for visualization (sample if too large)
            config = get_analysis_config()
            viz_data = data
            if len(data) > config.get('max_visualization_points', 100_000):
                viz_data = prepare_large_dataset(data, max_rows=config.get('max_visualization_points', 100_000))
            
            # Create chart metadata
            chart_metadata = create_chart_metadata(analysis_config or {}, period_data or {})
            
            # Map selected metrics to actual column names in the data
            actual_x_metric = metric_mapping.get(x_metric, x_metric)
            actual_y_metrics = [metric_mapping.get(y, y) for y in y_metrics]
            
            # Always use multi y-axis chart for consistency
            fig = create_multi_y_correlation_plot(
                viz_data, actual_x_metric, actual_y_metrics,
                title_suffix="",
                agg_function=agg_function,
                network=chart_metadata.get('network'),
                time_range=chart_metadata.get('time_range'),
                metadata=chart_metadata,
                start_y_from_zero=analysis_config.get('start_y_from_zero', True),
                show_attestation_deadline=analysis_config.get('show_attestation_deadline', True)
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # Show correlation matrix if multiple metrics
            if len(available_metrics) > 2:
                st.write("#### Correlation Matrix")
                # Use actual column names for correlation matrix
                actual_available_metrics = [metric_mapping.get(m, m) for m in available_metrics]
                corr_fig = create_correlation_matrix(viz_data, actual_available_metrics)
                st.plotly_chart(corr_fig, use_container_width=True)
                
        except Exception as e:
            st.error(f"Error creating correlation plot: {str(e)}")
            st.write(f"Data shape: {data.shape}")
            st.write(f"X metric ({x_metric}) stats: {data[x_metric].describe()}")
            if y_metrics:
                for y_metric in y_metrics:
                    st.write(f"Y metric ({y_metric}) stats: {data[y_metric].describe()}")


def render_time_series_analysis(bucketed_data: pd.DataFrame, metrics: List[str], agg_function: str = "mean",
                               analysis_config: Dict[str, Any] = None, period_data: Dict[str, Any] = None):
    """Render time series analysis section."""
    st.write("### Temporal Analysis Over Time Buckets")
    
    if bucketed_data.empty:
        st.warning("No time bucket data available")
        return
    
    # Debug info
    st.write(f"Debug: Bucketed data shape: {bucketed_data.shape}")
    st.write(f"Debug: Bucketed data columns: {list(bucketed_data.columns)}")
    
    try:
        # Check if data has time buckets
        if 'bucket_number' not in bucketed_data.columns:
            st.warning("Data not properly bucketed. Cannot create time series.")
            return
        
        # Check if data is already aggregated by time buckets
        bucket_counts = bucketed_data['bucket_number'].value_counts()
        if bucket_counts.max() > 1:
            # Data needs further aggregation by bucket
            st.write(f"Aggregating {len(bucketed_data)} records by {bucketed_data['bucket_number'].nunique()} time buckets...")
            bucket_metrics = calculate_bucket_metrics(
                bucketed_data, 
                metric_cols=metrics,
                agg_function='mean'
            )
        else:
            # Data is already properly aggregated
            bucket_metrics = bucketed_data
        
        if bucket_metrics.empty:
            st.warning("Could not calculate bucket metrics")
            return
        
        st.write(f"Debug: Bucket metrics shape: {bucket_metrics.shape}")
        st.write(f"Debug: Bucket metrics columns: {list(bucket_metrics.columns)}")
        
        # Select metrics for time series
        available_ts_metrics = [col for col in metrics if col in bucket_metrics.columns and bucket_metrics[col].notna().sum() > 0]
        
        if not available_ts_metrics:
            st.warning(f"No time series metrics available. Requested: {metrics}, Available: {list(bucket_metrics.columns)}")
            return
        
        selected_ts_metrics = st.multiselect(
            "Select metrics for time series:",
            available_ts_metrics,
            default=available_ts_metrics[:2] if len(available_ts_metrics) >= 2 else available_ts_metrics,
            key="ts_metrics"
        )
        
        if selected_ts_metrics:
            # Sort by bucket number
            bucket_metrics_sorted = bucket_metrics.sort_values('bucket_number')
            
            # Create chart metadata
            chart_metadata = create_chart_metadata(analysis_config or {}, period_data or {})
            
            # Create time series plot
            fig = create_time_series_comparison(
                bucket_metrics_sorted.set_index('bucket_number'),
                selected_ts_metrics,
                title_suffix=" - Temporal Analysis",
                agg_function=agg_function,
                network=chart_metadata.get('network'),
                time_range=chart_metadata.get('time_range'),
                metadata=chart_metadata
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # Show trend analysis
            try:
                trends = calculate_temporal_trends(bucket_metrics_sorted, metric_cols=selected_ts_metrics)
                if trends:
                    st.write("#### Trend Analysis")
                    trend_data = []
                    for metric, trend_info in trends.items():
                        if trend_info:
                            trend_data.append({
                                'Metric': get_metric_info(metric)['title'],
                                'Trend': trend_info['trend_direction'],
                                'Slope': f"{trend_info['slope']:.2e}",
                                'R²': f"{trend_info['r_squared']:.3f}",
                                'Significant': "Yes" if trend_info['significant'] else "No"
                            })
                    
                    if trend_data:
                        st.dataframe(pd.DataFrame(trend_data), use_container_width=True)
            except Exception as e:
                st.warning(f"Could not calculate trends: {str(e)}")
                
    except Exception as e:
        st.error(f"Error in time series analysis: {str(e)}")
        import traceback
        st.code(traceback.format_exc())


def render_time_series_data_table(bucketed_data: pd.DataFrame, metrics: List[str]):
    """Render time series data table with gas bucket information."""
    st.write("### Time Series Data Explorer")
    
    if bucketed_data.empty:
        st.warning("No data available for time series data table")
        return
    
    try:
        # Check if we have gas bucket data
        if 'gas_bucket' in bucketed_data.columns and 'gas_bucket_label' in bucketed_data.columns:
            st.write("#### Gas Usage Bucket Analysis")
            
            # Create readable gas bucket labels if they don't exist
            if bucketed_data['gas_bucket_label'].isna().all():
                # Generate labels from gas_bucket_start and gas_bucket_end if available
                if 'gas_bucket_start' in bucketed_data.columns and 'gas_bucket_end' in bucketed_data.columns:
                    bucketed_data['gas_bucket_label'] = bucketed_data.apply(
                        lambda row: f"{int(row['gas_bucket_start']/1_000_000)}M-{int(row['gas_bucket_end']/1_000_000)}M" 
                        if pd.notna(row['gas_bucket_start']) and pd.notna(row['gas_bucket_end'])
                        else f"Bucket {row['gas_bucket']}", 
                        axis=1
                    )
                else:
                    # Fallback to simple bucket numbers
                    bucketed_data['gas_bucket_label'] = bucketed_data['gas_bucket'].apply(
                        lambda x: f"Bucket {x}" if pd.notna(x) else "Unknown"
                    )
            
            # Group by gas bucket and aggregate
            gas_bucket_metrics = bucketed_data.groupby('gas_bucket_label').agg({
                metric: ['mean', 'count'] for metric in metrics if metric in bucketed_data.columns
            }).round(2)
            
            # Flatten column names
            gas_bucket_metrics.columns = ['_'.join(col).strip('_') for col in gas_bucket_metrics.columns]
            
            # Add sample count column
            sample_counts = bucketed_data.groupby('gas_bucket_label').size()
            gas_bucket_metrics['sample_count'] = sample_counts
            
            # Sort by gas bucket order
            gas_bucket_metrics = gas_bucket_metrics.sort_index()
            
            st.write(f"**Data grouped by gas usage buckets** (showing {len(gas_bucket_metrics)} buckets)")
            st.dataframe(gas_bucket_metrics, use_container_width=True)
            
            # Allow users to select specific gas buckets
            bucket_options = sorted(bucketed_data['gas_bucket_label'].dropna().unique())
            selected_buckets = st.multiselect(
                "Select gas buckets to highlight in charts:",
                bucket_options,
                default=bucket_options[:3] if len(bucket_options) >= 3 else bucket_options,
                key="selected_gas_buckets"
            )
            
            if selected_buckets:
                filtered_data = bucketed_data[bucketed_data['gas_bucket_label'].isin(selected_buckets)]
                st.write(f"**Filtered data:** {len(filtered_data)} records from selected buckets")
                
                # Show summary of selected buckets
                selected_summary = filtered_data.groupby('gas_bucket_label')[metrics].mean().round(2)
                st.dataframe(selected_summary, use_container_width=True)
        
        elif 'bucket_number' in bucketed_data.columns:
            st.write("#### Time Bucket Analysis")
            
            # Group by time bucket
            time_bucket_metrics = bucketed_data.groupby('bucket_number').agg({
                metric: ['mean', 'count'] for metric in metrics if metric in bucketed_data.columns
            }).round(2)
            
            # Flatten column names
            time_bucket_metrics.columns = ['_'.join(col).strip('_') for col in time_bucket_metrics.columns]
            
            st.write(f"**Data grouped by time buckets** (showing {len(time_bucket_metrics)} buckets)")
            st.dataframe(time_bucket_metrics, use_container_width=True)
            
            # Allow users to select specific time ranges
            bucket_options = sorted(bucketed_data['bucket_number'].dropna().unique())
            selected_time_buckets = st.multiselect(
                "Select time buckets to highlight:",
                bucket_options,
                default=bucket_options[:5] if len(bucket_options) >= 5 else bucket_options,
                key="selected_time_buckets"
            )
            
            if selected_time_buckets:
                filtered_data = bucketed_data[bucketed_data['bucket_number'].isin(selected_time_buckets)]
                st.write(f"**Filtered data:** {len(filtered_data)} records from selected time buckets")
                
                selected_summary = filtered_data.groupby('bucket_number')[metrics].mean().round(2)
                st.dataframe(selected_summary, use_container_width=True)
        
        else:
            # Show raw data table with sampling if too large
            st.write("#### Raw Data Table")
            display_data = bucketed_data[metrics + ['slot'] if 'slot' in bucketed_data.columns else metrics]
            
            if len(display_data) > 1000:
                sample_size = 1000
                display_data = display_data.sample(n=sample_size)
                st.write(f"**Showing sample of {sample_size} records** (total: {len(bucketed_data)})")
            
            st.dataframe(display_data, use_container_width=True)
            
    except Exception as e:
        st.error(f"Error creating time series data table: {str(e)}")
        st.write(f"Data shape: {bucketed_data.shape}")
        st.write(f"Available columns: {list(bucketed_data.columns)}")
        import traceback
        st.code(traceback.format_exc())


def render_distribution_analysis(data: pd.DataFrame, metrics: List[str]):
    """Render distribution analysis section."""
    st.write("### Distribution Analysis")
    
    # Box plot comparison
    if 'consensus_implementations' in data.columns:
        st.write("#### Performance Distribution by Consensus Implementation")
        
        box_metric = st.selectbox(
            "Select metric for box plot:",
            metrics,
            key="box_metric"
        )
        
        fig = create_box_plot_comparison(
            data, 
            box_metric,
            title_suffix=" - Distribution Analysis"
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # Gas binned analysis
    st.write("#### Performance vs Gas Usage Analysis")
    
    gas_metrics = [m for m in metrics if 'gas' in m.lower()]
    perf_metrics = [m for m in metrics if 'time' in m.lower() or 'gossip' in m.lower()]
    
    if gas_metrics and perf_metrics:
        gas_metric = st.selectbox("Gas metric:", gas_metrics, key="gas_bin_metric")
        perf_metric = st.selectbox("Performance metric:", perf_metrics, key="perf_bin_metric")
        
        # Calculate gas binned analysis
        binned_analysis = calculate_gas_binned_analysis(data, gas_metric, perf_metric)
        
        if not binned_analysis.empty:
            fig = create_gas_binned_performance_plot(
                binned_analysis,
                f"{perf_metric}_mean",
                title_suffix=" - Gas Binned Analysis"
            )
            st.plotly_chart(fig, use_container_width=True)


def render_geographic_analysis(data: pd.DataFrame, metrics: List[str]):
    """Render geographic analysis section."""
    st.write("### Geographic Performance Analysis")
    
    if 'continents' not in data.columns:
        st.warning("No geographic data available")
        return
    
    geo_metric = st.selectbox(
        "Select metric for geographic analysis:",
        metrics,
        key="geo_metric"
    )
    
    fig = create_geographic_performance_plot(
        data, 
        geo_metric,
        title_suffix=" - Geographic Analysis"
    )
    st.plotly_chart(fig, use_container_width=True)


def render_statistical_summary(data: pd.DataFrame, metrics: List[str]):
    """Render statistical summary section."""
    st.subheader("📋 Statistical Summary")
    
    # Percentile analysis
    percentiles = calculate_percentile_analysis(data, metrics)
    
    if not percentiles.empty:
        st.write("#### Percentile Analysis")
        st.dataframe(percentiles, use_container_width=True)
    
    # Comparison analysis if multiple periods
    if 'period2' in st.session_state.analysis_data:
        period2_data = st.session_state.analysis_data['period2']['combined_data']
        if not period2_data.empty:
            st.write("#### Period Comparison")
            comparison = calculate_comparative_analysis(data, period2_data, metrics)
            
            if comparison:
                comp_data = []
                for metric, comp_info in comparison.items():
                    if comp_info:
                        comp_data.append({
                            'Metric': get_metric_info(metric)['title'],
                            'Period 1 Mean': f"{comp_info['period1_mean']:.2f}",
                            'Period 2 Mean': f"{comp_info['period2_mean']:.2f}",
                            'Change (%)': f"{comp_info['percent_change']:.1f}%",
                            'Significant': "Yes" if comp_info['significant_difference'] else "No"
                        })
                
                if comp_data:
                    st.dataframe(pd.DataFrame(comp_data), use_container_width=True)


def main():
    """Main dashboard function."""
    apply_ethPandaOps_styling()
    
    # Initialize session state
    initialize_session_state()
    
    # Page title
    st.markdown('<h1 class="main-header">⛽ Gas Usage Performance Analysis</h1>', unsafe_allow_html=True)
    
    # Sidebar configuration
    config = render_sidebar_configuration()
    
    # Check if configuration changed
    current_config = (
        config['network'], 
        str(config['period1_start']), 
        str(config['period1_end']),
        config['enable_comparison'],
        str(config.get('period2_start', '')),
        str(config.get('period2_end', '')),
        config['time_buckets']
    )
    config_changed = st.session_state.last_config != current_config
    
    if config_changed and st.session_state.data_loaded:
        st.sidebar.warning("⚠️ Configuration changed. Click 'Load Data' to refresh.")
        st.session_state.data_loaded = False
    
    # Data loading
    if st.sidebar.button("🔄 Load Analysis Data", type="primary"):
        if load_and_validate_data(config):
            st.session_state.last_config = current_config
    
    # Main analysis display
    if st.session_state.data_loaded:
        render_analysis_dashboard()
    else:
        # Show information when no data is loaded
        st.info("👆 Configure analysis parameters and click 'Load Analysis Data' to begin.")
        
        st.markdown("### 📊 What This Analysis Provides")
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **🔗 Correlation Analysis**
            - Gas usage vs block propagation correlation
            - Statistical significance testing
            - Trend line analysis with confidence intervals
            
            **📈 Temporal Analysis**
            - Performance changes over time buckets
            - Trend detection and significance testing
            - Multi-metric time series comparison
            """)
        
        with col2:
            st.markdown("""
            **🔥 Performance Comparison**
            - Consensus implementation rankings
            - Performance heatmaps over time
            - Geographic performance variations
            
            **📊 Statistical Insights**
            - Percentile analysis for all metrics
            - Period-over-period comparisons
            - Distribution analysis and outlier detection
            """)
        
        # Show example metric information
        st.markdown("### 📋 Available Metrics")
        example_metrics = ['gas_used', 'block_gossip_time', 'head_time', 'gas_utilization']
        
        metric_info_data = []
        for metric in example_metrics:
            info = get_metric_info(metric)
            metric_info_data.append({
                'Metric': info['title'],
                'Description': info['subtitle'],
                'Unit': info['unit']
            })
        
        st.dataframe(pd.DataFrame(metric_info_data), use_container_width=True)


if __name__ == "__main__":
    main()