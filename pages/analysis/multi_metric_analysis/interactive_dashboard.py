"""
Interactive dashboard for multi-metric performance analysis.

This module provides the main Streamlit interface for analyzing relationships
between multiple performance metrics in Ethereum networks, including gas usage,
block propagation times, and consensus implementation performance.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from shared.ui_components import apply_ethPandaOps_styling
from shared.header import render_global_header, get_global_cluster, get_global_network
from shared.metric_utils import get_metric_info
from config_utils import (
    get_analysis_config, get_default_periods,
    validate_analysis_config
)
from data_loaders import load_complete_analysis_data
from metrics_calculators import (
    create_time_buckets,
    create_gas_buckets, 
    calculate_bucket_metrics,
    aggregate_data,
    calculate_correlation_analysis,
    calculate_temporal_trends,
    calculate_percentile_analysis,
    prepare_large_dataset,
    calculate_consensus_performance_ranking,
    calculate_gas_binned_analysis,
    calculate_comparative_analysis
)
from plot_generators import (
    create_gas_vs_arrival_scatter, create_time_series_comparison, create_consensus_performance_heatmap,
    create_box_plot_comparison, create_correlation_matrix, create_geographic_performance_plot,
    create_gas_binned_performance_plot, create_multi_y_correlation_plot
)
from metric_discovery import discover_metrics, DataLineageTracker, format_bucket_size
from dynamic_bucketing import create_dynamic_buckets
from analysis_templates import get_template, get_template_names, get_default_template, save_template


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
    # Get global cluster and network from header
    cluster = get_global_cluster()
    network = get_global_network()
    
    if not cluster or not network:
        st.error("Please select a cluster and network from the header above")
        return None
    
    st.sidebar.header("⚙️ Analysis Configuration")
    config = get_analysis_config()
    
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
    
    
    # Set performance settings internally (removed from UI)
    enable_chunking = True
    chunk_size_days = 1  # Fixed to 1 day as requested
    
    return {
        'cluster': cluster,
        'network': network,
        'period1_start': period1_start,
        'period1_end': period1_end,
        'period2_start': period2_start,
        'period2_end': period2_end,
        'enable_comparison': enable_comparison,
        'time_buckets': config['default_time_buckets'],  # Configurable in main analysis area
        'min_samples': config['min_samples_per_analysis'],
        'max_propagation': config['max_propagation_time_ms'],
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
    with st.spinner("🔄 Loading performance analysis data..."):
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
                "Period 1",
                config.get('enable_chunking', True),
                config.get('cluster')
            )
            
            st.session_state.analysis_data['period1'] = period1_data
            
            # Load Period 2 data if comparison enabled
            if config['enable_comparison']:
                period2_data = load_complete_analysis_data(
                    config['network'],
                    datetime.combine(config['period2_start'], datetime.min.time()),
                    datetime.combine(config['period2_end'], datetime.min.time()),
                    "Period 2",
                    config.get('enable_chunking', True),
                    config.get('cluster')
                )
                st.session_state.analysis_data['period2'] = period2_data
            
            # Data quality check
            if period1_data['combined_data'].empty:
                st.warning("⚠️ No data found for the selected period")
            
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
            return True
            
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            st.error(f"❌ Error loading data: {str(e)}")
            st.session_state.data_loaded = False
            return False


def render_analysis_controls() -> Tuple[Dict[str, Any], DataLineageTracker]:
    """
    Render analysis controls with template-based configuration.
    
    Returns:
        Tuple of (configuration dictionary, data lineage tracker)
    """
    st.subheader("📊 Analysis Configuration")
    
    # Initialize data lineage tracker
    lineage = DataLineageTracker()
    
    # Get available data
    if 'period1' not in st.session_state.analysis_data:
        st.warning("No data loaded yet")
        return {}, lineage
        
    data = st.session_state.analysis_data['period1']['combined_data']
    lineage.set_initial_state(data, "Client-level block propagation and performance data")
    
    # Discover metrics dynamically
    exclude_cols = ['slot', 'slot_start_date_time', 'meta_client_name', 
                   'meta_consensus_implementation', 'meta_client_geo_continent_code',
                   'bucket_number', 'bucket_start', 'bucket_end', 'has_gas_data']
    
    metric_info = discover_metrics(data, exclude_cols)
    available_metrics = list(metric_info.keys())
    
    if not available_metrics:
        st.error("No metrics found in the data")
        return {}, lineage
    
    # Template selector at the top
    col1, col2 = st.columns([2, 1])
    with col1:
        template_names = get_template_names() + ["Custom Analysis"]
        selected_template = st.selectbox(
            "📋 Select Analysis Template",
            template_names,
            index=0,  # Default to first template
            help="Choose a pre-configured analysis template or select 'Custom Analysis' for full control"
        )
    
    with col2:
        if selected_template != "Custom Analysis":
            template = get_template(selected_template)
            st.info(f"💡 {template.description}")
    
    # Apply template settings or use custom defaults
    if selected_template != "Custom Analysis":
        template = get_template(selected_template)
        template_config = template.to_dict()
        
        # Validate that template metrics exist in the data
        if template_config['x_metric'] not in available_metrics:
            st.warning(f"Template metric '{template_config['x_metric']}' not available in data.")
            x_metric = available_metrics[0]
        else:
            x_metric = template_config['x_metric']
            
        # Filter y_metrics to only include available ones
        y_metrics = [m for m in template_config['y_metrics'] if m in available_metrics]
        if not y_metrics:
            y_metrics = [m for m in available_metrics if m != x_metric][:2]
            
        # Use template settings
        aggregation_level = template_config['aggregation_level']
        agg_function = template_config['aggregation_function']
        enable_time_buckets = template_config['enable_time_buckets']
        enable_two_stage = template_config['enable_two_stage']
        first_stage_agg = template_config['first_stage_agg']
        second_stage_agg = template_config['second_stage_agg']
        show_trend_line = template_config['show_trend_line']
        show_attestation_deadline = template_config['show_attestation_deadline']
        start_y_from_zero = template_config['start_y_from_zero']
    else:
        # Custom analysis - use defaults
        x_metric = available_metrics[0]
        y_metrics = [m for m in available_metrics if m != x_metric][:2]
        aggregation_level = 'No Aggregation (Raw Data)'
        agg_function = 'mean'
        enable_time_buckets = False
        enable_two_stage = False
        first_stage_agg = 'mean'
        second_stage_agg = 'mean'
        show_trend_line = True
        show_attestation_deadline = True
        start_y_from_zero = True
    
    # Show current settings summary
    st.markdown("### Current Settings")
    settings_col1, settings_col2, settings_col3 = st.columns(3)
    with settings_col1:
        st.write(f"**X-axis:** {x_metric}")
    with settings_col2:
        st.write(f"**Y-axis:** {', '.join(y_metrics)}")
    with settings_col3:
        st.write(f"**Grouping:** {aggregation_level}")
    
    # All detailed settings in advanced expander
    with st.expander("⚙️ Advanced Settings", expanded=(selected_template == "Custom Analysis")):
        
        # Metric Selection
        st.markdown("#### Metric Selection")
        adv_col1, adv_col2 = st.columns(2)
        
        with adv_col1:
            x_metric = st.selectbox(
                "X-axis metric:",
                available_metrics,
                index=available_metrics.index(x_metric),
                key="x_axis_metric",
                help="Select the metric to plot on the X-axis"
            )
        
        with adv_col2:
            # Ensure default y_metrics are in the available options
            available_y_options = [m for m in available_metrics if m != x_metric]
            default_y_metrics = [m for m in y_metrics if m in available_y_options]
            
            y_metrics = st.multiselect(
                "Y-axis metric(s):",
                available_y_options,
                default=default_y_metrics,
                key="y_axis_metrics",
                help="Select one or more metrics to plot on the Y-axis"
            )
        
        # Show metric info in a collapsible container
        if st.checkbox("Show metric information", value=False, key="show_metric_info"):
            metric_info_container = st.container()
            with metric_info_container:
                if x_metric:
                    info = metric_info[x_metric]
                    st.write(f"**{x_metric}**")
                    st.write(f"- Category: {info.category}")
                    st.write(f"- Type: {'Numeric' if info.is_numeric else 'Categorical'}")
                    if info.is_numeric:
                        st.write(f"- Range: {info.min:.2f} - {info.max:.2f} {info.unit}")
                        st.write(f"- Mean: {info.mean:.2f} {info.unit}")
                    st.write(f"- Non-null values: {info.non_null_count:,} ({info.non_null_count/info.count*100:.1f}%)")
        
        # Aggregation Settings
        st.markdown("#### Aggregation Settings")
        agg_col1, agg_col2, agg_col3 = st.columns(3)
        
        with agg_col1:
            # Dynamic aggregation options
            base_options = {
                'No Aggregation (Raw Data)': None,
                'Slot Level': ['slot'],
                'Implementation': ['meta_consensus_implementation'],
                'Geographic (Continent)': ['meta_client_geo_continent_code'],
                'Implementation + Geographic': ['meta_consensus_implementation', 'meta_client_geo_continent_code']
            }
            
            # Add bucketing options if X metric is numeric
            if x_metric and metric_info[x_metric].is_numeric:
                bucket_label = f"{x_metric} Buckets"
                base_options[bucket_label] = ['x_bucket']
                base_options[f"{bucket_label} + Implementation"] = ['x_bucket', 'meta_consensus_implementation']
                base_options[f"{bucket_label} + Geographic"] = ['x_bucket', 'meta_client_geo_continent_code']
            
            # Add time bucket options if enabled
            if enable_time_buckets:
                base_options['Time Buckets'] = ['bucket_number']
                base_options['Time Buckets + Implementation'] = ['bucket_number', 'meta_consensus_implementation']
                if x_metric and metric_info[x_metric].is_numeric:
                    base_options[f'Time Buckets + {x_metric} Buckets'] = ['bucket_number', 'x_bucket']
            
            # Find the index of the current aggregation level
            agg_index = 0
            for i, key in enumerate(base_options.keys()):
                if key == aggregation_level:
                    agg_index = i
                    break
            
            aggregation_level = st.selectbox(
                "Group data by:",
                list(base_options.keys()),
                index=agg_index,
                key="aggregation_level"
            )
            
            group_by = base_options[aggregation_level]
        
        with agg_col2:
            # Two-stage aggregation option
            enable_two_stage = st.checkbox(
                "Enable two-stage aggregation",
                value=enable_two_stage,
                key="enable_two_stage",
                help="First aggregate by slot, then apply a second aggregation to the results"
            )
            
            if enable_two_stage:
                first_stage_agg = st.selectbox(
                    "First stage (per slot):",
                    ['mean', 'median', 'p90', 'p95', 'p99', 'min', 'max'],
                    index=['mean', 'median', 'p90', 'p95', 'p99', 'min', 'max'].index(first_stage_agg),
                    key="first_stage_agg",
                    help="How to aggregate multiple node values for each slot"
                )
                
                second_stage_agg = st.selectbox(
                    "Second stage (overall):",
                    ['mean', 'median', 'p90', 'p95', 'p99', 'min', 'max'],
                    index=['mean', 'median', 'p90', 'p95', 'p99', 'min', 'max'].index(second_stage_agg),
                    key="second_stage_agg",
                    help="How to aggregate the per-slot values"
                )
                
                agg_function = first_stage_agg  # Used for display
            else:
                agg_function = st.selectbox(
                    "How to aggregate:",
                    ['mean', 'median', 'p90', 'p95', 'p99', 'min', 'max'],
                    index=['mean', 'median', 'p90', 'p95', 'p99', 'min', 'max'].index(agg_function),
                    key="agg_function"
                )
        
        with agg_col3:
            # Time bucketing
            enable_time_buckets = st.checkbox(
                "Enable time bucketing",
                value=enable_time_buckets,
                help="Divide data into equal time periods for temporal analysis"
            )
            
            if enable_time_buckets:
                config = get_analysis_config()
                num_time_buckets = st.slider(
                    "Number of time buckets:",
                    min_value=config['min_time_buckets'],
                    max_value=config['max_time_buckets'],
                    value=config['default_time_buckets'],
                    help="Split the time range into this many equal periods"
                )
            else:
                num_time_buckets = None
            
            # Dynamic bucket configuration based on X metric
            if x_metric and metric_info[x_metric].is_numeric and 'x_bucket' in str(group_by):
                x_info = metric_info[x_metric]
                suggested_size = x_info.suggested_bucket_size
                
                if suggested_size:
                    bucket_options = []
                    for factor in [0.25, 0.5, 1.0, 2.0, 4.0]:
                        size = suggested_size * factor
                        bucket_options.append(size)
                    
                    bucket_options = sorted(list(set(bucket_options)))
                    default_idx = bucket_options.index(suggested_size) if suggested_size in bucket_options else 2
                    
                    x_bucket_size = st.selectbox(
                        f"{x_metric} bucket size:",
                        bucket_options,
                        index=default_idx,
                        format_func=lambda x: format_bucket_size(x, x_info.unit),
                        key="x_bucket_size",
                        help=f"Suggested size: {format_bucket_size(suggested_size, x_info.unit)}"
                    )
                else:
                    x_bucket_size = st.number_input(
                        f"{x_metric} bucket size:",
                        value=1.0,
                        key="x_bucket_size"
                    )
            else:
                x_bucket_size = None
        
        # Data Quality Filters
        st.markdown("#### Data Quality Filters")
        filter_col1, filter_col2 = st.columns(2)
        
        with filter_col1:
            max_propagation = st.number_input(
                "Max Propagation Time (ms)",
                min_value=1000,
                max_value=30000,
                value=get_analysis_config()['max_propagation_time_ms'],
                help="Exclude outliers with propagation times above this threshold"
            )
        
        with filter_col2:
            min_samples = st.number_input(
                "Minimum Samples per Group", 
                min_value=10, 
                value=get_analysis_config()['min_samples_per_analysis'],
                help="Minimum data points required per aggregation group"
            )
        
        # Chart Options
        st.markdown("#### Chart Options")
        chart_col1, chart_col2, chart_col3 = st.columns(3)
        
        with chart_col1:
            start_y_from_zero = st.checkbox(
                "Start Y-axis from 0",
                value=start_y_from_zero,
                key="start_y_from_zero",
                help="Force Y-axis to start from zero for better comparison"
            )
            show_reference_line = st.checkbox(
                "Show 1:1 reference line",
                value=False,
                key="show_reference_line",
                help="Display a 1:1 linear reference line to compare against actual trend"
            )
        
        with chart_col2:
            show_attestation_deadline = st.checkbox(
                "Show 4s attestation deadline",
                value=show_attestation_deadline,
                key="show_attestation_deadline",
                help="Display a reference line at 4000ms for attestation timing analysis"
            )
            extrapolate_to_deadline = st.checkbox(
                "Extrapolate trends to 4s line",
                value=False,
                key="extrapolate_to_deadline",
                help="Extend trend lines to 4s deadline and show predicted gas capacity"
            )
        
        with chart_col3:
            show_trend_line = st.checkbox(
                "Show trend lines",
                value=show_trend_line,
                key="show_trend_line",
                help="Display linear regression trend lines on scatter plots"
            )
    
    # Save as template section
    st.divider()
    with st.container():
        save_col1, save_col2 = st.columns([3, 1])
        with save_col1:
            st.markdown("#### 💾 Save Current Configuration as Template")
            st.text("Save your current settings as a reusable template")
        with save_col2:
            if st.button("Save as Template", type="secondary", use_container_width=True):
                st.session_state.show_save_template_dialog = True
        
        if st.session_state.get('show_save_template_dialog', False):
            with st.form("save_template_form"):
                st.markdown("### Save Analysis Template")
                template_name = st.text_input(
                    "Template Name",
                    placeholder="e.g., My Custom Analysis",
                    help="Choose a unique name for your template"
                )
                template_description = st.text_area(
                    "Description",
                    placeholder="Describe what this template analyzes...",
                    help="Brief description of what this template is for"
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("Save Template", type="primary", use_container_width=True):
                        if template_name:
                            # Build the config to save
                            save_config = {
                                'x_metric': x_metric,
                                'y_metrics': y_metrics,
                                'aggregation_level': aggregation_level,
                                'aggregation_function': agg_function,
                                'enable_time_buckets': enable_time_buckets,
                                'enable_two_stage': enable_two_stage,
                                'first_stage_agg': first_stage_agg,
                                'second_stage_agg': second_stage_agg,
                                'show_trend_line': show_trend_line,
                                'show_attestation_deadline': show_attestation_deadline,
                                'start_y_from_zero': start_y_from_zero
                            }
                            
                            if save_template(save_config, template_name, template_description):
                                st.success(f"✅ Template '{template_name}' saved successfully!")
                                st.session_state.show_save_template_dialog = False
                                st.rerun()
                            else:
                                st.error("Failed to save template")
                        else:
                            st.error("Please provide a template name")
                
                with col2:
                    if st.form_submit_button("Cancel", use_container_width=True):
                        st.session_state.show_save_template_dialog = False
                        st.rerun()
    
    # Build configuration
    selected_metrics = [x_metric] + y_metrics if y_metrics else [x_metric]
    config = {
        'x_metric': x_metric,
        'y_metrics': y_metrics,
        'metrics': selected_metrics,
        'group_by': group_by,
        'agg_function': agg_function,
        'aggregation_level': aggregation_level,
        'x_bucket_size': x_bucket_size,
        'start_y_from_zero': start_y_from_zero,
        'show_attestation_deadline': show_attestation_deadline,
        'extrapolate_to_deadline': extrapolate_to_deadline,
        'show_reference_line': show_reference_line,
        'show_trend_line': show_trend_line,
        'metric_info': metric_info,
        'num_time_buckets': num_time_buckets,
        'max_propagation': max_propagation,
        'min_samples': min_samples,
        'enable_two_stage': enable_two_stage
    }
    
    if enable_two_stage:
        config['first_stage_agg'] = first_stage_agg
        config['second_stage_agg'] = second_stage_agg
    
    # Data Processing Explanation
    with st.expander("🔍 Data Processing Explanation", expanded=False):
        if group_by:
            # Build human-readable group descriptions
            group_descriptions = []
            for g in group_by:
                if g == 'x_bucket':
                    group_descriptions.append(f"{x_metric} buckets (size: {format_bucket_size(x_bucket_size, metric_info[x_metric].unit)})")
                elif g == 'bucket_number':
                    group_descriptions.append("time buckets")
                elif g == 'meta_consensus_implementation':
                    group_descriptions.append("consensus implementation")
                elif g == 'meta_client_geo_continent_code':
                    group_descriptions.append("geographic continent")
                elif g == 'slot':
                    group_descriptions.append("individual slot")
                else:
                    group_descriptions.append(g)
            
            # Build metric descriptions
            metric_descriptions = []
            for m in selected_metrics:
                m_info = metric_info.get(m, None)
                if m_info:
                    desc = f"{m}"
                    if m_info.unit:
                        desc += f" ({m_info.unit})"
                    metric_descriptions.append(desc)
                else:
                    metric_descriptions.append(m)
            
            if config.get('enable_two_stage', False):
                explanation = f"**Two-Stage Aggregation Process:**\n\n"
                explanation += f"**Stage 1:** For each unique slot:\n"
                explanation += f"- Take all client observations for that slot\n"
                explanation += f"- Calculate the **{first_stage_agg}** of: {', '.join(metric_descriptions)}\n"
                explanation += f"- Result: One value per slot (reduces ~30 clients → 1 value)\n\n"
                
                explanation += f"**Stage 2:** Group the slot-aggregated data by: **{', '.join(group_descriptions)}**\n"
                explanation += f"- Calculate the **{second_stage_agg}** of the Stage 1 results\n"
                explanation += f"- Result: One value per {' + '.join(group_descriptions)}\n\n"
                
                explanation += f"**Example with your current selection:**\n"
                if 'x_bucket' in group_by:
                    explanation += f"- Stage 1: For slot 12345, if 30 clients report {x_metric}, calculate {first_stage_agg} → single value\n"
                    explanation += f"- Stage 2: Group all slots by {x_metric} bucket, calculate {second_stage_agg} of slot values → one value per bucket"
                else:
                    explanation += f"- Stage 1: For each slot, aggregate all client measurements → slot-level {first_stage_agg}\n"
                    explanation += f"- Stage 2: Group by {', '.join(group_descriptions)}, calculate {second_stage_agg} → final values"
            else:
                explanation = f"**Single-Stage Aggregation Process:**\n\n"
                explanation += f"**Grouping:** {', '.join(group_descriptions)}\n"
                explanation += f"**Metrics:** {', '.join(metric_descriptions)}\n"
                explanation += f"**Aggregation:** {agg_function}\n\n"
                
                explanation += f"**Process:**\n"
                explanation += f"1. Take all records in the dataset\n"
                explanation += f"2. Group records by: {', '.join(group_descriptions)}\n"
                explanation += f"3. For each group, calculate the {agg_function} of each metric\n\n"
                
                explanation += f"**Example with your current selection:**\n"
                if 'x_bucket' in group_by:
                    bucket_info = metric_info[x_metric]
                    explanation += f"- All records with {x_metric} between 0-{format_bucket_size(x_bucket_size, bucket_info.unit)} go in bucket 1\n"
                    explanation += f"- Calculate {agg_function} of {', '.join(y_metrics)} for all records in bucket 1\n"
                    explanation += f"- Repeat for each {x_metric} bucket"
                elif 'meta_consensus_implementation' in group_by:
                    explanation += f"- All records from Lighthouse clients grouped together\n"
                    explanation += f"- All records from Prysm clients grouped together\n"
                    explanation += f"- Calculate {agg_function} of metrics for each implementation"
                else:
                    explanation += f"- Records grouped by {', '.join(group_descriptions)}\n"
                    explanation += f"- Calculate {agg_function} for each group"
        else:
            explanation = "**No Aggregation - Raw Data:**\n\n"
            explanation += f"**Displaying:** Individual client observations\n"
            explanation += f"**X-axis:** {x_metric}"
            if metric_info[x_metric].unit:
                explanation += f" ({metric_info[x_metric].unit})"
            explanation += f"\n**Y-axis:** {', '.join(y_metrics)}\n\n"
            explanation += "Each point represents a single client's observation of a single block.\n"
            explanation += "No averaging or grouping is applied."
            
        st.markdown(explanation)
        
        # Add data volume warning
        if not group_by and len(data) > 100000:
            st.warning(f"⚠️ Large dataset: {len(data):,} raw records. Consider using aggregation for better performance.")
    
    return config, lineage


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
    analysis_config, lineage_tracker = render_analysis_controls()
    
    if not analysis_config:
        return
        
    if not analysis_config.get('x_metric') or not analysis_config.get('metrics'):
        st.warning("⚠️ Please select metrics for analysis")
        return
    
    # Apply user-controlled aggregation
    if analysis_config['group_by'] is not None:
        # Check if time bucket aggregation is requested
        needs_time_bucketed_data = any('bucket_number' in str(col) for col in analysis_config['group_by'])
        
        # Check if X-axis bucket aggregation is requested
        needs_x_bucketed_data = any('x_bucket' in str(col) for col in analysis_config['group_by'])
        
        # Start with the appropriate base data
        if needs_time_bucketed_data and not period1_bucketed.empty:
            source_data = period1_bucketed
            lineage_tracker.add_filter(
                "Using time-bucketed data",
                len(period1_data),
                len(period1_bucketed)
            )
        else:
            source_data = period1_data
            
        # Apply X-axis bucketing if needed
        if needs_x_bucketed_data and analysis_config.get('x_bucket_size'):
            x_metric = analysis_config['x_metric']
            bucket_size = analysis_config['x_bucket_size']
            
            source_data = create_dynamic_buckets(
                source_data,
                x_metric,
                bucket_size,
                'x_bucket'
            )
            
            if 'x_bucket' in source_data.columns:
                num_buckets = source_data['x_bucket'].nunique()
                lineage_tracker.add_bucketing(x_metric, bucket_size, num_buckets)
            else:
                st.warning(f"⚠️ Could not create buckets for {x_metric}")
                # Remove x_bucket from group_by to prevent errors
                analysis_config['group_by'] = [g for g in analysis_config['group_by'] if g != 'x_bucket']
        
        # Handle two-stage aggregation if enabled
        if analysis_config.get('enable_two_stage', False):
            # Two-stage aggregation: first by slot, then by the selected grouping
            with st.spinner(f"Two-stage aggregation: First stage ({analysis_config['first_stage_agg']} per slot)..."):
                # First stage: aggregate by slot AND any other grouping columns
                # This preserves categories like gas buckets, implementations, etc.
                first_stage_group_by = ['slot']
                if analysis_config['group_by']:
                    # Add the other grouping columns (e.g., x_bucket, implementation)
                    for col in analysis_config['group_by']:
                        if col != 'slot' and col in source_data.columns:
                            first_stage_group_by.append(col)
                
                records_before = len(source_data)
                first_stage_data = aggregate_data(
                    source_data,
                    group_by=first_stage_group_by,
                    metrics=analysis_config['metrics'],
                    agg_function=analysis_config['first_stage_agg']
                )
                
                lineage_tracker.add_aggregation(
                    f"First stage: {analysis_config['first_stage_agg']} per slot",
                    first_stage_group_by,
                    analysis_config['first_stage_agg'],
                    records_before,
                    len(first_stage_data),
                    is_two_stage=True
                )
                
                # Update column names to reflect first stage aggregation
                # This is important for the second stage to work correctly
                metric_cols_to_rename = {}
                for metric in analysis_config['metrics']:
                    if metric in first_stage_data.columns:
                        # Column might already have aggregation suffix
                        metric_cols_to_rename[metric] = metric
                    else:
                        # Look for aggregated column
                        for col in first_stage_data.columns:
                            if col.startswith(metric) and col.endswith(f"_{analysis_config['first_stage_agg']}"):
                                metric_cols_to_rename[col] = metric
                                break
                
            with st.spinner(f"Two-stage aggregation: Second stage ({analysis_config['second_stage_agg']} per group)..."):
                # Second stage: aggregate by the non-slot grouping columns
                # Remove 'slot' from grouping to aggregate across slots
                second_stage_group_by = [col for col in first_stage_group_by if col != 'slot']
                
                if second_stage_group_by:
                    # Group by the remaining columns (e.g., x_bucket)
                    # and apply the second aggregation function
                    records_before_stage2 = len(first_stage_data)
                    aggregated_data = aggregate_data(
                        first_stage_data,
                        group_by=second_stage_group_by,
                        metrics=list(metric_cols_to_rename.keys()),
                        agg_function=analysis_config['second_stage_agg']
                    )
                    
                    lineage_tracker.add_aggregation(
                        f"Second stage: {analysis_config['second_stage_agg']} across slots",
                        second_stage_group_by,
                        analysis_config['second_stage_agg'],
                        records_before_stage2,
                        len(aggregated_data),
                        is_two_stage=True
                    )
                    
                    # Rename columns back to original metric names
                    rename_dict = {}
                    for col in aggregated_data.columns:
                        for agg_col, orig_metric in metric_cols_to_rename.items():
                            if col.startswith(agg_col):
                                rename_dict[col] = orig_metric
                                break
                    
                    if rename_dict:
                        aggregated_data = aggregated_data.rename(columns=rename_dict)
                    
                else:
                    # No grouping columns left, calculate single overall value
                    agg_results = {}
                    for col, orig_metric in metric_cols_to_rename.items():
                        if col in first_stage_data.columns:
                            values = first_stage_data[col].dropna()
                            if len(values) > 0:
                                if analysis_config['second_stage_agg'] == 'mean':
                                    agg_results[orig_metric] = values.mean()
                                elif analysis_config['second_stage_agg'] == 'median':
                                    agg_results[orig_metric] = values.median()
                                elif analysis_config['second_stage_agg'] == 'p90':
                                    agg_results[orig_metric] = values.quantile(0.90)
                                elif analysis_config['second_stage_agg'] == 'p95':
                                    agg_results[orig_metric] = values.quantile(0.95)
                                elif analysis_config['second_stage_agg'] == 'p99':
                                    agg_results[orig_metric] = values.quantile(0.99)
                                elif analysis_config['second_stage_agg'] == 'min':
                                    agg_results[orig_metric] = values.min()
                                elif analysis_config['second_stage_agg'] == 'max':
                                    agg_results[orig_metric] = values.max()
                    
                    # Create a single-row DataFrame with the results
                    aggregated_data = pd.DataFrame([agg_results])
                    
                    st.info(f"📊 Two-stage result: {analysis_config['first_stage_agg']} per slot → {analysis_config['second_stage_agg']} overall")
                    
                    # Show the actual values
                    if not aggregated_data.empty:
                        st.write("**Final aggregated values:**")
                        display_data = {}
                        for col in aggregated_data.columns:
                            if col in analysis_config['metrics']:
                                info = get_metric_info(col)
                                display_data[info['title']] = f"{aggregated_data[col].iloc[0]:.2f} {info['unit']}"
                        
                        # Display in columns
                        cols = st.columns(len(display_data))
                        for idx, (metric, value) in enumerate(display_data.items()):
                            with cols[idx]:
                                st.metric(metric, value)
                
        else:
            # Regular single-stage aggregation
            with st.spinner(f"Aggregating {len(source_data):,} records..."):
                records_before = len(source_data)
                aggregated_data = aggregate_data(
                    source_data,
                    group_by=analysis_config['group_by'],
                    metrics=analysis_config['metrics'],
                    agg_function=analysis_config['agg_function']
                )
                
                lineage_tracker.add_aggregation(
                    f"Aggregated using {analysis_config['agg_function']}",
                    analysis_config['group_by'],
                    analysis_config['agg_function'],
                    records_before,
                    len(aggregated_data)
                )
        
        # Show aggregation results for debugging
        with st.expander("🔍 Aggregation Details", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Aggregated data shape:** {aggregated_data.shape}")
                st.write(f"**Grouping columns:** {analysis_config['group_by']}")
                if 'meta_consensus_implementation' in aggregated_data.columns:
                    implementations = aggregated_data['meta_consensus_implementation'].unique()
                    st.write(f"**Implementations found:** {', '.join(implementations)}")
                    
                    # Show node count per implementation
                    period1_data_info = st.session_state.analysis_data.get('period1', {})
                    if period1_data_info and 'combined_data' in period1_data_info:
                        original_data = period1_data_info['combined_data']
                        if 'meta_client_name' in original_data.columns:
                            impl_node_counts = []
                            for impl in implementations:
                                node_count = original_data[original_data['meta_consensus_implementation'] == impl]['meta_client_name'].nunique()
                                impl_node_counts.append(f"{impl}: {node_count}")
                            st.write(f"**Node counts:** {', '.join(impl_node_counts)}")
            with col2:
                st.write(f"**Available columns:** {', '.join(aggregated_data.columns)}")
                if 'gas_bucket' in aggregated_data.columns:
                    gas_buckets = sorted(aggregated_data['gas_bucket'].unique())
                    st.write(f"**Gas buckets:** {gas_buckets}")
        
        # If aggregated data is still too large, suggest higher-level aggregation
        max_chart_points = 100_000  # Modern browsers can handle this easily
        if len(aggregated_data) > max_chart_points:
            st.warning(f"⚠️ Large dataset ({len(aggregated_data):,} records). Charts may be slow. Consider using higher-level aggregation for better performance.")
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
    
    # Show any warnings from data processing
    warnings = lineage_tracker.get_warnings()
    if warnings:
        for warning in warnings:
            st.warning(warning)
    
    # Correlation Analysis (only visualization option)
    with st.spinner("Generating correlation analysis..."):
        render_correlation_analysis(
            display_data, 
            analysis_config['x_metric'], 
            analysis_config['y_metrics'],
            analysis_config['agg_function'], 
            analysis_config, 
            st.session_state.analysis_data.get('period1', {})
        )
    


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
    
    # Extract block counts and unique nodes
    if 'combined_data' in period_data and not period_data['combined_data'].empty:
        # Count unique blocks (slots)
        unique_blocks = period_data['combined_data']['slot'].nunique() if 'slot' in period_data['combined_data'].columns else len(period_data['combined_data'])
        metadata['total_blocks'] = unique_blocks
        
        # Count unique nodes (clients)
        if 'meta_client_name' in period_data['combined_data'].columns:
            unique_nodes = period_data['combined_data']['meta_client_name'].nunique()
            metadata['unique_nodes'] = unique_nodes
    
    return metadata


def render_correlation_analysis(data: pd.DataFrame, x_metric: str, y_metrics: List[str], 
                               agg_function: str = "mean", analysis_config: Dict[str, Any] = None, 
                               period_data: Dict[str, Any] = None):
    """Render correlation analysis section with pre-selected metrics."""
    
    if data.empty:
        st.warning("No data available for correlation analysis")
        return
    
    if not x_metric or not y_metrics:
        st.warning("Please select metrics for analysis")
        return
    
    # Handle aggregated data - map original metrics to their aggregated versions
    metric_mapping = {}  # original -> aggregated column name
    
    # Map X metric - special handling for bucketed data
    if 'x_bucket' in analysis_config.get('group_by', []) and 'x_bucket_midpoint' in data.columns:
        # Use bucket midpoint for x-axis when grouping by x_bucket
        metric_mapping[x_metric] = 'x_bucket_midpoint'
    elif x_metric in data.columns:
        metric_mapping[x_metric] = x_metric
    else:
        # Look for aggregated version
        for agg_suffix in ['_mean', '_median', '_p90', '_p95', '_p99', '_min', '_max']:
            agg_metric = f"{x_metric}{agg_suffix}"
            if agg_metric in data.columns:
                metric_mapping[x_metric] = agg_metric
                break
    
    # Map Y metrics
    for metric in y_metrics:
        if metric in data.columns:
            metric_mapping[metric] = metric
        else:
            # Look for aggregated version
            for agg_suffix in ['_mean', '_median', '_p90', '_p95', '_p99', '_min', '_max']:
                agg_metric = f"{metric}{agg_suffix}"
                if agg_metric in data.columns:
                    metric_mapping[metric] = agg_metric
                    break
    
    # Check if all metrics are mapped
    if x_metric not in metric_mapping:
        st.error(f"X-axis metric '{x_metric}' not found in data")
        return
        
    missing_y = [m for m in y_metrics if m not in metric_mapping]
    if missing_y:
        st.warning(f"Y-axis metrics not found: {missing_y}")
        y_metrics = [m for m in y_metrics if m in metric_mapping]
        if not y_metrics:
            return
    
    try:
        # Prepare data for visualization (sample if too large)
        config = get_analysis_config()
        viz_data = data
        if len(data) > config.get('max_visualization_points', 100_000):
            viz_data = prepare_large_dataset(data, max_rows=config.get('max_visualization_points', 100_000))
        
        # Create chart metadata
        chart_metadata = create_chart_metadata(analysis_config or {}, period_data or {})
        
        # Add aggregation level information to metadata
        if analysis_config and 'aggregation_level' in analysis_config:
            chart_metadata['aggregation_level'] = analysis_config['aggregation_level']
        
        # Add original combined data for node counting in plots
        if period_data and 'combined_data' in period_data:
            chart_metadata['combined_data'] = period_data['combined_data']
        
        # If working with aggregated data, ensure we still show unique nodes from original data
        if 'unique_nodes' not in chart_metadata and period_data and 'combined_data' in period_data:
            if 'meta_client_name' in period_data['combined_data'].columns:
                chart_metadata['unique_nodes'] = period_data['combined_data']['meta_client_name'].nunique()
        
        # Map selected metrics to actual column names in the data
        actual_x_metric = metric_mapping.get(x_metric, x_metric)
        actual_y_metrics = [metric_mapping.get(y, y) for y in y_metrics]
        
        # Build aggregation description for plot title
        if analysis_config.get('enable_two_stage', False):
            # Create descriptive aggregation string for two-stage
            grouping_desc = ""
            if analysis_config.get('group_by'):
                group_names = []
                for g in analysis_config['group_by']:
                    if g == 'x_bucket':
                        group_names.append(f'{x_metric} bucket')
                    elif g == 'bucket_number':
                        group_names.append('time bucket')
                    elif g == 'meta_consensus_implementation':
                        group_names.append('implementation')
                    elif g == 'meta_client_geo_continent_code':
                        group_names.append('continent')
                    else:
                        group_names.append(g)
                grouping_desc = f" by {', '.join(group_names)}"
            
            agg_desc = f"{analysis_config['second_stage_agg'].upper()}({analysis_config['first_stage_agg']} per slot) grouped{grouping_desc}"
        else:
            agg_desc = agg_function if agg_function else analysis_config.get('agg_function', 'mean')
        
        # Always use multi y-axis chart for consistency
        fig = create_multi_y_correlation_plot(
            viz_data, actual_x_metric, actual_y_metrics,
            title_suffix="",
            agg_function=agg_desc,
            network=chart_metadata.get('network'),
            time_range=chart_metadata.get('time_range'),
            metadata=chart_metadata,
            start_y_from_zero=analysis_config.get('start_y_from_zero', True),
            show_attestation_deadline=analysis_config.get('show_attestation_deadline', True),
            extrapolate_to_deadline=analysis_config.get('extrapolate_to_deadline', False),
            show_reference_line=analysis_config.get('show_reference_line', False),
            show_trend_line=analysis_config.get('show_trend_line', True)
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Show correlation matrix if we have enough metrics
        all_metrics = [x_metric] + y_metrics
        if len(all_metrics) > 2:
            st.write("#### Correlation Matrix")
            # Use actual column names for correlation matrix
            actual_all_metrics = [metric_mapping.get(m, m) for m in all_metrics]
            corr_fig = create_correlation_matrix(viz_data, actual_all_metrics)
            st.plotly_chart(corr_fig, use_container_width=True)
            
    except Exception as e:
        st.error(f"Error creating correlation plot: {str(e)}")
        st.write(f"Data shape: {data.shape}")
        st.write(f"X metric ({x_metric}) mapped to column: {metric_mapping.get(x_metric, 'NOT FOUND')}")
        if y_metrics:
            for y_metric in y_metrics:
                st.write(f"Y metric ({y_metric}) mapped to column: {metric_mapping.get(y_metric, 'NOT FOUND')}")


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
            
            # Add aggregation level information to metadata
            if analysis_config and 'aggregation_level' in analysis_config:
                chart_metadata['aggregation_level'] = analysis_config['aggregation_level']
            
            # Add original combined data for node counting in plots
            if period_data and 'combined_data' in period_data:
                chart_metadata['combined_data'] = period_data['combined_data']
            
            # If working with aggregated data, ensure we still show unique nodes from original data
            if 'unique_nodes' not in chart_metadata and period_data and 'combined_data' in period_data:
                if 'meta_client_name' in period_data['combined_data'].columns:
                    chart_metadata['unique_nodes'] = period_data['combined_data']['meta_client_name'].nunique()
            
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
            st.write("#### Metric Bucket Analysis")
            
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
            
            st.write(f"**Data grouped by metric buckets** (showing {len(gas_bucket_metrics)} buckets)")
            st.dataframe(gas_bucket_metrics, use_container_width=True)
            
            # Allow users to select specific gas buckets
            bucket_options = sorted(bucketed_data['gas_bucket_label'].dropna().unique())
            selected_buckets = st.multiselect(
                "Select metric buckets to highlight in charts:",
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
    
    # Metric binned analysis
    st.write("#### Metric Correlation Analysis")
    
    execution_metrics = [m for m in metrics if 'gas' in m.lower() or 'blob' in m.lower()]
    timing_metrics = [m for m in metrics if 'time' in m.lower() or 'gossip' in m.lower()]
    
    if execution_metrics and timing_metrics:
        bin_metric = st.selectbox("Binning metric:", execution_metrics, key="gas_bin_metric")
        analysis_metric = st.selectbox("Analysis metric:", timing_metrics, key="perf_bin_metric")
        
        # Calculate metric binned analysis
        binned_analysis = calculate_gas_binned_analysis(data, bin_metric, analysis_metric)
        
        if not binned_analysis.empty:
            fig = create_gas_binned_performance_plot(
                binned_analysis,
                f"{analysis_metric}_mean",
                title_suffix=" - Metric Binned Analysis"
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
    # Render the global header
    render_global_header()
    
    apply_ethPandaOps_styling()
    
    # Initialize session state
    initialize_session_state()
    
    # Page title
    st.markdown('<h1 class="main-header">📊 Multi-Metric Performance Analysis</h1>', unsafe_allow_html=True)
    
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
            - Multi-metric correlation analysis
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
        example_metrics = ['gas_used', 'block_gossip_time', 'head_time', 'data_available', 'gas_utilization']
        
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