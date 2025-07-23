"""
Plot generation utilities for gas usage performance analysis.

This module provides interactive Plotly visualizations with consistent
ethPandaOps branding and styling.
"""

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, Any, List, Optional, Union
import logging

from shared.ui_components import add_ethPandaOps_logo
from .config_utils import get_metric_info, get_analysis_config, get_continents
from .metrics_calculators import calculate_correlation_analysis


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_gas_vs_arrival_scatter(
    data: pd.DataFrame,
    x_metric: str = 'gas_used',
    y_metric: str = 'block_gossip_time_mean',
    color_by: Optional[str] = None,
    size_by: Optional[str] = None,
    title_suffix: str = "",
    agg_function: str = "mean",
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    show_reference_line: bool = False
) -> go.Figure:
    """
    Create interactive scatter plot of gas usage vs arrival times.
    Includes trend line, correlation info, and time-based coloring.
    
    Args:
        data: DataFrame with gas and performance data
        x_metric: Column name for x-axis (gas metric)
        y_metric: Column name for y-axis (performance metric)
        color_by: Column to color points by
        size_by: Optional column to size points by
        title_suffix: Additional text for plot title
        
    Returns:
        Plotly figure object
    """
    if data.empty:
        logger.warning("Cannot create scatter plot: empty data")
        return go.Figure()
    
    x_info = get_metric_info(x_metric)
    y_info = get_metric_info(y_metric)
    
    # Calculate correlation (handle case where scipy is not available)
    try:
        correlation_data = calculate_correlation_analysis(data, x_metric, y_metric)
    except ImportError as e:
        logger.warning(f"Correlation analysis not available: {e}")
        correlation_data = None
    
    # Create enhanced title with aggregation info and better meta display
    agg_suffix = f" ({agg_function.title()})" if agg_function and agg_function != "mean" else ""
    main_title = f'{x_info["title"]} vs {y_info["title"]}{agg_suffix}{title_suffix}'
    
    # Create clean metadata annotation instead of subtitle overflow
    metadata_parts = []
    if network:
        metadata_parts.append(f"Network: {network.title()}")
    if time_range:
        metadata_parts.append(f"Period: {time_range}")
    
    # Add data point count and unique nodes
    data_count = len(data)
    if metadata and 'total_blocks' in metadata:
        block_info = f"Points: {data_count:,} (from {metadata['total_blocks']:,} blocks)"
        if 'unique_nodes' in metadata:
            block_info += f", {metadata['unique_nodes']} nodes"
        metadata_parts.append(block_info)
    else:
        metadata_parts.append(f"Data Points: {data_count:,}")
    
    # Add correlation statistics to metadata if available
    if correlation_data:
        metadata_parts.append(f"Correlation: r={correlation_data['correlation']:.3f} (p={correlation_data['p_value']:.4f})")
        metadata_parts.append(f"R²={correlation_data['r_squared']:.3f}")
    
    # Use annotations instead of title overflow
    title = main_title
    
    
    # Prepare hover data - adapt to available columns
    hover_data = []
    
    # Add identifier column based on what's available
    if 'slot' in data.columns:
        hover_data.append('slot')
    elif 'bucket_number' in data.columns:
        hover_data.append('bucket_number')
    elif 'gas_bucket' in data.columns:
        hover_data.append('gas_bucket')
        if 'gas_bucket_label' in data.columns:
            hover_data.append('gas_bucket_label')
    
    # Add categorical columns if available
    if 'consensus_implementations' in data.columns:
        hover_data.append('consensus_implementations')
    elif 'meta_consensus_implementation' in data.columns:
        hover_data.append('meta_consensus_implementation')
        
    if 'continents' in data.columns:
        hover_data.append('continents')
    elif 'meta_client_geo_continent_code' in data.columns:
        hover_data.append('meta_client_geo_continent_code')
    
    # Choose grouping for discrete series (avoid continuous scales)
    # Prioritize consensus implementation for coloring, then continent
    color_column = None
    if 'meta_consensus_implementation' in data.columns and data['meta_consensus_implementation'].nunique() <= 10:
        color_column = 'meta_consensus_implementation'
    elif 'meta_client_geo_continent_code' in data.columns and data['meta_client_geo_continent_code'].nunique() <= 10:
        color_column = 'meta_client_geo_continent_code'
    elif 'gas_bucket' in data.columns and data['gas_bucket'].nunique() <= 15:
        color_column = 'gas_bucket'
    
    # Create scatter plot with discrete color grouping if available
    if color_column and data[color_column].nunique() <= 10:  # Limit to reasonable number of groups
        fig = px.scatter(
            data,
            x=x_metric,
            y=y_metric,
            color=color_column,
            title=title,
            labels={
                x_metric: f'{x_info["title"]} ({x_info["unit"]})',
                y_metric: f'{y_info["title"]} ({y_info["unit"]})',
                color_column: color_column.replace('_', ' ').title()
            },
            hover_data=hover_data,
            color_discrete_sequence=px.colors.qualitative.Set1
        )
        
        # Improve marker size for aggregated data
        fig.update_traces(marker=dict(size=8, opacity=0.8))
        
        # Add node count to legend names if we have implementation/continent grouping and original data
        if (metadata and 'combined_data' in metadata and 
            'meta_client_name' in metadata['combined_data'].columns and
            color_column in ['meta_consensus_implementation', 'meta_client_geo_continent_code']):
            
            # Update legend names to include node counts
            original_data = metadata['combined_data']
            for trace in fig.data:
                if hasattr(trace, 'name') and trace.name:
                    # Find group name from trace
                    group_name = trace.name
                    group_nodes = original_data[original_data[color_column] == group_name]['meta_client_name'].nunique()
                    trace.name = f"{group_name} ({group_nodes} nodes)"
    else:
        # Single series if no good grouping column
        fig = px.scatter(
            data,
            x=x_metric,
            y=y_metric,
            title=title,
            labels={
                x_metric: f'{x_info["title"]} ({x_info["unit"]})',
                y_metric: f'{y_info["title"]} ({y_info["unit"]})'
            },
            hover_data=hover_data
        )
    
    # Always add trend line if correlation data available
    if correlation_data and len(data) > 10:
        x_range = np.linspace(data[x_metric].min(), data[x_metric].max(), 100)
        y_trend = correlation_data['slope'] * x_range + correlation_data['intercept']
        
        fig.add_trace(go.Scatter(
            x=x_range,
            y=y_trend,
            mode='lines',
            name='Actual Trend',
            line=dict(dash='dash', color='red', width=2),
            hovertemplate=f'Actual Trend<br>Slope: {correlation_data["slope"]:.2e}<extra></extra>'
        ))
    
    # Add 1:1 reference line if requested and metrics are comparable
    if show_reference_line and 'gas' in x_metric.lower() and 'time' in y_metric.lower():
        # For gas vs time, we need to scale appropriately
        # Assume 1 unit of gas = some constant time (need to determine scale)
        x_min, x_max = data[x_metric].min(), data[x_metric].max()
        
        # Calculate a reasonable scale factor based on the data
        # Use the mean ratio as a starting point
        gas_mean = data[x_metric].mean()
        time_mean = data[y_metric].mean()
        scale_factor = time_mean / gas_mean if gas_mean > 0 else 1
        
        x_ref = np.array([x_min, x_max])
        y_ref = x_ref * scale_factor  # 1:1 linear relationship with scaling
        
        fig.add_trace(go.Scatter(
            x=x_ref,
            y=y_ref,
            mode='lines',
            name='1:1 Linear Reference',
            line=dict(dash='dot', color='black', width=2),
            hovertemplate=f'1:1 Linear Reference<br>Scale: 1 gas = {scale_factor:.2e} ms<extra></extra>'
        ))
    
    # Update layout with clean axis lines, interactive legend, and metadata annotations
    fig.update_layout(
        height=600,
        showlegend=True,
        title={'font': {'size': 16}},
        xaxis_title_font_size=14,
        yaxis_title_font_size=14,
        hovermode='closest',
        legend=dict(
            itemclick="toggle",
            itemdoubleclick="toggleothers",
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02
        ),
        xaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            mirror=False,
            ticks='outside',
            rangemode='tozero',
            title=f'{x_info["title"]} ({x_info["unit"]})'
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            mirror=False,
            ticks='outside',
            rangemode='tozero',
            title=f'{y_info["title"]} ({y_info["unit"]})'
        ),
        margin=dict(r=200),  # Right margin for legend with node counts
        annotations=[
            dict(
                text=' | '.join(metadata_parts),
                showarrow=False,
                xref="paper", yref="paper",
                x=0, y=-0.1,
                xanchor='left', yanchor='top',
                font=dict(size=10, color="gray")
            )
        ] if metadata_parts else None
    )
    
    return add_ethPandaOps_logo(fig)


