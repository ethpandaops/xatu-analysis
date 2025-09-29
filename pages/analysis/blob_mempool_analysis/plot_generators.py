"""
Plot generators for Blob Mempool Analysis.

This module creates various visualizations for blob mempool analysis,
including line charts, bar charts, heatmaps, and summary statistics.
"""

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st
from typing import Dict, Any, Optional, List
import logging

from pages.analysis.blob_mempool_analysis.config_utils import get_default_chart_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_blob_count_timeline(
    df: pd.DataFrame,
    selected_clients: Optional[List[str]] = None,
    chart_config: Optional[Dict[str, Any]] = None
) -> go.Figure:
    """
    Create a timeline chart showing blob counts per slot.
    
    Args:
        df: DataFrame with slot, canonical_blob_count, mempool_blob_count, client_name
        selected_clients: Optional list of clients to highlight
        chart_config: Optional chart configuration
        
    Returns:
        Plotly figure
    """
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available for the selected parameters",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    config = chart_config or get_default_chart_config()
    
    # Group by slot to show aggregate data
    slot_summary = df.groupby(['slot', 'slot_start_date_time']).agg({
        'canonical_blob_count': 'first',  # Same for all clients in a slot
        'mempool_blob_count': 'sum',      # Sum across all clients
        'matching_blob_count': 'sum'      # Sum of matches across clients
    }).reset_index()
    
    fig = go.Figure()
    
    # Add canonical blob count line
    fig.add_trace(go.Scatter(
        x=slot_summary['slot'],
        y=slot_summary['canonical_blob_count'],
        mode='lines+markers',
        name='Canonical Blobs',
        line=dict(color='#1f77b4', width=config.get('line_width', 2)),
        marker=dict(size=config.get('marker_size', 6)),
        hovertemplate='<b>Slot:</b> %{x}<br><b>Canonical Blobs:</b> %{y}<extra></extra>'
    ))
    
    # Add mempool blob count line
    fig.add_trace(go.Scatter(
        x=slot_summary['slot'],
        y=slot_summary['mempool_blob_count'],
        mode='lines+markers',
        name='Mempool Blobs (All Clients)',
        line=dict(color='#ff7f0e', width=config.get('line_width', 2)),
        marker=dict(size=config.get('marker_size', 6)),
        hovertemplate='<b>Slot:</b> %{x}<br><b>Mempool Blobs:</b> %{y}<extra></extra>'
    ))
    
    # Add matching blob count line
    fig.add_trace(go.Scatter(
        x=slot_summary['slot'],
        y=slot_summary['matching_blob_count'],
        mode='lines+markers',
        name='Matching Blobs',
        line=dict(color='#2ca02c', width=config.get('line_width', 2)),
        marker=dict(size=config.get('marker_size', 6)),
        hovertemplate='<b>Slot:</b> %{x}<br><b>Matching Blobs:</b> %{y}<extra></extra>'
    ))
    
    fig.update_layout(
        title="Blob Count Timeline by Slot",
        xaxis_title="Slot",
        yaxis_title="Number of Blobs",
        height=config.get('height', 400),
        showlegend=config.get('show_legend', True),
        hovermode='x unified'
    )
    
    if config.get('show_grid', True):
        fig.update_xaxes(showgrid=True)
        fig.update_yaxes(showgrid=True)
    
    return fig


