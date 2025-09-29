"""
Plot generators for Blob Propagation Analysis.

This module provides functions to create various visualizations for blob propagation
analysis, including heatmaps, timelines, and coverage charts.
"""

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.figure_factory as ff
from typing import Dict, Any, Optional, List, Tuple
import logging

logger = logging.getLogger(__name__)


def create_blob_propagation_heatmap(
    data: pd.DataFrame,
    title: str = "Blob Propagation Heatmap",
    color_metric: str = "unique_blobs_seen",
    height: int = 600
) -> go.Figure:
    """
    Create a heatmap showing blob propagation patterns between proposer and attester groups.
    
    Args:
        data: DataFrame with blob propagation data
        title: Chart title
        color_metric: Metric to use for color intensity
        height: Chart height
    
    Returns:
        Plotly figure
    """
    
    if data.empty:
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    # Pivot data for heatmap
    heatmap_data = data.pivot_table(
        index='proposer_group',
        columns='attester_group',
        values=color_metric,
        fill_value=0
    )
    
    fig = go.Figure(data=go.Heatmap(
        z=heatmap_data.values,
        x=heatmap_data.columns,
        y=heatmap_data.index,
        colorscale='Viridis',
        hoverongaps=False,
        text=np.round(heatmap_data.values, 2),
        texttemplate="%{text}",
        textfont={"size": 10},
        hovertemplate='<b>Proposer:</b> %{y}<br>' +
                     '<b>Attester:</b> %{x}<br>' +
                     f'<b>{color_metric.replace("_", " ").title()}:</b> %{{z}}<br>' +
                     '<extra></extra>'
    ))
    
    fig.update_layout(
        title=title,
        xaxis_title="Attester Group",
        yaxis_title="Proposer Group",
        height=height,
        font=dict(size=12)
    )
    
    return fig


def create_blob_propagation_timeline(
    data: pd.DataFrame,
    title: str = "Blob Propagation Timeline",
    proposer_group: Optional[str] = None,
    attester_group: Optional[str] = None,
    height: int = 500
) -> go.Figure:
    """
    Create a timeline showing blob propagation over time.
    
    Args:
        data: DataFrame with timeline data
        title: Chart title
        proposer_group: Specific proposer group to highlight
        attester_group: Specific attester group to highlight
        height: Chart height
    
    Returns:
        Plotly figure
    """
    
    if data.empty:
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    # Filter data if specific groups are specified
    filtered_data = data.copy()
    if proposer_group:
        filtered_data = filtered_data[filtered_data['proposer_group'] == proposer_group]
    if attester_group:
        filtered_data = filtered_data[filtered_data['attester_group'] == attester_group]
    
    # Create timeline chart
    fig = go.Figure()
    
    # Group by proposer/attester combination
    for (prop_group, att_group), group_data in filtered_data.groupby(['proposer_group', 'attester_group']):
        fig.add_trace(go.Scatter(
            x=group_data['time_bucket_ms'],
            y=group_data['unique_blobs_seen'],
            mode='lines+markers',
            name=f"{prop_group} → {att_group}",
            line=dict(width=2),
            marker=dict(size=6),
            hovertemplate='<b>Time:</b> %{x}ms<br>' +
                         '<b>Blobs Seen:</b> %{y}<br>' +
                         '<b>Proposer:</b> ' + prop_group + '<br>' +
                         '<b>Attester:</b> ' + att_group + '<br>' +
                         '<extra></extra>'
        ))
    
    fig.update_layout(
        title=title,
        xaxis_title="Time (milliseconds)",
        yaxis_title="Unique Blobs Seen",
        height=height,
        hovermode='x unified',
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.01
        )
    )
    
    return fig


def create_blob_propagation_coverage_chart(
    data: pd.DataFrame,
    title: str = "Blob Propagation Coverage",
    metric: str = "avg_attester_clients_per_slot",
    height: int = 500
) -> go.Figure:
    """
    Create a chart showing blob propagation coverage by proposer group.
    
    Args:
        data: DataFrame with coverage data
        title: Chart title
        metric: Metric to display
        height: Chart height
    
    Returns:
        Plotly figure
    """
    
    if data.empty:
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    fig = go.Figure(data=[
        go.Bar(
            x=data['proposer_group'],
            y=data[metric],
            text=np.round(data[metric], 2),
            textposition='auto',
            hovertemplate='<b>Proposer Group:</b> %{x}<br>' +
                         f'<b>{metric.replace("_", " ").title()}:</b> %{{y}}<br>' +
                         '<extra></extra>'
        )
    ])
    
    fig.update_layout(
        title=title,
        xaxis_title="Proposer Group",
        yaxis_title=metric.replace("_", " ").title(),
        height=height,
        xaxis={'categoryorder': 'total descending'}
    )
    
    return fig