def create_time_series_comparison(
    time_metrics: pd.DataFrame,
    metrics_to_plot: List[str],
    title_suffix: str = "",
    agg_function: str = "mean",
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None
) -> go.Figure:
    """
    Create multi-axis time series plot for temporal analysis with visible legends.
    
    Args:
        time_metrics: DataFrame with time bucket metrics
        metrics_to_plot: List of metric columns to plot
        title_suffix: Additional text for plot title
        
    Returns:
        Plotly figure with dual y-axes and visible legends
    """
    if time_metrics.empty:
        logger.warning("Cannot create time series: empty data")
        return go.Figure()
    
    # Create subplot with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Define which metrics go on which axis
    gas_metrics = [m for m in metrics_to_plot if 'gas' in m.lower()]
    timing_metrics = [m for m in metrics_to_plot if 'time' in m.lower() or 'gossip' in m.lower() or 'head' in m.lower()]
    
    colors = px.colors.qualitative.Set1
    color_idx = 0
    
    # Get x values for plotting
    x_values = time_metrics.index if hasattr(time_metrics, 'index') else time_metrics.get('time_bucket', range(len(time_metrics)))
    
    # Plot gas metrics on primary y-axis
    for metric in gas_metrics:
        if metric in time_metrics.columns:
            metric_info = get_metric_info(metric.replace('_mean', ''))
            agg_suffix = f" ({agg_function.title()})" if agg_function != "mean" else ""
            fig.add_trace(
                go.Scatter(
                    x=x_values,
                    y=time_metrics[metric],
                    name=f'{metric_info["title"]}{agg_suffix}',
                    line=dict(color=colors[color_idx % len(colors)], width=2),
                    mode='lines+markers',
                    marker=dict(size=6),
                    hovertemplate=f'{metric_info["title"]}: %{{y:.2f}} {metric_info["unit"]}<br>Time Bucket: %{{x}}<extra></extra>',
                    showlegend=True
                ),
                secondary_y=False
            )
            color_idx += 1
    
    # Plot timing metrics on secondary y-axis
    for metric in timing_metrics:
        if metric in time_metrics.columns:
            metric_info = get_metric_info(metric.replace('_mean', ''))
            agg_suffix = f" ({agg_function.title()})" if agg_function != "mean" else ""
            fig.add_trace(
                go.Scatter(
                    x=x_values,
                    y=time_metrics[metric],
                    name=f'{metric_info["title"]}{agg_suffix}',
                    line=dict(color=colors[color_idx % len(colors)], width=2, dash='dash'),
                    mode='lines+markers',
                    marker=dict(size=6, symbol='diamond'),
                    hovertemplate=f'{metric_info["title"]}: %{{y:.2f}} {metric_info["unit"]}<br>Time Bucket: %{{x}}<extra></extra>',
                    showlegend=True
                ),
                secondary_y=True
            )
            color_idx += 1
    
    # Update axis labels with better titles
    if gas_metrics:
        fig.update_yaxes(title_text="Gas Metrics", secondary_y=False)
    if timing_metrics:
        fig.update_yaxes(title_text="Performance Metrics (ms)", secondary_y=True)
    fig.update_xaxes(title_text="Time Bucket")
    
    # Create enhanced title with aggregation info and metadata
    agg_suffix = f" ({agg_function.title()})" if agg_function and agg_function != "mean" else ""
    main_title = f"Time Series Analysis{agg_suffix}{title_suffix}"
    
    # Create clean metadata for annotation
    metadata_parts = []
    if network:
        metadata_parts.append(f"Network: {network.title()}")
    if time_range:
        metadata_parts.append(f"Period: {time_range}")
    
    # Add bucket and data point information
    num_buckets = len(time_metrics)
    if metadata and 'total_blocks' in metadata:
        bucket_info = f"Buckets: {num_buckets} (from {metadata['total_blocks']:,} blocks)"
        if 'unique_nodes' in metadata:
            bucket_info += f", {metadata['unique_nodes']} nodes"
        metadata_parts.append(bucket_info)
    else:
        metadata_parts.append(f"Time Buckets: {num_buckets}")
    
    # Add aggregation description to metadata
    agg_descriptions = {
        'mean': 'average',
        'median': 'median (50th percentile)',
        'p95': '95th percentile', 
        'p99': '99th percentile',
        'min': 'minimum',
        'max': 'maximum'
    }
    agg_desc = agg_descriptions.get(agg_function, agg_function)
    metadata_parts.append(f"Aggregation: {agg_desc}")
    
    title_with_subtitle = main_title
    
    fig.update_layout(
        title=title_with_subtitle,
        height=500,
        hovermode='x unified',
        showlegend=True,
        legend=dict(
            itemclick="toggle",
            itemdoubleclick="toggleothers",
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="rgba(0,0,0,0.2)",
            borderwidth=1
        ),
        xaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            mirror=False,
            ticks='outside'
        ),
        margin=dict(r=200),  # Right margin for legend with node counts
        annotations=[
            dict(
                text=' | '.join(metadata_parts),
                showarrow=False,
                xref="paper", yref="paper",
                x=0, y=-0.1,
                xanchor='left', yanchor='top',
                font=dict(size=10, color="gray")
            )
        ] if metadata_parts else None
    )
    
    # Update y-axis styling for both primary and secondary axes
    fig.update_yaxes(
        showline=True,
        linewidth=1,
        linecolor='black',
        mirror=False,
        ticks='outside',
        rangemode='tozero',
        secondary_y=False
    )
    fig.update_yaxes(
        showline=True,
        linewidth=1,
        linecolor='black',
        mirror=False,
        ticks='outside',
        rangemode='tozero',
        secondary_y=True
    )
    
    return add_ethPandaOps_logo(fig)