def create_match_percentage_chart(
    df: pd.DataFrame,
    selected_clients: Optional[List[str]] = None,
    chart_config: Optional[Dict[str, Any]] = None
) -> go.Figure:
    """
    Create a chart showing mempool match percentages.
    
    Args:
        df: DataFrame with match_percentage data
        selected_clients: Optional list of clients to show
        chart_config: Optional chart configuration
        
    Returns:
        Plotly figure
    """
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available for the selected parameters",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    config = chart_config or get_default_chart_config()
    
    # Filter data for slots with blobs
    df_with_blobs = df[df['canonical_blob_count'] > 0].copy()
    
    if df_with_blobs.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No slots with blobs found in the selected time range",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    fig = go.Figure()
    
    # If specific clients selected, show individual lines
    if selected_clients:
        for client in selected_clients:
            client_data = df_with_blobs[df_with_blobs['client_name'] == client]
            if not client_data.empty:
                fig.add_trace(go.Scatter(
                    x=client_data['slot'],
                    y=client_data['match_percentage'],
                    mode='lines+markers',
                    name=f'{client} Match %',
                    line=dict(width=config.get('line_width', 2)),
                    marker=dict(size=config.get('marker_size', 6)),
                    hovertemplate=f'<b>Client:</b> {client}<br><b>Slot:</b> %{{x}}<br><b>Match %:</b> %{{y:.1f}}%<extra></extra>'
                ))
    else:
        # Show average across all clients
        avg_match = df_with_blobs.groupby('slot')['match_percentage'].mean().reset_index()
        avg_match['slot_data'] = df_with_blobs.groupby('slot')['slot'].first().reset_index()['slot']
        
        fig.add_trace(go.Scatter(
            x=avg_match['slot'],
            y=avg_match['match_percentage'],
            mode='lines+markers',
            name='Average Match %',
            line=dict(color='#d62728', width=config.get('line_width', 2)),
            marker=dict(size=config.get('marker_size', 6)),
            hovertemplate='<b>Slot:</b> %{x}<br><b>Avg Match %:</b> %{y:.1f}%<extra></extra>'
        ))
    
    fig.update_layout(
        title="Mempool Match Percentage by Slot",
        xaxis_title="Slot",
        yaxis_title="Match Percentage (%)",
        height=config.get('height', 400),
        showlegend=config.get('show_legend', True),
        hovermode='x unified'
    )
    
    # Add horizontal line at 100%
    fig.add_hline(y=100, line_dash="dash", line_color="gray", opacity=0.5)
    
    if config.get('show_grid', True):
        fig.update_xaxes(showgrid=True)
        fig.update_yaxes(showgrid=True)
    
    return fig


def create_client_comparison_bar(
    summary_df: pd.DataFrame,
    metric: str = "avg_match_percentage",
    chart_config: Optional[Dict[str, Any]] = None
) -> go.Figure:
    """
    Create a bar chart comparing clients by a specific metric.
    
    Args:
        summary_df: Summary DataFrame with client statistics
        metric: Metric to compare ('avg_match_percentage', 'total_canonical_blobs', etc.)
        chart_config: Optional chart configuration
        
    Returns:
        Plotly figure
    """
    if summary_df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No summary data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    config = chart_config or get_default_chart_config()
    
    # Sort by metric value
    sorted_df = summary_df.sort_values(metric, ascending=False)
    
    # Set up metric-specific formatting
    metric_formats = {
        'avg_match_percentage': {'suffix': '%', 'title': 'Average Match Percentage'},
        'total_canonical_blobs': {'suffix': '', 'title': 'Total Canonical Blobs'},
        'total_mempool_blobs': {'suffix': '', 'title': 'Total Mempool Blobs'},
        'total_matching_blobs': {'suffix': '', 'title': 'Total Matching Blobs'},
        'median_match_percentage': {'suffix': '%', 'title': 'Median Match Percentage'},
        'p90_match_percentage': {'suffix': '%', 'title': '90th Percentile Match Percentage'}
    }
    
    format_info = metric_formats.get(metric, {'suffix': '', 'title': metric.replace('_', ' ').title()})
    
    fig = go.Figure(data=[
        go.Bar(
            x=sorted_df['client_name'],
            y=sorted_df[metric],
            text=[f"{val:.1f}{format_info['suffix']}" for val in sorted_df[metric]],
            textposition='auto',
            marker_color='rgba(31, 119, 180, 0.8)',
            hovertemplate='<b>Client:</b> %{x}<br><b>' + format_info['title'] + ':</b> %{y:.1f}' + format_info['suffix'] + '<extra></extra>'
        )
    ])
    
    fig.update_layout(
        title=f"Client Comparison: {format_info['title']}",
        xaxis_title="Client",
        yaxis_title=format_info['title'],
        height=config.get('height', 400),
        showlegend=False
    )
    
    if config.get('show_grid', True):
        fig.update_yaxes(showgrid=True)
    
    return fig


