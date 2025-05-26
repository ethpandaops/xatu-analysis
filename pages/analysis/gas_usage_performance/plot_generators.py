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
from config_utils import get_metric_info, get_analysis_config, get_continents
from metrics_calculators import calculate_correlation_analysis


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_gas_vs_arrival_scatter(
    data: pd.DataFrame,
    x_metric: str = 'gas_used',
    y_metric: str = 'block_gossip_time_mean',
    color_by: str = 'slot_start_date_time',
    size_by: Optional[str] = None,
    title_suffix: str = ""
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
    
    # Create correlation info for title
    corr_text = ""
    if correlation_data:
        corr_text = f"<br><sub>Correlation: {correlation_data['correlation']:.4f}, R²: {correlation_data['r_squared']:.4f}"
        if correlation_data['significant']:
            corr_text += " *"
        corr_text += "</sub>"
    
    title = f'{x_info["title"]} vs {y_info["title"]}{title_suffix}{corr_text}'
    
    # Prepare hover data
    hover_data = ['slot']
    if 'consensus_implementations' in data.columns:
        hover_data.append('consensus_implementations')
    if 'continents' in data.columns:
        hover_data.append('continents')
    
    # Create scatter plot
    fig = px.scatter(
        data,
        x=x_metric,
        y=y_metric,
        color=color_by,
        size=size_by,
        title=title,
        labels={
            x_metric: f'{x_info["title"]} ({x_info["unit"]})',
            y_metric: f'{y_info["title"]} ({y_info["unit"]})',
            color_by: color_by.replace('_', ' ').title()
        },
        hover_data=hover_data,
        color_continuous_scale='viridis'
    )
    
    # Add trend line if correlation data available
    if correlation_data and len(data) > 10:
        x_range = np.linspace(data[x_metric].min(), data[x_metric].max(), 100)
        y_trend = correlation_data['slope'] * x_range + correlation_data['intercept']
        
        fig.add_trace(go.Scatter(
            x=x_range,
            y=y_trend,
            mode='lines',
            name=f'Trend Line (slope: {correlation_data["slope"]:.2e})',
            line=dict(dash='dash', color='red', width=2),
            hovertemplate='Trend Line<br>Slope: %{customdata:.2e}<extra></extra>',
            customdata=[correlation_data["slope"]] * len(x_range)
        ))
    
    # Update layout
    fig.update_layout(
        height=600,
        showlegend=True,
        title={'font': {'size': 16}},
        xaxis_title_font_size=14,
        yaxis_title_font_size=14,
        hovermode='closest'
    )
    
    return add_ethPandaOps_logo(fig)


def create_time_series_comparison(
    time_metrics: pd.DataFrame,
    metrics_to_plot: List[str],
    title_suffix: str = ""
) -> go.Figure:
    """
    Create multi-axis time series plot for temporal analysis.
    
    Args:
        time_metrics: DataFrame with time bucket metrics
        metrics_to_plot: List of metric columns to plot
        title_suffix: Additional text for plot title
        
    Returns:
        Plotly figure with dual y-axes
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
    
    # Plot gas metrics on primary y-axis
    for metric in gas_metrics:
        if metric in time_metrics.columns:
            metric_info = get_metric_info(metric.replace('_mean', ''))
            fig.add_trace(
                go.Scatter(
                    x=time_metrics.index if hasattr(time_metrics, 'index') else time_metrics['time_bucket'],
                    y=time_metrics[metric],
                    name=f'{metric_info["title"]} (Mean)',
                    line=dict(color=colors[color_idx % len(colors)]),
                    mode='lines+markers',
                    hovertemplate=f'{metric_info["title"]}: %{{y:.2f}} {metric_info["unit"]}<extra></extra>'
                ),
                secondary_y=False
            )
            color_idx += 1
    
    # Plot timing metrics on secondary y-axis
    for metric in timing_metrics:
        if metric in time_metrics.columns:
            metric_info = get_metric_info(metric.replace('_mean', ''))
            fig.add_trace(
                go.Scatter(
                    x=time_metrics.index if hasattr(time_metrics, 'index') else time_metrics['time_bucket'],
                    y=time_metrics[metric],
                    name=f'{metric_info["title"]} (Mean)',
                    line=dict(color=colors[color_idx % len(colors)]),
                    mode='lines+markers',
                    hovertemplate=f'{metric_info["title"]}: %{{y:.2f}} {metric_info["unit"]}<extra></extra>'
                ),
                secondary_y=True
            )
            color_idx += 1
    
    # Update axis labels
    fig.update_yaxes(title_text="Gas Usage", secondary_y=False)
    fig.update_yaxes(title_text="Arrival Time (ms)", secondary_y=True)
    fig.update_xaxes(title_text="Time Bucket")
    
    fig.update_layout(
        title=f"Gas Usage and Arrival Times Over Time{title_suffix}",
        height=500,
        hovermode='x unified'
    )
    
    return add_ethPandaOps_logo(fig)


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
    for i, (group, mean_val) in enumerate(means.items()):
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