def create_multi_y_correlation_plot(
    data: pd.DataFrame,
    x_metric: str,
    y_metrics: List[str],
    title_suffix: str = "",
    agg_function: str = "mean",
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    start_y_from_zero: bool = True,
    show_attestation_deadline: bool = True,
    extrapolate_to_deadline: bool = False,
    show_reference_line: bool = False
) -> go.Figure:
    """
    Create scatter plot with multiple y-axis metrics against one x-metric.
    
    Args:
        data: DataFrame with gas and performance data
        x_metric: Column name for x-axis (gas metric)
        y_metrics: List of column names for y-axis (performance metrics)
        title_suffix: Additional text for plot title
        agg_function: Aggregation function used
        network: Network name
        time_range: Time range string
        metadata: Additional metadata
        start_y_from_zero: Whether to force Y-axis to start from 0
        show_attestation_deadline: Whether to show 4s attestation deadline reference line
        
    Returns:
        Plotly figure object with multiple y-metrics
    """
    if data.empty:
        logger.warning("Cannot create multi-y correlation plot: empty data")
        return go.Figure()
    
    x_info = get_metric_info(x_metric)
    
    # Create concise main title
    agg_suffix = f" ({agg_function.title()})" if agg_function and agg_function != "mean" else ""
    main_title = f'{x_info["title"]} vs Performance Metrics{agg_suffix}{title_suffix}'
    
    # Create subtitle with network, time range, block count, and unique nodes
    subtitle_parts = []
    if network:
        subtitle_parts.append(f"Network: {network.title()}")
    if time_range:
        subtitle_parts.append(f"Period: {time_range}")
    if metadata and 'total_blocks' in metadata:
        block_info = f"{metadata['total_blocks']:,} blocks"
        if 'unique_nodes' in metadata:
            block_info += f", {metadata['unique_nodes']} nodes"
        subtitle_parts.append(block_info)
    subtitle = ' | '.join(subtitle_parts) if subtitle_parts else ""
    
    # Create figure
    fig = go.Figure()
    
    # Use custom harsh colors that avoid red/orange to prevent conflict with attestation deadline
    colors = [
        '#0066CC',  # Strong blue
        '#006600',  # Dark green
        '#6600CC',  # Purple
        '#000066',  # Navy blue
        '#CC6600',  # Dark orange (if needed)
        '#666666',  # Dark gray
        '#CC0066',  # Magenta
        '#003366'   # Dark teal
    ]
    color_idx = 0
    
    # Track colors used for each trace to match trend lines
    trace_colors = {}
    
    # Create annotations list for trend line intersections
    annotations = []
    
    # Check if we should group by implementation or other categorical variables
    group_by_implementation = ('meta_consensus_implementation' in data.columns and 
                              data['meta_consensus_implementation'].nunique() > 1 and 
                              data['meta_consensus_implementation'].nunique() <= 10)
    
    group_by_continent = ('meta_client_geo_continent_code' in data.columns and 
                         data['meta_client_geo_continent_code'].nunique() > 1 and 
                         data['meta_client_geo_continent_code'].nunique() <= 8)
    
    # Determine grouping strategy
    if group_by_implementation:
        grouping_column = 'meta_consensus_implementation'
        grouping_title = 'Implementation'
    elif group_by_continent:
        grouping_column = 'meta_client_geo_continent_code'
        grouping_title = 'Continent'
    else:
        grouping_column = None
        grouping_title = None
    
    # Plot data grouped by implementation/continent and y-metric
    if grouping_column:
        # Group by implementation/continent first, then by y-metric
        for group_value in sorted(data[grouping_column].unique()):
            group_data = data[data[grouping_column] == group_value]
            
            # Calculate node count for this group if we have original node data
            node_count_info = ""
            if metadata and 'combined_data' in metadata:
                # Try to get node count from original data
                original_data = metadata['combined_data']
                if 'meta_client_name' in original_data.columns and grouping_column in original_data.columns:
                    group_nodes = original_data[original_data[grouping_column] == group_value]['meta_client_name'].nunique()
                    node_count_info = f" ({group_nodes} nodes)"
            
            for y_metric in y_metrics:
                if y_metric in group_data.columns and not group_data[y_metric].isna().all():
                    y_info = get_metric_info(y_metric)
                    current_color = colors[color_idx % len(colors)]
                    
                    # Create combined name for legend with node count
                    trace_name = f"{group_value}{node_count_info} - {y_info['title']}"
                    
                    # Track color for this trace (for matching trend lines)
                    trace_key = f"{group_value}_{y_metric}"
                    trace_colors[trace_key] = current_color
                    
                    # Add scatter plot for this implementation + metric combination
                    fig.add_trace(
                        go.Scatter(
                            x=group_data[x_metric],
                            y=group_data[y_metric],
                            mode='markers',
                            name=trace_name,
                            marker=dict(
                                color=current_color,
                                size=8,
                                opacity=0.8
                            ),
                            hovertemplate=f'{grouping_title}: {group_value}<br>' +
                                         f'{x_info["title"]}: %{{x:.2f}} {x_info["unit"]}<br>' +
                                         f'{y_info["title"]}: %{{y:.2f}} {y_info["unit"]}<extra></extra>',
                            showlegend=True
                        )
                    )
                    color_idx += 1
    else:
        # Fallback to original behavior - plot each y-metric as a separate trace
        for y_metric in y_metrics:
            if y_metric in data.columns:
                y_info = get_metric_info(y_metric)
                current_color = colors[color_idx % len(colors)]
                
                # Track color for this metric
                trace_colors[y_metric] = current_color
                
                # Add scatter plot
                fig.add_trace(
                    go.Scatter(
                        x=data[x_metric],
                        y=data[y_metric],
                        mode='markers',
                        name=y_info["title"],
                        marker=dict(
                            color=current_color,
                            size=6,
                            opacity=0.7
                        ),
                        hovertemplate=f'{x_info["title"]}: %{{x:.2f}} {x_info["unit"]}<br>' +
                                     f'{y_info["title"]}: %{{y:.2f}} {y_info["unit"]}<extra></extra>',
                        showlegend=True
                    )
                )
                color_idx += 1
            
    # Add trend lines after all scatter plots
    if len(data) > 10:
        if grouping_column:
            # For grouped data, add trend lines for each group + metric combination
            for group_value in sorted(data[grouping_column].unique()):
                group_data = data[data[grouping_column] == group_value]
                if len(group_data) > 5:  # Need minimum points for trend
                    for y_metric in y_metrics:
                        if y_metric in group_data.columns and not group_data[y_metric].isna().all():
                            try:
                                correlation_data = calculate_correlation_analysis(group_data, x_metric, y_metric)
                                if correlation_data and 'slope' in correlation_data and 'intercept' in correlation_data:
                                    x_min = group_data[x_metric].min()
                                    x_max = group_data[x_metric].max()
                                    
                                    # Calculate intersection with 4s deadline if extrapolation is enabled
                                    deadline_intersection = None
                                    if extrapolate_to_deadline and 'ms' in get_metric_info(y_metric).get("unit", ""):
                                        # Only extrapolate for timing metrics (ms unit)
                                        # Solve: 4000 = slope * x + intercept -> x = (4000 - intercept) / slope
                                        if correlation_data['slope'] != 0:
                                            x_at_4s = (4000 - correlation_data['intercept']) / correlation_data['slope']
                                            if x_at_4s > 0:  # Only show positive gas values
                                                deadline_intersection = x_at_4s
                                                x_max = max(x_max, x_at_4s)
                                    
                                    x_range = np.linspace(x_min, x_max, 100)
                                    y_trend = correlation_data['slope'] * x_range + correlation_data['intercept']
                                    
                                    y_info = get_metric_info(y_metric)
                                    # Use the same color as the corresponding data trace
                                    trace_key = f"{group_value}_{y_metric}"
                                    trend_color = trace_colors.get(trace_key, colors[0])
                                    
                                    # Always add trend line with same color as data
                                    fig.add_trace(
                                        go.Scatter(
                                            x=x_range,
                                            y=y_trend,
                                            mode='lines',
                                            name=f'{group_value} - {y_info["title"]} Trend',
                                            line=dict(
                                                color=trend_color,
                                                width=1.5,
                                                dash='dash'
                                            ),
                                            opacity=0.7,
                                            showlegend=False,  # Don't clutter legend with trend lines
                                            hovertemplate=f'Trend: {group_value} - {y_info["title"]}<br>' +
                                                         f'R² = {correlation_data.get("r_squared", 0):.3f}<extra></extra>'
                                        )
                                    )
                                    
                                    # Add annotation for 4s intersection if available
                                    if deadline_intersection:
                                        # Round to nearest million for cleaner display
                                        gas_millions = round(deadline_intersection / 1_000_000)
                                        annotations.append(dict(
                                            x=deadline_intersection,
                                            y=4000,
                                            text=f"{group_value}<br>{gas_millions}M gas",
                                            showarrow=True,
                                            arrowhead=2,
                                            arrowsize=1,
                                            arrowwidth=2,
                                            arrowcolor=trend_color,
                                            bgcolor="rgba(255,255,255,0.8)",
                                            bordercolor=trend_color,
                                            borderwidth=1,
                                            borderpad=6,
                                            font=dict(size=12, color=trend_color)
                                        ))
                            except Exception as e:
                                logger.warning(f"Could not calculate trend line for {group_value} - {y_metric}: {e}")
        else:
            # For non-grouped data, add trend lines for each metric
            for y_metric in y_metrics:
                if y_metric in data.columns:
                    try:
                        correlation_data = calculate_correlation_analysis(data, x_metric, y_metric)
                        if correlation_data and 'slope' in correlation_data and 'intercept' in correlation_data:
                            x_min = data[x_metric].min()
                            x_max = data[x_metric].max()
                            
                            # Calculate intersection with 4s deadline if extrapolation is enabled
                            deadline_intersection = None
                            if extrapolate_to_deadline and 'ms' in get_metric_info(y_metric).get("unit", ""):
                                # Only extrapolate for timing metrics (ms unit)
                                # Solve: 4000 = slope * x + intercept -> x = (4000 - intercept) / slope
                                if correlation_data['slope'] != 0:
                                    x_at_4s = (4000 - correlation_data['intercept']) / correlation_data['slope']
                                    if x_at_4s > 0:  # Only show positive gas values
                                        deadline_intersection = x_at_4s
                                        x_max = max(x_max, x_at_4s)
                            
                            x_range = np.linspace(x_min, x_max, 100)
                            y_trend = correlation_data['slope'] * x_range + correlation_data['intercept']
                            
                            y_info = get_metric_info(y_metric)
                            # Use the same color as the corresponding data trace
                            trend_color = trace_colors.get(y_metric, colors[0])
                            
                            # Always add trend line with same color as data
                            fig.add_trace(
                                go.Scatter(
                                    x=x_range,
                                    y=y_trend,
                                    mode='lines',
                                    name=f'{y_info["title"]} Trend',
                                    line=dict(
                                        color=trend_color,
                                        width=2,
                                        dash='dash'
                                    ),
                                    opacity=0.8,
                                    showlegend=True,  # Show trend lines in legend for non-grouped
                                    hovertemplate=f'Trend: {y_info["title"]}<br>' +
                                                 f'R² = {correlation_data.get("r_squared", 0):.3f}<extra></extra>'
                                )
                            )
                            
                            # Add annotation for 4s intersection if available
                            if deadline_intersection:
                                # Round to nearest million for cleaner display
                                gas_millions = round(deadline_intersection / 1_000_000)
                                annotations.append(dict(
                                    x=deadline_intersection,
                                    y=4000,
                                    text=f"{y_info['title']}<br>{gas_millions}M gas",
                                    showarrow=True,
                                    arrowhead=2,
                                    arrowsize=1,
                                    arrowwidth=2,
                                    arrowcolor=trend_color,
                                    bgcolor="rgba(255,255,255,0.8)",
                                    bordercolor=trend_color,
                                    borderwidth=1,
                                    borderpad=6,
                                    font=dict(size=12, color=trend_color)
                                ))
                    except Exception as e:
                        logger.warning(f"Could not calculate trend line for {y_metric}: {e}")
    
    # Add 1:1 reference lines if requested and we have gas vs time metrics
    if show_reference_line and 'gas' in x_metric.lower():
        for y_metric in y_metrics:
            if y_metric in data.columns and 'time' in y_metric.lower():
                try:
                    # Calculate scale factor for this specific metric pair
                    x_data = data[x_metric].dropna()
                    y_data = data[y_metric].dropna()
                    
                    if len(x_data) > 0 and len(y_data) > 0:
                        x_mean = x_data.mean()
                        y_mean = y_data.mean()
                        scale_factor = y_mean / x_mean if x_mean > 0 else 1
                        
                        x_min, x_max = x_data.min(), x_data.max()
                        x_ref = np.array([x_min, x_max])
                        y_ref = x_ref * scale_factor
                        
                        y_info = get_metric_info(y_metric)
                        ref_color = 'black'
                        
                        fig.add_trace(
                            go.Scatter(
                                x=x_ref,
                                y=y_ref,
                                mode='lines',
                                name='1:1 Linear Reference',
                                line=dict(
                                    color=ref_color,
                                    width=2,
                                    dash='dot'
                                ),
                                opacity=0.6,
                                showlegend=True,
                                hovertemplate=f'1:1 Linear Reference<br>' +
                                             f'Scale: 1 gas = {scale_factor:.2e} {y_info["unit"]}<extra></extra>'
                            )
                        )
                except Exception as e:
                    logger.warning(f"Could not add 1:1 reference line for {y_metric}: {e}")
    
    # Add subtitle annotation
    if subtitle:
        annotations.append(dict(
            text=subtitle,
            showarrow=False,
            xref="paper", yref="paper",
            x=0.5, y=1.02,
            xanchor='center', yanchor='bottom',
            font=dict(size=12, color="gray")
        ))
    
    
    
    # Determine y-axis title based on metric units
    y_metric_units = []
    for y_metric in y_metrics:
        if y_metric in data.columns:
            y_info = get_metric_info(y_metric)
            y_metric_units.append(y_info.get("unit", ""))
    
    # Check if all units are the same and not empty
    unique_units = list(set(y_metric_units))
    if len(unique_units) == 1 and unique_units[0]:
        # All metrics have the same unit
        y_axis_title = f"Performance Metrics ({unique_units[0]})"
    elif len(unique_units) > 1:
        # Mixed units
        y_axis_title = "Performance Metrics (mixed units)"
    else:
        # No units or empty units
        y_axis_title = "Performance Metrics"
    
    # Add ethPandaOps logo using add_layout_image (will be added after layout update)
    # Position logo at top left next to title
    logo_config = dict(
        source="https://ethpandaops.io/img/logo-slim.png",
        xref="paper", yref="paper",
        x=0.02, y=0.98,  # Top left position
        sizex=0.08, sizey=0.08,  # Small logo
        xanchor="left", yanchor="top"
    )
    
    # Update layout
    fig.update_layout(
        title=main_title,
        height=600,
        showlegend=True,
        hovermode='closest',
        legend=dict(
            itemclick="toggle",
            itemdoubleclick="toggleothers",
            orientation="v",
            yanchor="top",
            y=0.95,
            xanchor="left",
            x=1.02,  # Position legend to the right of the chart
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="rgba(0,0,0,0.3)",
            borderwidth=1
        ),
        xaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            mirror=False,
            ticks='outside',
            title=f'{x_info["title"]} ({x_info["unit"]})'
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            mirror=False,
            ticks='outside',
            title=y_axis_title,
            rangemode='tozero' if start_y_from_zero else 'normal'
        ),
        margin=dict(r=200, t=120, l=80),  # Right margin for legend, left margin for logo
        annotations=annotations if annotations else None
    )
    
    # Add 4s attestation deadline reference line if requested and we have timing metrics
    if show_attestation_deadline:
        # Check if any y-metrics are timing-related (have "ms" unit)
        has_timing_metrics = any("ms" in get_metric_info(y_metric).get("unit", "") 
                                for y_metric in y_metrics if y_metric in data.columns)
        
        if has_timing_metrics:
            fig.add_hline(
                y=4000,  # 4 seconds in milliseconds
                line_dash="dot",
                line_color="red",
                line_width=2,
                opacity=0.7,
                annotation_text="4s Attestation Deadline",
                annotation_position="top left",
                annotation_font_size=10,
                annotation_font_color="red"
            )
            
            # Set minimum y-axis max to 5000ms to provide buffer above 4s deadline
            # But allow chart to extend beyond if data requires it
            y_data_max = 0
            for y_metric in y_metrics:
                if y_metric in data.columns:
                    y_max = data[y_metric].max()
                    if pd.notna(y_max):
                        y_data_max = max(y_data_max, y_max)
            
            # Set y-axis range with minimum top of 5000ms for buffer
            y_axis_max = max(5000, y_data_max * 1.05)  # 5% padding above data max
            
            fig.update_yaxes(range=[0 if start_y_from_zero else None, y_axis_max])
    
    # Add ethPandaOps logo using add_layout_image
    fig.add_layout_image(logo_config)
    
    return fig