def create_blob_propagation_scatter(
    data: pd.DataFrame,
    title: str = "Blob Propagation Scatter Plot",
    x_metric: str = "avg_propagation_time_ms",
    y_metric: str = "unique_attester_clients",
    size_metric: str = "total_blob_events",
    height: int = 600
) -> go.Figure:
    """
    Create a scatter plot showing relationships between different blob propagation metrics.
    
    Args:
        data: DataFrame with blob propagation data
        title: Chart title
        x_metric: Metric for x-axis
        y_metric: Metric for y-axis
        size_metric: Metric for marker size
        height: Chart height
    
    Returns:
        Plotly figure
    """
    
    if data.empty:
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    fig = px.scatter(
        data,
        x=x_metric,
        y=y_metric,
        size=size_metric,
        color='proposer_group',
        hover_data=['attester_group', 'total_blob_events'],
        title=title,
        height=height
    )
    
    fig.update_layout(
        xaxis_title=x_metric.replace("_", " ").title(),
        yaxis_title=y_metric.replace("_", " ").title(),
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.01
        )
    )
    
    return fig


def create_blob_propagation_box_plot(
    data: pd.DataFrame,
    title: str = "Blob Propagation Distribution",
    metric: str = "avg_propagation_time_ms",
    group_by: str = "proposer_group",
    height: int = 500
) -> go.Figure:
    """
    Create a box plot showing distribution of blob propagation metrics.
    
    Args:
        data: DataFrame with blob propagation data
        title: Chart title
        metric: Metric to display
        group_by: Column to group by
        height: Chart height
    
    Returns:
        Plotly figure
    """
    
    if data.empty:
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    fig = px.box(
        data,
        x=group_by,
        y=metric,
        title=title,
        height=height,
        color=group_by
    )
    
    fig.update_layout(
        xaxis_title=group_by.replace("_", " ").title(),
        yaxis_title=metric.replace("_", " ").title(),
        showlegend=False
    )
    
    return fig


def create_blob_propagation_network_diagram(
    data: pd.DataFrame,
    title: str = "Blob Propagation Network",
    min_connections: int = 1,
    height: int = 700
) -> go.Figure:
    """
    Create a network diagram showing connections between proposer and attester groups.
    
    Args:
        data: DataFrame with blob propagation data
        title: Chart title
        min_connections: Minimum number of connections to show
        height: Chart height
    
    Returns:
        Plotly figure
    """
    
    if data.empty:
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    # Filter by minimum connections
    filtered_data = data[data['total_blob_events'] >= min_connections]
    
    if filtered_data.empty:
        return go.Figure().add_annotation(
            text=f"No connections found with minimum {min_connections} events",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    # Create nodes and edges
    proposer_nodes = filtered_data['proposer_group'].unique()
    attester_nodes = filtered_data['attester_group'].unique()
    
    # Node positions (simple layout)
    node_positions = {}
    node_x = []
    node_y = []
    node_text = []
    node_colors = []
    
    # Position proposer nodes on the left
    for i, node in enumerate(proposer_nodes):
        node_positions[node] = (0, i)
        node_x.append(0)
        node_y.append(i)
        node_text.append(f"P: {node}")
        node_colors.append('lightblue')
    
    # Position attester nodes on the right
    for i, node in enumerate(attester_nodes):
        node_positions[node] = (2, i)
        node_x.append(2)
        node_y.append(i)
        node_text.append(f"A: {node}")
        node_colors.append('lightcoral')
    
    # Create edges
    edge_x = []
    edge_y = []
    edge_info = []
    
    for _, row in filtered_data.iterrows():
        prop_pos = node_positions[row['proposer_group']]
        att_pos = node_positions[row['attester_group']]
        
        edge_x.extend([prop_pos[0], att_pos[0], None])
        edge_y.extend([prop_pos[1], att_pos[1], None])
        edge_info.append(f"Events: {row['total_blob_events']}")
    
    # Create the figure
    fig = go.Figure()
    
    # Add edges
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y,
        line=dict(width=2, color='gray'),
        hoverinfo='none',
        mode='lines',
        showlegend=False
    ))
    
    # Add nodes
    fig.add_trace(go.Scatter(
        x=node_x, y=node_y,
        mode='markers+text',
        marker=dict(
            size=20,
            color=node_colors,
            line=dict(width=2, color='black')
        ),
        text=node_text,
        textposition="middle center",
        hovertemplate='%{text}<br><extra></extra>',
        showlegend=False
    ))
    
    fig.update_layout(
        title=title,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=height,
        showlegend=False
    )
    
    return fig


