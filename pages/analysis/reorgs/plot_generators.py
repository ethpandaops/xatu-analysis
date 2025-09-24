"""
Visualization functions for reorg analysis
"""
import streamlit as st
import polars as pl
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from typing import Optional
from shared.ui_components import add_ethPandaOps_logo
from pages.analysis.reorgs.config_utils import get_metric_info, get_depth_filter_config

def create_reorg_timeline(df: pl.DataFrame, time_bucket: str = "1h") -> go.Figure:
    """Create a time series visualization of reorg events."""
    from metrics_calculators import calculate_reorg_rate
    
    # Calculate reorg rate
    rate_df = calculate_reorg_rate(df, time_bucket)
    rate_pandas = rate_df.to_pandas()
    
    # Create figure with secondary y-axis
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        subplot_titles=("Reorg Frequency", "Maximum Depth"),
        specs=[[{"secondary_y": False}], [{"secondary_y": False}]]
    )
    
    # Add reorg count trace
    fig.add_trace(
        go.Bar(
            x=rate_pandas['time_bucket'],
            y=rate_pandas['reorg_count'],
            name='Reorg Count',
            marker_color='#ff6b6b',
            hovertemplate='Time: %{x}<br>Count: %{y}<br>Avg Depth: %{customdata[0]:.1f}<extra></extra>',
            customdata=rate_pandas[['avg_depth']]
        ),
        row=1, col=1
    )
    
    # Add max depth trace
    fig.add_trace(
        go.Scatter(
            x=rate_pandas['time_bucket'],
            y=rate_pandas['max_depth'],
            mode='lines+markers',
            name='Max Depth',
            line=dict(color='#4ecdc4', width=2),
            marker=dict(size=6),
            hovertemplate='Time: %{x}<br>Max Depth: %{y}<extra></extra>'
        ),
        row=2, col=1
    )
    
    # Update layout
    fig.update_xaxes(title_text="Time", row=2, col=1)
    fig.update_yaxes(title_text="Count", row=1, col=1)
    fig.update_yaxes(title_text="Depth", row=2, col=1)
    
    fig.update_layout(
        height=600,
        title={
            'text': f'Chain Reorganizations Over Time ({time_bucket} buckets)',
            'font': {'size': 16}
        },
        showlegend=True,
        hovermode='x unified'
    )
    
    return add_ethPandaOps_logo(fig)

def create_depth_distribution(df: pl.DataFrame) -> go.Figure:
    """Create histogram and CDF of reorg depths."""
    depth_config = get_depth_filter_config()
    
    # Convert to pandas for plotting
    depths = df['depth'].to_list()
    
    # Create subplots
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=("Depth Distribution", "Cumulative Distribution"),
        horizontal_spacing=0.15
    )
    
    # Histogram
    fig.add_trace(
        go.Histogram(
            x=depths,
            nbinsx=min(30, df['depth'].max()),
            name='Frequency',
            marker_color='#667eea',
            hovertemplate='Depth: %{x}<br>Count: %{y}<extra></extra>'
        ),
        row=1, col=1
    )
    
    # Calculate CDF
    sorted_depths = sorted(depths)
    cdf_y = np.arange(1, len(sorted_depths) + 1) / len(sorted_depths) * 100
    
    fig.add_trace(
        go.Scatter(
            x=sorted_depths,
            y=cdf_y,
            mode='lines',
            name='CDF',
            line=dict(color='#f093fb', width=2),
            hovertemplate='Depth: %{x}<br>Percentile: %{y:.1f}%<extra></extra>'
        ),
        row=1, col=2
    )
    
    # Add percentile markers
    percentiles = [50, 95, 99]
    for p in percentiles:
        val = np.percentile(depths, p)
        fig.add_vline(x=val, line_dash="dash", line_color="gray", 
                     annotation_text=f"P{p}: {val:.0f}", row=1, col=2)
    
    # Update axes
    fig.update_xaxes(title_text="Depth", row=1, col=1)
    fig.update_xaxes(title_text="Depth", row=1, col=2)
    fig.update_yaxes(title_text="Count", row=1, col=1)
    fig.update_yaxes(title_text="Percentile (%)", row=1, col=2)
    
    fig.update_layout(
        height=400,
        title={'text': 'Reorg Depth Analysis', 'font': {'size': 16}},
        showlegend=False
    )
    
    return add_ethPandaOps_logo(fig)