def create_consensus_performance_heatmap(
    data: pd.DataFrame,
    metric: str = 'block_gossip_time_mean',
    title_suffix: str = ""
) -> go.Figure:
    """
    Create heatmap showing consensus implementation performance over time.
    
    Args:
        data: DataFrame with time buckets and consensus data
        metric: Performance metric to visualize
        title_suffix: Additional text for plot title
        
    Returns:
        Plotly heatmap figure
    """
    if data.empty or 'time_bucket' not in data.columns:
        logger.warning("Cannot create heatmap: missing required data")
        return go.Figure()
    
    metric_info = get_metric_info(metric)
    
    # Expand consensus implementations
    expanded_rows = []
    for _, row in data.iterrows():
        if pd.notna(row.get('consensus_implementations', '')):
            implementations = str(row['consensus_implementations']).split(',')
            for impl in implementations:
                impl = impl.strip()
                if impl and metric in row and pd.notna(row[metric]):
                    new_row = {
                        'time_bucket': row['time_bucket'],
                        'consensus_implementation': impl,
                        metric: row[metric]
                    }
                    if 'bucket_number' in row:
                        new_row['bucket_number'] = row['bucket_number']
                    expanded_rows.append(new_row)
    
    if not expanded_rows:
        logger.warning("No consensus implementation data for heatmap")
        return go.Figure()
    
    expanded_df = pd.DataFrame(expanded_rows)
    
    # Create pivot table for heatmap
    heatmap_data = expanded_df.pivot_table(
        index='consensus_implementation',
        columns='time_bucket',
        values=metric,
        aggfunc='mean'
    )
    
    if heatmap_data.empty:
        logger.warning("No data for heatmap after pivot")
        return go.Figure()
    
    # Create heatmap
    fig = go.Figure(data=go.Heatmap(
        z=heatmap_data.values,
        x=heatmap_data.columns,
        y=heatmap_data.index,
        colorscale='RdYlBu_r',  # Red for higher values (worse performance)
        hovertemplate='Implementation: %{y}<br>Time Bucket: %{x}<br>' + 
                     f'{metric_info["title"]}: %{{z:.2f}} {metric_info["unit"]}<extra></extra>',
        colorbar=dict(title=f'{metric_info["title"]} ({metric_info["unit"]})')
    ))
    
    fig.update_layout(
        title=f'{metric_info["title"]} by Consensus Implementation Over Time{title_suffix}',
        xaxis_title='Time Bucket',
        yaxis_title='Consensus Implementation',
        height=500
    )
    
    return add_ethPandaOps_logo(fig)