def create_blob_propagation_summary_dashboard(
    data: pd.DataFrame,
    title: str = "Blob Propagation Summary Dashboard",
    height: int = 800
) -> go.Figure:
    """
    Create a comprehensive dashboard with multiple blob propagation visualizations.
    
    Args:
        data: DataFrame with blob propagation data
        title: Dashboard title
        height: Dashboard height
    
    Returns:
        Plotly figure with subplots
    """
    
    if data.empty:
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    # Create subplots
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[
            "Propagation Heatmap",
            "Coverage by Proposer Group",
            "Propagation Timeline",
            "Distribution Box Plot"
        ],
        specs=[[{"type": "heatmap"}, {"type": "bar"}],
               [{"type": "scatter"}, {"type": "box"}]]
    )
    
    # Heatmap
    heatmap_data = data.pivot_table(
        index='proposer_group',
        columns='attester_group',
        values='unique_blobs_seen',
        fill_value=0
    )
    
    fig.add_trace(
        go.Heatmap(
            z=heatmap_data.values,
            x=heatmap_data.columns,
            y=heatmap_data.index,
            colorscale='Viridis',
            showscale=False
        ),
        row=1, col=1
    )
    
    # Coverage chart
    coverage_data = data.groupby('proposer_group')['unique_attester_clients'].mean().reset_index()
    fig.add_trace(
        go.Bar(
            x=coverage_data['proposer_group'],
            y=coverage_data['unique_attester_clients'],
            showlegend=False
        ),
        row=1, col=2
    )
    
    # Timeline (simplified - just show average over time)
    timeline_data = data.groupby('slot')['avg_propagation_time_ms'].mean().reset_index()
    fig.add_trace(
        go.Scatter(
            x=timeline_data['slot'],
            y=timeline_data['avg_propagation_time_ms'],
            mode='lines+markers',
            showlegend=False
        ),
        row=2, col=1
    )
    
    # Box plot
    fig.add_trace(
        go.Box(
            x=data['proposer_group'],
            y=data['avg_propagation_time_ms'],
            showlegend=False
        ),
        row=2, col=2
    )
    
    fig.update_layout(
        title=title,
        height=height,
        showlegend=False
    )
    
    return fig


def create_blob_propagation_metrics_table(
    data: pd.DataFrame,
    title: str = "Blob Propagation Metrics"
) -> pd.DataFrame:
    """
    Create a formatted table with key blob propagation metrics.
    
    Args:
        data: DataFrame with blob propagation data
        title: Table title
    
    Returns:
        Formatted DataFrame for display
    """
    
    if data.empty:
        return pd.DataFrame({"Message": ["No data available"]})
    
    # Calculate summary metrics
    summary_metrics = {
        'Total Slots': data['slot'].nunique(),
        'Total Proposer Groups': data['proposer_group'].nunique(),
        'Total Attester Groups': data['attester_group'].nunique(),
        'Total Blob Events': data['total_blob_events'].sum(),
        'Avg Blobs per Slot': data.groupby('slot')['unique_blobs_seen'].sum().mean(),
        'Avg Attester Clients per Slot': data.groupby('slot')['unique_attester_clients'].sum().mean(),
        'Avg Propagation Time (ms)': data['avg_propagation_time_ms'].mean(),
        'Median Propagation Time (ms)': data['avg_propagation_time_ms'].median(),
        'P90 Propagation Time (ms)': data['avg_propagation_time_ms'].quantile(0.9),
        'P95 Propagation Time (ms)': data['avg_propagation_time_ms'].quantile(0.95),
        'P99 Propagation Time (ms)': data['avg_propagation_time_ms'].quantile(0.99)
    }
    
    # Convert to DataFrame
    metrics_df = pd.DataFrame(list(summary_metrics.items()), columns=['Metric', 'Value'])
    
    # Format numeric values
    metrics_df['Value'] = metrics_df['Value'].apply(
        lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x)
    )
    
    return metrics_df