def create_blob_correlation_scatter(
    df: pd.DataFrame,
    chart_config: Optional[Dict[str, Any]] = None
) -> go.Figure:
    """
    Create a scatter plot showing correlation between canonical and mempool blobs.
    
    Args:
        df: DataFrame with canonical_blob_count and mempool_blob_count
        chart_config: Optional chart configuration
        
    Returns:
        Plotly figure
    """
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available for correlation analysis",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    config = chart_config or get_default_chart_config()
    
    # Filter to slots with blobs
    df_with_blobs = df[df['canonical_blob_count'] > 0].copy()
    
    if df_with_blobs.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No slots with blobs found for correlation analysis",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    # Aggregate by slot (sum mempool blobs across clients)
    slot_agg = df_with_blobs.groupby(['slot', 'canonical_blob_count']).agg({
        'mempool_blob_count': 'sum',
        'matching_blob_count': 'sum'
    }).reset_index()
    
    fig = go.Figure()
    
    # Add scatter points
    fig.add_trace(go.Scatter(
        x=slot_agg['canonical_blob_count'],
        y=slot_agg['mempool_blob_count'],
        mode='markers',
        marker=dict(
            size=config.get('marker_size', 8),
            color=slot_agg['matching_blob_count'],
            colorscale='Viridis',
            showscale=True,
            colorbar=dict(title="Matching Blobs"),
            opacity=config.get('opacity', 0.7)
        ),
        text=[f"Slot: {slot}<br>Matches: {matches}" 
              for slot, matches in zip(slot_agg['slot'], slot_agg['matching_blob_count'])],
        hovertemplate='<b>Canonical Blobs:</b> %{x}<br><b>Mempool Blobs:</b> %{y}<br>%{text}<extra></extra>',
        name='Slots'
    ))
    
    # Add diagonal line (perfect correlation)
    max_blobs = max(slot_agg['canonical_blob_count'].max(), slot_agg['mempool_blob_count'].max())
    fig.add_trace(go.Scatter(
        x=[0, max_blobs],
        y=[0, max_blobs],
        mode='lines',
        line=dict(color='red', dash='dash', width=1),
        name='Perfect Correlation',
        hoverinfo='skip'
    ))
    
    fig.update_layout(
        title="Canonical vs Mempool Blob Count Correlation",
        xaxis_title="Canonical Blob Count",
        yaxis_title="Mempool Blob Count (All Clients)",
        height=config.get('height', 400),
        showlegend=config.get('show_legend', True)
    )
    
    if config.get('show_grid', True):
        fig.update_xaxes(showgrid=True)
        fig.update_yaxes(showgrid=True)
    
    return fig


def create_hourly_heatmap(
    timeline_df: pd.DataFrame,
    metric: str = "avg_match_percentage",
    chart_config: Optional[Dict[str, Any]] = None
) -> go.Figure:
    """
    Create a heatmap showing hourly patterns by client.
    
    Args:
        timeline_df: DataFrame with hourly timeline data
        metric: Metric to visualize in heatmap
        chart_config: Optional chart configuration
        
    Returns:
        Plotly figure
    """
    if timeline_df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No timeline data available for heatmap",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    config = chart_config or get_default_chart_config()
    
    # Pivot the data for heatmap
    pivot_data = timeline_df.pivot(index='client_name', columns='hour', values=metric)
    
    if pivot_data.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="Insufficient data for heatmap visualization",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    # Format dates for x-axis
    x_labels = [col.strftime('%m-%d %H:%M') if hasattr(col, 'strftime') else str(col) 
                for col in pivot_data.columns]
    
    fig = go.Figure(data=go.Heatmap(
        z=pivot_data.values,
        x=x_labels,
        y=pivot_data.index,
        colorscale='Viridis',
        showscale=True,
        hoverongaps=False,
        hovertemplate='<b>Client:</b> %{y}<br><b>Time:</b> %{x}<br><b>Value:</b> %{z:.1f}<extra></extra>'
    ))
    
    metric_titles = {
        'avg_match_percentage': 'Average Match Percentage (%)',
        'total_canonical_blobs': 'Total Canonical Blobs',
        'total_mempool_blobs': 'Total Mempool Blobs'
    }
    
    title = metric_titles.get(metric, metric.replace('_', ' ').title())
    
    fig.update_layout(
        title=f"Hourly {title} by Client",
        xaxis_title="Time (Hour)",
        yaxis_title="Client",
        height=max(config.get('height', 400), len(pivot_data.index) * 30),  # Scale height with number of clients
    )
    
    return fig