def create_box_plot_comparison(
    data: pd.DataFrame,
    metric: str,
    group_by: str = 'consensus_implementations',
    title_suffix: str = ""
) -> go.Figure:
    """
    Create box plot comparing metric distributions across groups.
    
    Args:
        data: DataFrame with metrics and grouping column
        metric: Metric to compare
        group_by: Column to group by
        title_suffix: Additional text for plot title
        
    Returns:
        Plotly box plot figure
    """
    if data.empty or metric not in data.columns:
        logger.warning(f"Cannot create box plot: missing metric {metric}")
        return go.Figure()
    
    metric_info = get_metric_info(metric)
    
    # Expand grouped data if needed (for consensus implementations)
    if group_by == 'consensus_implementations' and group_by in data.columns:
        expanded_rows = []
        for _, row in data.iterrows():
            if pd.notna(row[group_by]):
                implementations = str(row[group_by]).split(',')
                for impl in implementations:
                    impl = impl.strip()
                    if impl and pd.notna(row[metric]):
                        expanded_rows.append({
                            'consensus_implementation': impl,
                            metric: row[metric]
                        })
        
        if expanded_rows:
            plot_data = pd.DataFrame(expanded_rows)
            group_col = 'consensus_implementation'
        else:
            logger.warning("No valid consensus implementation data for box plot")
            return go.Figure()
    else:
        plot_data = data[[group_by, metric]].dropna()
        group_col = group_by
    
    # Create box plot
    fig = px.box(
        plot_data,
        x=group_col,
        y=metric,
        title=f'{metric_info["title"]} Distribution by {group_col.replace("_", " ").title()}{title_suffix}',
        labels={
            metric: f'{metric_info["title"]} ({metric_info["unit"]})',
            group_col: group_col.replace('_', ' ').title()
        }
    )
    
    # Add mean markers
    means = plot_data.groupby(group_col)[metric].mean()
    for i, (_, mean_val) in enumerate(means.items()):
        fig.add_shape(
            type="line",
            x0=i-0.4, x1=i+0.4,
            y0=mean_val, y1=mean_val,
            line=dict(color="red", width=2, dash="dash")
        )
    
    fig.update_layout(
        height=500,
        xaxis_tickangle=-45
    )
    
    return add_ethPandaOps_logo(fig)


