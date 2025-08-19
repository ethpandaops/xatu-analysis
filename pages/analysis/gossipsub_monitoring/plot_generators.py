"""
Plot generation functions for Gossipsub Monitoring.
"""

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from shared.ui_components import add_ethPandaOps_logo


def create_continent_cdf_plot(
    cdf_data: Dict[str, Tuple[np.ndarray, np.ndarray]],
    slot: Optional[int] = None,
    title: Optional[str] = None
) -> go.Figure:
    """
    Create CDF plot comparing different continents with attestation CDF styling.
    
    Args:
        cdf_data: Dictionary mapping continent to (x_values, y_values)
        slot: Slot number being analyzed
        title: Custom title for the plot
        
    Returns:
        Plotly figure
    """
    fig = go.Figure()
    
    # Use the same color palette as attestation CDF
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']
    color_idx = 0
    
    # Collect all times for percentile calculations
    all_times_seconds = []
    
    # Add trace for each continent
    for continent, (x_values, y_values) in cdf_data.items():
        # Convert to seconds for display
        x_seconds = x_values / 1000.0
        all_times_seconds.extend(x_seconds)
        
        # Count peers for this continent
        peer_count = len(x_values)
        
        fig.add_trace(go.Scatter(
            x=x_seconds,
            y=y_values,
            mode='lines',
            name=f"{continent} ({peer_count:,} peers)",
            line=dict(color=colors[color_idx % len(colors)], width=2),
            hovertemplate=f'<b>{continent}</b><br>' +
                        f'Total Peers: {peer_count:,}<br>' +
                        'Time: %{x:.2f}s<br>' +
                        'Cumulative Probability: %{y:.2%}<br>' +
                        '<extra></extra>'
        ))
        color_idx += 1
    
    # Calculate and add P66 and P95 vertical lines (matching attestation CDF)
    if all_times_seconds:
        sorted_all_times = np.sort(all_times_seconds)
        p66_time = np.percentile(sorted_all_times, 66)
        p95_time = np.percentile(sorted_all_times, 95)
        
        # Add vertical lines at percentile times
        fig.add_vline(x=p66_time, line_dash="dot", line_color="orange", opacity=0.5,
                     annotation_text=f"P66: {p66_time:.2f}s", annotation_position="top")
        fig.add_vline(x=p95_time, line_dash="dot", line_color="red", opacity=0.5,
                     annotation_text=f"P95: {p95_time:.2f}s", annotation_position="top")
    
    # Update layout to match attestation CDF
    if title:
        plot_title = title
    elif slot:
        plot_title = f"Gossipsub Block Propagation CDF - Slot {slot}<br><sub>Cumulative distribution of beacon block IHAVE arrival times</sub>"
    else:
        plot_title = "Gossipsub Block Propagation CDF Analysis<br><sub>Cumulative distribution of beacon block IHAVE arrival times across continents</sub>"
    
    fig.update_layout(
        title=plot_title,
        xaxis_title='Propagation Time (seconds)',
        yaxis_title='Cumulative Probability',
        height=600,
        hovermode='x unified',
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
        title_font_size=16,
        xaxis=dict(
            showgrid=True,
            gridwidth=1,
            gridcolor='rgba(128, 128, 128, 0.2)',
            range=[0, None]  # Start from 0
        ),
        yaxis=dict(
            showgrid=True,
            gridwidth=1,
            gridcolor='rgba(128, 128, 128, 0.2)',
            range=[0, 1],
            tickformat='.0%'
        )
    )
    
    # Add ethPandaOps logo
    return add_ethPandaOps_logo(fig)


