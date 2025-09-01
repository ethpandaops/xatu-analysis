"""
Performance gap analysis for PeerDAS node classes.

This module creates visualizations to analyze how performance differences
between node classes scale with blob count.
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, Any, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_node_performance_gap_analysis(
    data: pd.DataFrame,
    bucket_size: Optional[int] = None,
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    show_relative: bool = True
) -> go.Figure:
    """
    Create visualization showing performance gap between node classes.
    
    This chart helps analyze if the performance difference between node types
    scales linearly with blob count or shows other patterns.
    
    Args:
        data: DataFrame with raw PeerDAS data including node_class
        bucket_size: Optional bucket size for grouping blob counts
        network: Network name
        time_range: Time range string
        metadata: Additional metadata
        show_relative: Show relative (%) difference in addition to absolute
        
    Returns:
        Plotly figure showing performance gaps between node classes
    """
    if data.empty:
        logger.warning("Cannot create gap analysis: empty data")
        return go.Figure()
    
    # Convert milliseconds to seconds
    data = data.copy()
    data['data_available_time'] = data['data_available_time'] / 1000.0
    
    # Apply bucketing if requested
    if bucket_size and bucket_size > 1:
        data['blob_group'] = ((data['blob_count'] - 1) // bucket_size) * bucket_size + 1
        data['blob_label'] = data['blob_group'].apply(
            lambda x: f"{int(x)}-{int(x+bucket_size-1)}"
        )
        group_col = 'blob_group'
        label_col = 'blob_label'
        x_title = f'Blob Count (buckets of {bucket_size})'
    else:
        data['blob_group'] = data['blob_count']
        data['blob_label'] = data['blob_count'].astype(str)
        group_col = 'blob_group'
        label_col = 'blob_label'
        x_title = 'Blob Count'
    
    # Calculate statistics for each node class at each blob count
    stats = []
    for blob_val in sorted(data[group_col].unique()):
        blob_data = data[data[group_col] == blob_val]
        blob_label = blob_data[label_col].iloc[0]
        
        # Calculate median, mean, and percentiles for each node class
        for node_class in ['non-validating', 'validating-standard', 'supernode']:
            class_data = blob_data[blob_data['node_class'] == node_class]
            if not class_data.empty:
                times = class_data['data_available_time']
                stats.append({
                    'blob_count': blob_val,
                    'blob_label': blob_label,
                    'node_class': node_class,
                    'median': times.median(),
                    'mean': times.mean(),
                    'p25': times.quantile(0.25),
                    'p75': times.quantile(0.75),
                    'count': len(class_data)
                })
    
    if not stats:
        logger.warning("No statistics could be calculated")
        return go.Figure()
    
    stats_df = pd.DataFrame(stats)
    
    # Create figure with subplots
    if show_relative:
        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=('Absolute Performance Gap (seconds)', 'Relative Performance Gap (%)'),
            vertical_spacing=0.15,
            row_heights=[0.5, 0.5]
        )
        row_for_absolute = 1
        row_for_relative = 2
    else:
        fig = go.Figure()
        row_for_absolute = None
        row_for_relative = None
    
    # Define colors
    colors = {
        'standard-vs-non': '#2E7D32',  # Dark green
        'super-vs-standard': '#D32F2F',  # Dark red
        'super-vs-non': '#1565C0'  # Dark blue
    }
    
    # Calculate gaps between different node class pairs
    gap_data = []
    for blob_val in sorted(stats_df['blob_count'].unique()):
        blob_stats = stats_df[stats_df['blob_count'] == blob_val]
        blob_label = blob_stats['blob_label'].iloc[0]
        
        non_val = blob_stats[blob_stats['node_class'] == 'non-validating']
        standard = blob_stats[blob_stats['node_class'] == 'validating-standard']
        supernode = blob_stats[blob_stats['node_class'] == 'supernode']
        
        # Calculate gaps (positive means faster/better)
        if not non_val.empty and not standard.empty:
            gap_data.append({
                'blob_count': blob_val,
                'blob_label': blob_label,
                'comparison': 'Standard vs Non-Validating',
                'gap': non_val['median'].iloc[0] - standard['median'].iloc[0],
                'gap_pct': ((non_val['median'].iloc[0] - standard['median'].iloc[0]) / non_val['median'].iloc[0]) * 100,
                'base_time': non_val['median'].iloc[0]
            })
        
        if not standard.empty and not supernode.empty:
            gap_data.append({
                'blob_count': blob_val,
                'blob_label': blob_label,
                'comparison': 'Supernode vs Standard',
                'gap': standard['median'].iloc[0] - supernode['median'].iloc[0],
                'gap_pct': ((standard['median'].iloc[0] - supernode['median'].iloc[0]) / standard['median'].iloc[0]) * 100,
                'base_time': standard['median'].iloc[0]
            })
        
        if not non_val.empty and not supernode.empty:
            gap_data.append({
                'blob_count': blob_val,
                'blob_label': blob_label,
                'comparison': 'Supernode vs Non-Validating',
                'gap': non_val['median'].iloc[0] - supernode['median'].iloc[0],
                'gap_pct': ((non_val['median'].iloc[0] - supernode['median'].iloc[0]) / non_val['median'].iloc[0]) * 100,
                'base_time': non_val['median'].iloc[0]
            })
    
    if not gap_data:
        logger.warning("Could not calculate gaps between node classes")
        return go.Figure()
    
    gap_df = pd.DataFrame(gap_data)
    
    # Plot absolute differences
    for comparison in gap_df['comparison'].unique():
        comp_data = gap_df[gap_df['comparison'] == comparison]
        color_key = {
            'Standard vs Non-Validating': 'standard-vs-non',
            'Supernode vs Standard': 'super-vs-standard',
            'Supernode vs Non-Validating': 'super-vs-non'
        }.get(comparison, 'standard-vs-non')
        
        # Absolute gap
        if show_relative:
            fig.add_trace(
                go.Scatter(
                    x=comp_data['blob_count'],
                    y=comp_data['gap'],
                    mode='lines+markers',
                    name=comparison,
                    marker=dict(size=8, color=colors[color_key]),
                    line=dict(width=2, color=colors[color_key]),
                    hovertemplate='Blob Count: %{x}<br>' +
                                 f'{comparison}<br>' +
                                 'Performance Gap: %{y:.3f}s<br>' +
                                 '<extra></extra>'
                ),
                row=row_for_absolute, col=1
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=comp_data['blob_count'],
                    y=comp_data['gap'],
                    mode='lines+markers',
                    name=comparison,
                    marker=dict(size=8, color=colors[color_key]),
                    line=dict(width=2, color=colors[color_key]),
                    hovertemplate='Blob Count: %{x}<br>' +
                                 f'{comparison}<br>' +
                                 'Performance Gap: %{y:.3f}s<br>' +
                                 '<extra></extra>'
                )
            )
        
        # Add trend line for absolute gap
        if len(comp_data) > 2:
            from scipy import stats
            slope, intercept, r_value, _, _ = stats.linregress(comp_data['blob_count'], comp_data['gap'])
            x_trend = np.array([comp_data['blob_count'].min(), comp_data['blob_count'].max()])
            y_trend = slope * x_trend + intercept
            
            if show_relative:
                fig.add_trace(
                    go.Scatter(
                        x=x_trend,
                        y=y_trend,
                        mode='lines',
                        name=f'{comparison} Trend',
                        line=dict(dash='dash', width=1, color=colors[color_key]),
                        opacity=0.5,
                        showlegend=False,
                        hovertemplate=f'Slope: {slope:.4f}s per blob<br>R²: {r_value**2:.3f}<extra></extra>'
                    ),
                    row=row_for_absolute, col=1
                )
            else:
                fig.add_trace(
                    go.Scatter(
                        x=x_trend,
                        y=y_trend,
                        mode='lines',
                        name=f'{comparison} Trend',
                        line=dict(dash='dash', width=1, color=colors[color_key]),
                        opacity=0.5,
                        showlegend=False,
                        hovertemplate=f'Slope: {slope:.4f}s per blob<br>R²: {r_value**2:.3f}<extra></extra>'
                    )
                )
        
        # Relative gap (percentage)
        if show_relative:
            fig.add_trace(
                go.Scatter(
                    x=comp_data['blob_count'],
                    y=comp_data['gap_pct'],
                    mode='lines+markers',
                    name=comparison,
                    marker=dict(size=8, color=colors[color_key]),
                    line=dict(width=2, color=colors[color_key]),
                    showlegend=False,
                    hovertemplate='Blob Count: %{x}<br>' +
                                 f'{comparison}<br>' +
                                 'Performance Gap: %{y:.1f}%<br>' +
                                 '<extra></extra>'
                ),
                row=row_for_relative, col=1
            )
    
    # Create title
    main_title = 'Node Performance Gap Analysis'
    
    # Update layout
    if show_relative:
        fig.update_xaxes(title_text=x_title, row=2, col=1)
        fig.update_xaxes(title_text='', row=1, col=1)
        fig.update_yaxes(title_text='Performance Gap (seconds)', row=1, col=1)
        fig.update_yaxes(title_text='Performance Gap (%)', row=2, col=1)
    else:
        fig.update_xaxes(title_text=x_title)
        fig.update_yaxes(title_text='Performance Gap (seconds)')
    
    # Add zero line for reference
    if show_relative:
        fig.add_hline(y=0, line_dash="dot", line_color="gray", line_width=1, opacity=0.5, row=1, col=1)
        fig.add_hline(y=0, line_dash="dot", line_color="gray", line_width=1, opacity=0.5, row=2, col=1)
    else:
        fig.add_hline(y=0, line_dash="dot", line_color="gray", line_width=1, opacity=0.5)
    
    # Create metadata parts for subtitle
    metadata_parts = []
    if network:
        metadata_parts.append(f"Network: {network}")
    if time_range:
        metadata_parts.append(f"Period: {time_range}")
    
    # Add subtitle annotation
    if metadata_parts:
        fig.add_annotation(
            text=' | '.join(metadata_parts),
            showarrow=False,
            xref="paper", yref="paper",
            x=0.5, y=1.02,
            xanchor='center', yanchor='bottom',
            font=dict(size=12, color="gray")
        )
    
    # Add ethPandaOps logo
    fig.add_layout_image(
        dict(
            source="https://ethpandaops.io/img/logo-slim.png",
            xref="paper", yref="paper",
            x=0.02, y=0.98,
            sizex=0.08, sizey=0.08,
            xanchor="left", yanchor="top"
        )
    )
    
    # Update general layout
    height = 800 if show_relative else 600
    fig.update_layout(
        title=main_title,
        height=height,
        showlegend=True,
        hovermode='x unified',
        legend=dict(
            orientation="v",
            yanchor="top",
            y=0.95,
            xanchor="left",
            x=1.02,
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="rgba(0,0,0,0.3)",
            borderwidth=1
        ),
        margin=dict(r=250, t=120, l=80)
    )
    
    return fig