def create_correlation_matrix(
    data: pd.DataFrame,
    metrics: List[str],
    title_suffix: str = ""
) -> go.Figure:
    """
    Create correlation matrix heatmap for multiple metrics.
    
    Args:
        data: DataFrame with metrics
        metrics: List of metrics to include in correlation matrix
        title_suffix: Additional text for plot title
        
    Returns:
        Plotly heatmap figure showing correlations
    """
    if data.empty:
        logger.warning("Cannot create correlation matrix: empty data")
        return go.Figure()
    
    # Filter to available metrics
    available_metrics = [m for m in metrics if m in data.columns]
    if len(available_metrics) < 2:
        logger.warning("Need at least 2 metrics for correlation matrix")
        return go.Figure()
    
    # Calculate correlation matrix
    corr_matrix = data[available_metrics].corr()
    
    # Get metric info for labels
    metric_labels = [get_metric_info(m)["title"] for m in available_metrics]
    
    # Create heatmap
    fig = go.Figure(data=go.Heatmap(
        z=corr_matrix.values,
        x=metric_labels,
        y=metric_labels,
        colorscale='RdBu',
        zmid=0,
        zmin=-1,
        zmax=1,
        hovertemplate='%{y} vs %{x}<br>Correlation: %{z:.3f}<extra></extra>',
        colorbar=dict(title='Correlation Coefficient')
    ))
    
    # Add correlation values as text
    annotations = []
    for i, row in enumerate(corr_matrix.values):
        for j, val in enumerate(row):
            annotations.append(
                dict(
                    x=j, y=i,
                    text=f'{val:.3f}',
                    showarrow=False,
                    font=dict(color='white' if abs(val) > 0.5 else 'black')
                )
            )
    
    fig.update_layout(
        title=f'Correlation Matrix{title_suffix}',
        annotations=annotations,
        height=500,
        width=500,
        xaxis_tickangle=-45
    )
    
    return add_ethPandaOps_logo(fig)