def create_slot_cdf_plot(
    cdf_data: Dict[int, Tuple[np.ndarray, np.ndarray]],
    title: Optional[str] = None
) -> go.Figure:
    """
    Create CDF plot comparing different slots with attestation CDF styling.
    
    Args:
        cdf_data: Dictionary mapping slot to (x_values, y_values)
        title: Custom title for the plot
        
    Returns:
        Plotly figure
    """
    fig = go.Figure()
    
    # Use the same color palette as attestation CDF
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']
    
    # Collect all times for percentile calculations
    all_times_seconds = []
    
    # Add trace for each slot
    sorted_slots = sorted(cdf_data.keys(), reverse=True)  # Most recent first
    
    for idx, slot in enumerate(sorted_slots):
        x_values, y_values = cdf_data[slot]
        
        # Convert to seconds for display
        x_seconds = x_values / 1000.0
        all_times_seconds.extend(x_seconds)
        
        # Count peers for this slot
        peer_count = len(x_values)
        
        fig.add_trace(go.Scatter(
            x=x_seconds,
            y=y_values,
            mode='lines',
            name=f"Slot {slot:,} ({peer_count:,} peers)",
            line=dict(color=colors[idx % len(colors)], width=2),
            hovertemplate=f'<b>Slot {slot:,}</b><br>' +
                        f'Total Peers: {peer_count:,}<br>' +
                        'Time: %{x:.2f}s<br>' +
                        'Cumulative Probability: %{y:.2%}<br>' +
                        '<extra></extra>'
        ))
    
    # Calculate and add P66 and P95 vertical lines (matching attestation CDF)
    if all_times_seconds:
        sorted_all_times = np.sort(all_times_seconds)
        p66_time = np.percentile(sorted_all_times, 66)
        p95_time = np.percentile(sorted_all_times, 95)
        
        # Add vertical lines at percentile times
        fig.add_vline(x=p66_time, line_dash="dot", line_color="orange", opacity=0.5,
                     annotation_text=f"P66: {p66_time:.2f}s", annotation_position="top")
        fig.add_vline(x=p95_time, line_dash="dot", line_color="red", opacity=0.5,
                     annotation_text=f"P95: {p95_time:.2f}s", annotation_position="top")
    
    
    # Update layout to match attestation CDF
    plot_title = title or "Gossipsub Block Propagation CDF by Slot<br><sub>Cumulative distribution of beacon block IHAVE arrival times per slot</sub>"
    
    fig.update_layout(
        title=plot_title,
        xaxis_title='Propagation Time (seconds)',
        yaxis_title='Cumulative Probability',
        height=600,
        hovermode='x unified',
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
        title_font_size=16,
        xaxis=dict(
            showgrid=True,
            gridwidth=1,
            gridcolor='rgba(128, 128, 128, 0.2)',
            range=[0, None]
        ),
        yaxis=dict(
            showgrid=True,
            gridwidth=1,
            gridcolor='rgba(128, 128, 128, 0.2)',
            range=[0, 1],
            tickformat='.0%'
        )
    )
    
    # Add ethPandaOps logo
    return add_ethPandaOps_logo(fig)