def create_client_comparison(client_metrics: pl.DataFrame, node_level: bool = False) -> go.Figure:
    """Create comparison chart of clients or implementations."""
    client_pandas = client_metrics.to_pandas()
    
    # Determine the x-axis based on whether this is node-level or implementation-level
    if node_level and 'meta_client_name' in client_pandas.columns:
        x_column = 'meta_client_name'
        title_suffix = "by Node"
        # Truncate long node names for readability
        client_pandas['display_name'] = client_pandas['meta_client_name'].apply(
            lambda x: x[:30] + '...' if len(x) > 30 else x
        )
        x_values = client_pandas['display_name']
    else:
        x_column = 'meta_consensus_implementation'
        title_suffix = "by Implementation"
        x_values = client_pandas[x_column]
    
    # Create subplots for different metrics
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            f"Reorg Count {title_suffix}",
            f"Average Depth {title_suffix}", 
            f"Detection Delay {title_suffix}",
            "Deep Reorgs (>2 blocks)"
        ),
        specs=[[{"type": "bar"}, {"type": "bar"}],
               [{"type": "bar"}, {"type": "bar"}]]
    )
    
    # Reorg count
    if node_level and 'meta_consensus_implementation' in client_pandas.columns:
        # For node-level, show implementation in hover
        hover_text = [
            f"{name}<br>Implementation: {impl}<br>Count: {count}"
            for name, impl, count in zip(
                client_pandas['meta_client_name'],
                client_pandas['meta_consensus_implementation'],
                client_pandas['reorg_count']
            )
        ]
        fig.add_trace(
            go.Bar(
                x=x_values,
                y=client_pandas['reorg_count'],
                marker_color='#667eea',
                hovertemplate='%{text}<extra></extra>',
                text=hover_text
            ),
            row=1, col=1
        )
    else:
        fig.add_trace(
            go.Bar(
                x=x_values,
                y=client_pandas['reorg_count'],
                marker_color='#667eea',
                hovertemplate='%{x}<br>Count: %{y}<extra></extra>'
            ),
            row=1, col=1
        )
    
    # Average depth box plot (if we have the raw data)
    # For now, using bar chart with error bars
    fig.add_trace(
        go.Bar(
            x=x_values,
            y=client_pandas['avg_depth'],
            error_y=dict(type='data', array=client_pandas['depth_std']) if 'depth_std' in client_pandas.columns else None,
            marker_color='#f093fb',
            hovertemplate='%{x}<br>Avg Depth: %{y:.2f}<extra></extra>'
        ),
        row=1, col=2
    )
    
    # Detection delay
    fig.add_trace(
        go.Bar(
            x=x_values,
            y=client_pandas['avg_detection_delay'],
            marker_color='#4ecdc4',
            hovertemplate='%{x}<br>Avg Delay: %{y:.2f}s<extra></extra>'
        ),
        row=2, col=1
    )
    
    # Deep reorgs
    fig.add_trace(
        go.Bar(
            x=x_values,
            y=client_pandas['deep_reorgs'],
            marker_color='#ff6b6b',
            hovertemplate='%{x}<br>Deep Reorgs: %{y}<extra></extra>'
        ),
        row=2, col=2
    )
    
    # Update layout
    fig.update_xaxes(tickangle=45)
    
    title_text = 'Individual Node Comparison' if node_level else 'Client Implementation Comparison'
    fig.update_layout(
        height=700,
        title={'text': title_text, 'font': {'size': 16}},
        showlegend=False
    )
    
    return add_ethPandaOps_logo(fig)

def create_epoch_boundary_heatmap(df: pl.DataFrame) -> go.Figure:
    """Create heatmap of reorgs by epoch and slot position."""
    # Create pivot table
    pivot_df = df.group_by(['epoch', 'slot_in_epoch']).agg(
        pl.count().alias('reorg_count')
    )
    
    # Convert to matrix format
    epochs = sorted(pivot_df['epoch'].unique().to_list())
    slot_positions = list(range(32))  # 32 slots per epoch
    
    # Create matrix
    z_data = []
    for epoch in epochs[-50:]:  # Last 50 epochs for visibility
        row = []
        for slot_pos in slot_positions:
            count = pivot_df.filter(
                (pl.col('epoch') == epoch) & 
                (pl.col('slot_in_epoch') == slot_pos)
            )
            row.append(count['reorg_count'][0] if len(count) > 0 else 0)
        z_data.append(row)
    
    # Create heatmap
    fig = go.Figure(data=go.Heatmap(
        z=z_data,
        x=slot_positions,
        y=epochs[-50:],
        colorscale='Viridis',
        hovertemplate='Epoch: %{y}<br>Slot Position: %{x}<br>Reorgs: %{z}<extra></extra>'
    ))
    
    fig.update_layout(
        title={'text': 'Reorg Distribution by Epoch and Slot Position', 'font': {'size': 16}},
        xaxis_title='Slot Position in Epoch',
        yaxis_title='Epoch',
        height=600
    )
    
    return add_ethPandaOps_logo(fig)