def create_gas_vs_head_time_plot(
    relationship_data: Dict[str, Any],
    show_binned: bool = True,
    title_suffix: str = "",
    network: str = None,
    time_range: str = None
) -> go.Figure:
    """
    Create visualization for gas usage vs head time relationship analysis.
    
    Args:
        relationship_data: Output from calculate_gas_vs_head_time_relationship
        show_binned: Whether to show binned analysis overlay
        title_suffix: Additional text for plot title
        network: Network name for metadata
        time_range: Time range for metadata
        
    Returns:
        Plotly figure showing the relationship
    """
    if not relationship_data or 'visualization_data' not in relationship_data:
        logger.warning("Cannot create gas vs head time plot: no data")
        return go.Figure()
    
    viz_data = relationship_data['visualization_data']
    scatter_df = pd.DataFrame(viz_data['scatter_data'])
    
    # Create figure
    fig = go.Figure()
    
    # Add scatter plot of raw data
    fig.add_trace(go.Scatter(
        x=scatter_df[viz_data['x_column']],
        y=scatter_df[viz_data['y_column']],
        mode='markers',
        name='Data Points',
        marker=dict(
            size=6,
            color='lightblue',
            opacity=0.6,
            line=dict(width=1, color='darkblue')
        ),
        hovertemplate='Gas: %{x:,.0f}<br>Head Time: %{y:.2f} ms<extra></extra>'
    ))
    
    # Add trend line if available
    if 'trend_line' in viz_data:
        trend = viz_data['trend_line']
        fig.add_trace(go.Scatter(
            x=trend['x'],
            y=trend['y'],
            mode='lines',
            name='Linear Fit',
            line=dict(color='red', width=3, dash='solid'),
            hovertemplate=f"{trend['equation']}<br>R² = {trend['r_squared']:.3f}<extra></extra>"
        ))
    
    # Add binned analysis if available and requested
    if show_binned and 'binned_analysis' in relationship_data:
        bin_data = pd.DataFrame(relationship_data['binned_analysis']['bin_data'])
        if not bin_data.empty:
            # Add binned averages
            fig.add_trace(go.Scatter(
                x=bin_data['gas_bin_midpoint'],
                y=bin_data[f"{viz_data['y_column']}_mean"],
                mode='lines+markers',
                name='Binned Average',
                line=dict(color='darkgreen', width=2),
                marker=dict(size=10, symbol='diamond'),
                error_y=dict(
                    type='data',
                    array=bin_data[f"{viz_data['y_column']}_std"],
                    visible=True,
                    color='green'
                ),
                hovertemplate='Gas Bin: %{x:,.0f}<br>Avg Head Time: %{y:.2f} ms<br>±%{error_y.array:.2f}<extra></extra>'
            ))
    
    # Create title with relationship description
    main_title = viz_data.get('title', 'Gas Usage vs Head Time Relationship')
    if 'relationship_description' in relationship_data:
        main_title += f" - {relationship_data['relationship_description']}"
    main_title += title_suffix
    
    # Create metadata annotation
    metadata_parts = []
    if network:
        metadata_parts.append(f"Network: {network.title()}")
    if time_range:
        metadata_parts.append(f"Period: {time_range}")
    
    # Add statistical information
    if 'correlation_analysis' in relationship_data:
        corr = relationship_data['correlation_analysis']
        metadata_parts.append(f"Correlation: {corr['correlation']:.3f} (p={corr['p_value']:.4f})")
        metadata_parts.append(f"R²: {corr['r_squared']:.3f}")
    
    metadata_parts.append(f"Samples: {relationship_data['sample_size']:,}")
    
    # Add linearity assessment
    if 'is_linear' in relationship_data:
        linearity_text = "Linear" if relationship_data['is_linear'] else "Non-linear"
        confidence = relationship_data.get('linearity_confidence', 0)
        metadata_parts.append(f"Relationship: {linearity_text} (confidence: {confidence:.1%})")
    
    # Update layout
    fig.update_layout(
        title=main_title,
        xaxis_title=viz_data.get('x_label', 'Gas Used'),
        yaxis_title=viz_data.get('y_label', 'Head Time (ms)'),
        height=600,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02
        ),
        xaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            mirror=False,
            ticks='outside',
            rangemode='tozero'
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            mirror=False,
            ticks='outside',
            rangemode='tozero'
        ),
        annotations=[
            dict(
                text=' | '.join(metadata_parts),
                showarrow=False,
                xref="paper", yref="paper",
                x=0, y=-0.12,
                xanchor='left', yanchor='top',
                font=dict(size=10, color="gray")
            )
        ]
    )
    
    return add_ethPandaOps_logo(fig)