def create_percentile_comparison_chart(
    percentiles_df: pd.DataFrame,
    slot: Optional[int] = None
) -> go.Figure:
    """
    Create bar chart comparing percentiles across continents with attestation CDF styling.
    
    Args:
        percentiles_df: DataFrame with percentile data by continent
        slot: Slot number being analyzed
        
    Returns:
        Plotly figure
    """
    if percentiles_df.empty:
        return go.Figure().add_annotation(
            text="No data available for percentile comparison",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    # Sort by P50 for better visualization
    percentiles_df = percentiles_df.sort_values('p50')
    
    fig = go.Figure()
    
    # Use the same color palette as attestation CDF
    percentiles_to_show = ['p50', 'p75', 'p90', 'p95']
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']
    
    for i, p in enumerate(percentiles_to_show):
        if p in percentiles_df.columns:
            # Values are already in milliseconds, keep them for consistency
            values = percentiles_df[p]
            
            # Determine group column
            group_col = 'continent' if 'continent' in percentiles_df.columns else 'slot'
            
            fig.add_trace(go.Bar(
                name=f'P{p[1:]}',
                x=percentiles_df[group_col] if group_col == 'continent' else [f"Slot {s:,}" for s in percentiles_df[group_col]],
                y=values,
                text=[f"{v:.0f}ms" for v in values],
                textposition='auto',
                marker_color=colors[i],
                hovertemplate='<b>%{x}</b><br>' +
                            f'P{p[1:]}: %{{y:.0f}}ms<br>' +
                            '<extra></extra>'
            ))
    
    # Title with subtitle matching attestation style
    if slot:
        title = f"Propagation Time Percentiles - Slot {slot}<br><sub>Statistical distribution of beacon block IHAVE arrival times</sub>"
    else:
        group_type = 'Continent' if 'continent' in percentiles_df.columns else 'Slot'
        title = f"Propagation Time Percentiles by {group_type}<br><sub>Statistical distribution of beacon block IHAVE arrival times</sub>"
    
    fig.update_layout(
        title=title,
        xaxis_title="Continent" if 'continent' in percentiles_df.columns else "Slot",
        yaxis_title="Propagation Time (milliseconds)",
        barmode='group',
        height=500,
        showlegend=True,
        legend=dict(
            title="Percentile",
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02
        ),
        hovermode='x unified',
        title_font_size=16
    )
    
    return add_ethPandaOps_logo(fig)


def create_peer_distribution_map(
    df: pd.DataFrame,
    slot: Optional[int] = None
) -> go.Figure:
    """
    Create a geographic distribution visualization of peers.
    
    Args:
        df: DataFrame with peer data including continent information
        slot: Slot number being analyzed
        
    Returns:
        Plotly figure
    """
    if df.empty or 'continent' not in df.columns:
        return go.Figure().add_annotation(
            text="No geographic data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    # Aggregate by continent
    continent_stats = df.groupby('continent').agg({
        'peer_id': 'nunique',
        'propagation_delay_ms': ['mean', 'median', 'std']
    }).reset_index()
    
    # Flatten column names
    continent_stats.columns = ['continent', 'peer_count', 'mean_delay', 'median_delay', 'std_delay']
    
    # Convert to seconds
    continent_stats['mean_delay'] = continent_stats['mean_delay'] / 1000.0
    continent_stats['median_delay'] = continent_stats['median_delay'] / 1000.0
    
    # Create bubble chart
    fig = go.Figure()
    
    # Define positions for continents (simplified world map layout)
    continent_positions = {
        'North America': (-100, 45),
        'South America': (-60, -15),
        'Europe': (10, 50),
        'Africa': (20, 0),
        'Asia': (80, 30),
        'Oceania': (135, -25),
        'Unknown': (0, -60)
    }
    
    for _, row in continent_stats.iterrows():
        continent = row['continent']
        if continent in continent_positions:
            x, y = continent_positions[continent]
            
            # Size based on peer count
            size = max(10, min(50, row['peer_count'] * 2))
            
            fig.add_trace(go.Scatter(
                x=[x],
                y=[y],
                mode='markers+text',
                marker=dict(
                    size=size,
                    color=row['median_delay'],
                    colorscale='RdYlGn_r',
                    showscale=True,
                    colorbar=dict(title="Median Delay (s)"),
                    line=dict(width=2, color='white')
                ),
                text=f"{continent}<br>{row['peer_count']} peers<br>{row['median_delay']:.2f}s",
                textposition="top center",
                hovertemplate=f"<b>{continent}</b><br>" +
                            f"Peers: {row['peer_count']}<br>" +
                            f"Mean delay: {row['mean_delay']:.2f}s<br>" +
                            f"Median delay: {row['median_delay']:.2f}s<br>" +
                            "<extra></extra>",
                showlegend=False
            ))
    
    # Title with subtitle matching attestation style
    if slot:
        title = f"Global Peer Distribution and Performance - Slot {slot}<br><sub>Geographic distribution of peers and their median propagation times</sub>"
    else:
        title = "Global Peer Distribution and Performance<br><sub>Geographic distribution of peers and their median propagation times</sub>"
    
    fig.update_layout(
        title=title,
        xaxis=dict(
            showgrid=False,
            showticklabels=False,
            zeroline=False,
            range=[-180, 180]
        ),
        yaxis=dict(
            showgrid=False,
            showticklabels=False,
            zeroline=False,
            range=[-90, 90]
        ),
        height=500,
        hovermode='closest',
        title_font_size=16
    )
    
    return add_ethPandaOps_logo(fig)


def create_time_series_analysis(
    df: pd.DataFrame,
    grouping: str = 'continent'
) -> go.Figure:
    """
    Create time series analysis of propagation delays.
    
    Args:
        df: DataFrame with time series data
        grouping: Column to group by (e.g., 'continent', 'country')
        
    Returns:
        Plotly figure
    """
    if df.empty or 'slot' not in df.columns:
        return go.Figure().add_annotation(
            text="No time series data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    # Aggregate by slot and grouping
    agg_data = df.groupby(['slot', grouping])['propagation_delay_ms'].agg(['mean', 'median', 'count']).reset_index()
    
    # Convert to seconds
    agg_data['mean'] = agg_data['mean'] / 1000.0
    agg_data['median'] = agg_data['median'] / 1000.0
    
    fig = go.Figure()
    
    # Add line for each group
    for group in agg_data[grouping].unique():
        group_data = agg_data[agg_data[grouping] == group].sort_values('slot')
        
        if len(group_data) > 1:  # Need at least 2 points for a line
            fig.add_trace(go.Scatter(
                x=group_data['slot'],
                y=group_data['median'],
                mode='lines+markers',
                name=group,
                hovertemplate=f'<b>{group}</b><br>' +
                            'Slot: %{x}<br>' +
                            'Median: %{y:.2f}s<br>' +
                            '<extra></extra>'
            ))
    
    fig.update_layout(
        title="Propagation Delay Trends Over Time",
        xaxis_title="Slot",
        yaxis_title="Median Propagation Time (seconds)",
        height=500,
        hovermode='x unified',
        showlegend=True
    )
    
    return add_ethPandaOps_logo(fig)