def create_episode_timeline(episodes: pl.DataFrame) -> go.Figure:
    """Create Gantt-style chart of reorg episodes."""
    if episodes.is_empty():
        fig = go.Figure()
        fig.add_annotation(
            text="No reorg episodes detected",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return add_ethPandaOps_logo(fig)
    
    episodes_pandas = episodes.to_pandas()
    
    # Sort by severity for coloring
    episodes_pandas = episodes_pandas.sort_values('severity_score', ascending=False)
    
    # Create Gantt chart
    fig = go.Figure()
    
    for idx, episode in episodes_pandas.iterrows():
        # Color based on severity
        if episode['severity_score'] > 0.7:
            color = '#ff6b6b'  # Red for high severity
        elif episode['severity_score'] > 0.4:
            color = '#feca57'  # Yellow for medium
        else:
            color = '#48dbfb'  # Blue for low
        
        fig.add_trace(go.Scatter(
            x=[episode['episode_start'], episode['episode_end']],
            y=[idx, idx],
            mode='lines+markers',
            line=dict(color=color, width=10),
            marker=dict(size=8),
            name=f"Episode {episode['episode_id']}",
            hovertemplate=(
                f"Episode ID: {episode['episode_id']}<br>"
                f"Start: %{{x[0]}}<br>"
                f"End: %{{x[1]}}<br>"
                f"Max Depth: {episode['max_depth']}<br>"
                f"Severity: {episode['severity_score']:.2f}<br>"
                f"Clients: {episode['reporting_clients']}<extra></extra>"
            ),
            showlegend=False
        ))
    
    fig.update_layout(
        title={'text': 'Reorg Episode Timeline (Top 50 by Severity)', 'font': {'size': 16}},
        xaxis_title='Time',
        yaxis_title='Episode',
        height=max(400, len(episodes_pandas) * 15),
        yaxis=dict(showticklabels=False),
        hovermode='closest'
    )
    
    return add_ethPandaOps_logo(fig)

def create_scatter_matrix(df: pl.DataFrame) -> go.Figure:
    """Create scatter matrix for multi-dimensional analysis."""
    # Select key columns for scatter matrix
    columns = ['depth', 'detection_delay_seconds', 'slot_in_epoch']
    
    # Sample if too many points
    if len(df) > 1000:
        sample_df = df.sample(n=1000)
    else:
        sample_df = df
    
    sample_pandas = sample_df.to_pandas()
    
    # Create scatter matrix
    fig = px.scatter_matrix(
        sample_pandas,
        dimensions=columns,
        color='meta_consensus_implementation',
        title='Multi-dimensional Reorg Analysis',
        height=700
    )
    
    fig.update_traces(diagonal_visible=False)
    
    return add_ethPandaOps_logo(fig)

def create_geographic_distribution(geo_metrics: pl.DataFrame) -> go.Figure:
    """Create geographic distribution visualization."""
    if geo_metrics.is_empty():
        fig = go.Figure()
        fig.add_annotation(
            text="No geographic data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return add_ethPandaOps_logo(fig)
    
    geo_pandas = geo_metrics.head(20).to_pandas()  # Top 20 countries
    
    # Create horizontal bar chart
    fig = go.Figure(go.Bar(
        x=geo_pandas['reorg_count'],
        y=geo_pandas['meta_client_geo_country'],
        orientation='h',
        marker_color='#667eea',
        hovertemplate='%{y}<br>Reorgs: %{x}<br>Percentage: %{customdata[0]:.1f}%<extra></extra>',
        customdata=geo_pandas[['pct_of_total']]
    ))
    
    fig.update_layout(
        title={'text': 'Reorg Distribution by Country (Top 20)', 'font': {'size': 16}},
        xaxis_title='Reorg Count',
        yaxis_title='Country',
        height=max(400, len(geo_pandas) * 25),
        yaxis={'categoryorder': 'total ascending'}
    )
    
    return add_ethPandaOps_logo(fig)

def create_correlation_plot(correlation_data: dict) -> go.Figure:
    """Create visualization of missed slot correlation."""
    # Create a simple gauge chart for correlation rate
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=correlation_data.get('correlation_rate', 0),
        title={'text': "Reorgs After Missed Slots (%)"},
        delta={'reference': 50, 'increasing': {'color': "red"}},
        gauge={
            'axis': {'range': [None, 100]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, 25], 'color': "lightgray"},
                {'range': [25, 50], 'color': "gray"},
                {'range': [50, 75], 'color': "orange"},
                {'range': [75, 100], 'color': "red"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 90
            }
        }
    ))
    
    fig.update_layout(height=300)
    
    return add_ethPandaOps_logo(fig)