def create_summary_metrics_cards(summary_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Create summary metrics for display in cards/columns.
    
    Args:
        summary_df: Summary DataFrame with client statistics
        
    Returns:
        Dictionary with summary metrics
    """
    if summary_df.empty:
        return {
            "total_clients": 0,
            "avg_match_rate": 0,
            "total_slots": 0,
            "total_canonical_blobs": 0,
            "total_mempool_blobs": 0,
            "best_client": "N/A",
            "worst_client": "N/A"
        }
    
    # Calculate overall metrics
    total_clients = len(summary_df)
    
    # Weighted average match rate
    total_canonical = summary_df['total_canonical_blobs'].sum()
    total_matching = summary_df['total_matching_blobs'].sum()
    overall_match_rate = (total_matching / total_canonical * 100) if total_canonical > 0 else 0
    
    # Other metrics
    total_slots = summary_df['slots_with_data'].sum()
    total_mempool = summary_df['total_mempool_blobs'].sum()
    
    # Best and worst performing clients
    best_client = summary_df.loc[summary_df['avg_match_percentage'].idxmax(), 'client_name'] if len(summary_df) > 0 else "N/A"
    worst_client = summary_df.loc[summary_df['avg_match_percentage'].idxmin(), 'client_name'] if len(summary_df) > 0 else "N/A"
    
    return {
        "total_clients": total_clients,
        "avg_match_rate": overall_match_rate,
        "total_slots": total_slots,
        "total_canonical_blobs": int(total_canonical),
        "total_mempool_blobs": int(total_mempool),
        "best_client": best_client,
        "worst_client": worst_client
    }


def create_blob_gas_analysis_chart(
    df: pd.DataFrame,
    chart_config: Optional[Dict[str, Any]] = None
) -> go.Figure:
    """
    Create a chart analyzing blob gas usage patterns.
    
    Args:
        df: DataFrame with blob gas data
        chart_config: Optional chart configuration
        
    Returns:
        Plotly figure
    """
    if df.empty or 'avg_blob_gas' not in df.columns:
        fig = go.Figure()
        fig.add_annotation(
            text="No blob gas data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    config = chart_config or get_default_chart_config()
    
    # Filter out zero gas values
    df_with_gas = df[df['avg_blob_gas'] > 0].copy()
    
    if df_with_gas.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No blob gas data available for analysis",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    fig = go.Figure()
    
    # Group by client for comparison
    for client in df_with_gas['client_name'].unique():
        if client == 'No Data':
            continue
            
        client_data = df_with_gas[df_with_gas['client_name'] == client]
        
        fig.add_trace(go.Scatter(
            x=client_data['slot'],
            y=client_data['avg_blob_gas'],
            mode='lines+markers',
            name=f'{client} Blob Gas',
            line=dict(width=config.get('line_width', 2)),
            marker=dict(size=config.get('marker_size', 6)),
            hovertemplate=f'<b>Client:</b> {client}<br><b>Slot:</b> %{{x}}<br><b>Avg Blob Gas:</b> %{{y:,.0f}}<extra></extra>'
        ))
    
    fig.update_layout(
        title="Blob Gas Usage by Client and Slot",
        xaxis_title="Slot",
        yaxis_title="Average Blob Gas",
        height=config.get('height', 400),
        showlegend=config.get('show_legend', True),
        hovermode='x unified'
    )
    
    if config.get('show_grid', True):
        fig.update_xaxes(showgrid=True)
        fig.update_yaxes(showgrid=True)
    
    return fig


def create_blob_size_analysis_chart(
    df: pd.DataFrame,
    chart_config: Optional[Dict[str, Any]] = None
) -> go.Figure:
    """
    Create a chart analyzing blob sidecar size patterns.
    
    Args:
        df: DataFrame with blob sidecar size data
        chart_config: Optional chart configuration
        
    Returns:
        Plotly figure
    """
    if df.empty or 'total_blob_sidecars_size' not in df.columns:
        fig = go.Figure()
        fig.add_annotation(
            text="No blob size data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    config = chart_config or get_default_chart_config()
    
    # Filter out zero size values
    df_with_size = df[df['total_blob_sidecars_size'] > 0].copy()
    
    if df_with_size.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No blob size data available for analysis",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    # Group by slot to show aggregate data
    slot_summary = df_with_size.groupby(['slot', 'slot_start_date_time']).agg({
        'total_blob_sidecars_size': 'sum',
        'mempool_blob_count': 'sum'
    }).reset_index()
    
    fig = go.Figure()
    
    # Add blob size line
    fig.add_trace(go.Scatter(
        x=slot_summary['slot'],
        y=slot_summary['total_blob_sidecars_size'],
        mode='lines+markers',
        name='Total Blob Sidecar Size (bytes)',
        line=dict(color='#1f77b4', width=config.get('line_width', 2)),
        marker=dict(size=config.get('marker_size', 6)),
        hovertemplate='<b>Slot:</b> %{x}<br><b>Total Size:</b> %{y:,.0f} bytes<extra></extra>'
    ))
    
    # Add blob count line (secondary y-axis)
    fig2 = make_subplots(specs=[[{"secondary_y": True}]])
    
    fig2.add_trace(
        go.Scatter(
            x=slot_summary['slot'],
            y=slot_summary['total_blob_sidecars_size'],
            mode='lines+markers',
            name='Blob Size (bytes)',
            line=dict(color='#1f77b4')
        ),
        secondary_y=False,
    )
    
    fig2.add_trace(
        go.Scatter(
            x=slot_summary['slot'],
            y=slot_summary['mempool_blob_count'],
            mode='lines+markers',
            name='Blob Count',
            line=dict(color='#ff7f0e')
        ),
        secondary_y=True,
    )
    
    fig2.update_xaxes(title_text="Slot")
    fig2.update_yaxes(title_text="Blob Sidecar Size (bytes)", secondary_y=False)
    fig2.update_yaxes(title_text="Number of Blobs", secondary_y=True)
    
    fig2.update_layout(
        title="Blob Size and Count Analysis",
        height=config.get('height', 400),
        showlegend=True,
        hovermode='x unified'
    )
    
    return fig2


def create_dual_axis_chart(
    df: pd.DataFrame,
    chart_config: Optional[Dict[str, Any]] = None
) -> go.Figure:
    """
    Create a dual-axis chart showing blob counts and match percentages.
    
    Args:
        df: DataFrame with blob data
        chart_config: Optional chart configuration
        
    Returns:
        Plotly figure with dual y-axes
    """
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available for dual-axis chart",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    config = chart_config or get_default_chart_config()
    
    # Group by slot for aggregate view
    slot_data = df.groupby(['slot', 'slot_start_date_time']).agg({
        'canonical_blob_count': 'first',
        'mempool_blob_count': 'sum',
        'match_percentage': 'mean'
    }).reset_index()
    
    # Create subplots with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Add blob count traces (left y-axis)
    fig.add_trace(
        go.Scatter(
            x=slot_data['slot'],
            y=slot_data['canonical_blob_count'],
            mode='lines+markers',
            name='Canonical Blobs',
            line=dict(color='#1f77b4'),
            marker=dict(size=6)
        ),
        secondary_y=False,
    )
    
    fig.add_trace(
        go.Scatter(
            x=slot_data['slot'],
            y=slot_data['mempool_blob_count'],
            mode='lines+markers',
            name='Mempool Blobs',
            line=dict(color='#ff7f0e'),
            marker=dict(size=6)
        ),
        secondary_y=False,
    )
    
    # Add match percentage trace (right y-axis)
    fig.add_trace(
        go.Scatter(
            x=slot_data['slot'],
            y=slot_data['match_percentage'],
            mode='lines+markers',
            name='Match %',
            line=dict(color='#2ca02c', dash='dash'),
            marker=dict(size=6)
        ),
        secondary_y=True,
    )
    
    # Set titles
    fig.update_xaxes(title_text="Slot")
    fig.update_yaxes(title_text="Number of Blobs", secondary_y=False)
    fig.update_yaxes(title_text="Match Percentage (%)", secondary_y=True)
    
    fig.update_layout(
        title="Blob Counts and Match Rates by Slot",
        height=config.get('height', 400),
        showlegend=True,
        hovermode='x unified'
    )
    
    return fig