def create_geographic_performance_plot(
    data: pd.DataFrame,
    metric: str = 'block_gossip_time_mean',
    title_suffix: str = ""
) -> go.Figure:
    """
    Create geographic performance analysis plot.
    
    Args:
        data: DataFrame with continental data
        metric: Performance metric to analyze
        title_suffix: Additional text for plot title
        
    Returns:
        Plotly bar chart showing performance by continent
    """
    if data.empty or 'continents' not in data.columns:
        logger.warning("Cannot create geographic plot: missing continental data")
        return go.Figure()
    
    metric_info = get_metric_info(metric)
    continent_names = get_continents()
    
    # Expand continental data
    expanded_rows = []
    for _, row in data.iterrows():
        if pd.notna(row['continents']):
            continents = str(row['continents']).split(',')
            for cont in continents:
                cont = cont.strip()
                if cont and metric in row and pd.notna(row[metric]):
                    expanded_rows.append({
                        'continent_code': cont,
                        'continent_name': continent_names.get(cont, cont),
                        metric: row[metric]
                    })
    
    if not expanded_rows:
        logger.warning("No continental data for geographic plot")
        return go.Figure()
    
    expanded_df = pd.DataFrame(expanded_rows)
    
    # Calculate metrics by continent
    continent_metrics = expanded_df.groupby(['continent_code', 'continent_name'])[metric].agg([
        'mean', 'median', 'std', 'count'
    ]).reset_index()
    
    # Create bar chart
    fig = px.bar(
        continent_metrics,
        x='continent_name',
        y='mean',
        error_y='std',
        title=f'{metric_info["title"]} by Continent{title_suffix}',
        labels={
            'mean': f'Mean {metric_info["title"]} ({metric_info["unit"]})',
            'continent_name': 'Continent'
        },
        hover_data=['median', 'count']
    )
    
    fig.update_layout(
        height=500,
        xaxis_tickangle=-45
    )
    
    return add_ethPandaOps_logo(fig)


def create_gas_binned_performance_plot(
    binned_data: pd.DataFrame,
    performance_metric: str = 'block_gossip_time_mean_mean',
    title_suffix: str = ""
) -> go.Figure:
    """
    Create plot showing performance across gas usage bins.
    
    Args:
        binned_data: DataFrame with gas bin analysis results
        performance_metric: Performance metric column name
        title_suffix: Additional text for plot title
        
    Returns:
        Plotly line plot with error bars
    """
    if binned_data.empty or performance_metric not in binned_data.columns:
        logger.warning("Cannot create gas binned plot: missing data")
        return go.Figure()
    
    metric_info = get_metric_info(performance_metric.replace('_mean', ''))
    
    # Use gas bin midpoints for x-axis
    x_values = binned_data['gas_bin_midpoint'] if 'gas_bin_midpoint' in binned_data.columns else range(len(binned_data))
    
    # Get error bars if available
    error_y = None
    std_col = performance_metric.replace('_mean', '_std')
    if std_col in binned_data.columns:
        error_y = binned_data[std_col]
    
    fig = go.Figure()
    
    # Add main line
    fig.add_trace(go.Scatter(
        x=x_values,
        y=binned_data[performance_metric],
        mode='lines+markers',
        name=f'Mean {metric_info["title"]}',
        error_y=dict(type='data', array=error_y, visible=True) if error_y is not None else None,
        hovertemplate=f'Gas Bin: %{{x:.0f}}<br>{metric_info["title"]}: %{{y:.2f}} {metric_info["unit"]}<extra></extra>'
    ))
    
    # Add trend line if enough points
    if len(binned_data) > 3:
        try:
            corr_data = calculate_correlation_analysis(
                binned_data, 
                'gas_bin_midpoint' if 'gas_bin_midpoint' in binned_data.columns else binned_data.columns[0],
                performance_metric
            )
        except ImportError:
            corr_data = None
        
        if corr_data:
            x_trend = np.linspace(x_values.min(), x_values.max(), 100)
            y_trend = corr_data['slope'] * x_trend + corr_data['intercept']
            
            fig.add_trace(go.Scatter(
                x=x_trend,
                y=y_trend,
                mode='lines',
                name=f'Trend (R²: {corr_data["r_squared"]:.3f})',
                line=dict(dash='dash', color='red')
            ))
    
    fig.update_layout(
        title=f'{metric_info["title"]} vs Gas Usage{title_suffix}',
        xaxis_title='Gas Used (Gas Bin Midpoint)',
        yaxis_title=f'{metric_info["title"]} ({metric_info["unit"]})',
        height=500
    )
    
    return add_ethPandaOps_logo(fig)