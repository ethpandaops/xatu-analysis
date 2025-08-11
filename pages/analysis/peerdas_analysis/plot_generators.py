"""
Plot generation for PeerDAS analysis with ethPandaOps branding.

This module creates visualizations matching the multi-metric analysis style.
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from typing import Dict, Any, List, Optional
import logging

from shared.metric_utils import get_metric_info

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def calculate_correlation_analysis(data: pd.DataFrame, x_metric: str, y_metric: str) -> Dict[str, float]:
    """Calculate correlation statistics between two metrics."""
    try:
        from scipy import stats
        import math
        
        # Remove NaN values
        clean_data = data[[x_metric, y_metric]].dropna()
        if len(clean_data) < 2:
            return None
            
        x = clean_data[x_metric].values
        y = clean_data[y_metric].values
        
        # Calculate correlation
        correlation, p_value = stats.pearsonr(x, y)
        
        # Calculate linear regression
        slope, intercept, r_value, _, _ = stats.linregress(x, y)
        
        # Check for invalid values
        if math.isnan(slope) or math.isinf(slope) or math.isnan(intercept) or math.isinf(intercept):
            logger.warning(f"Invalid regression values: slope={slope}, intercept={intercept}")
            return None
        
        return {
            'correlation': correlation,
            'p_value': p_value,
            'slope': slope,
            'intercept': intercept,
            'r_squared': r_value ** 2
        }
    except Exception as e:
        logger.warning(f"Could not calculate correlation: {e}")
        return None


def create_peerdas_performance_chart(
    data: pd.DataFrame,
    x_metric: str = 'blob_count',
    y_metric: str = 'data_available_time',
    title_suffix: str = "",
    agg_function: str = "mean",
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    show_attestation_deadline: bool = True,
    extrapolate_to_deadline: bool = False,
    show_trend_line: bool = True
) -> go.Figure:
    """
    Create PeerDAS performance chart matching multi-metric analysis style.
    
    Args:
        data: DataFrame with PeerDAS metrics
        x_metric: Column for x-axis (default: blob_count)
        y_metric: Column for y-axis (default: data_available_time)
        title_suffix: Additional text for plot title
        agg_function: Aggregation function used
        network: Network name
        time_range: Time range string
        metadata: Additional metadata
        show_attestation_deadline: Show 4s attestation deadline
        extrapolate_to_deadline: Extend trend lines to 4s
        show_trend_line: Show trend lines
        
    Returns:
        Plotly figure with ethPandaOps styling
    """
    if data.empty:
        logger.warning("Cannot create chart: empty data")
        return go.Figure()
    
    # Get metric info
    x_info = get_metric_info(x_metric)
    y_info = get_metric_info(y_metric)
    
    # Override for PeerDAS specific metrics
    if x_metric == 'blob_count':
        x_info = {'title': 'Blob Count', 'unit': ''}
    elif x_metric == 'custody_count':
        x_info = {'title': 'Custody Count', 'unit': 'columns'}
    if y_metric == 'data_available_time':
        y_info = {'title': 'Data Available Time', 'unit': 'ms'}
    
    # Create title
    agg_suffix = f" ({agg_function.title()})" if agg_function and agg_function != "mean" else ""
    main_title = f'{y_info["title"]} vs {x_info["title"]}{agg_suffix}{title_suffix}'
    
    # Create metadata parts for subtitle
    metadata_parts = []
    if network:
        metadata_parts.append(f"Network: {network}")
    if time_range:
        metadata_parts.append(f"Period: {time_range}")
    
    # Add data point count
    data_count = len(data)
    if metadata and 'total_blocks' in metadata:
        block_info = f"Points: {data_count:,} (from {metadata['total_blocks']:,} blocks)"
        if 'unique_nodes' in metadata:
            block_info += f", {metadata['unique_nodes']} nodes"
        metadata_parts.append(block_info)
    else:
        metadata_parts.append(f"Data Points: {data_count:,}")
    
    # Calculate correlation if we have enough data
    correlation_data = None
    if len(data) > 10 and show_trend_line:
        correlation_data = calculate_correlation_analysis(data, x_metric, y_metric)
        if correlation_data:
            metadata_parts.append(f"R²={correlation_data['r_squared']:.3f}")
    
    # Create figure
    fig = go.Figure()
    
    # Define colors matching multi-metric analysis
    colors = [
        '#0066CC',  # Strong blue
        '#006600',  # Dark green
        '#6600CC',  # Purple
        '#000066',  # Navy blue
        '#CC6600',  # Dark orange
        '#666666',  # Dark gray
        '#CC0066',  # Magenta
        '#003366'   # Dark teal
    ]
    
    # Check if we should group by client
    group_by_client = 'meta_client_name' in data.columns and data['meta_client_name'].nunique() > 1 and data['meta_client_name'].nunique() <= 10
    
    if group_by_client:
        # Group by client
        color_idx = 0
        for client in sorted(data['meta_client_name'].unique()):
            client_data = data[data['meta_client_name'] == client]
            
            fig.add_trace(
                go.Scatter(
                    x=client_data[x_metric],
                    y=client_data[y_metric],
                    mode='markers',
                    name=client,
                    marker=dict(
                        color=colors[color_idx % len(colors)],
                        size=8,
                        opacity=0.8
                    ),
                    hovertemplate=f'Client: {client}<br>' +
                                 f'{x_info["title"]}: %{{x:.0f}}<br>' +
                                 f'{y_info["title"]}: %{{y:.2f}} {y_info["unit"]}<extra></extra>'
                )
            )
            color_idx += 1
            
            # Add trend line for this client if enabled
            if show_trend_line and len(client_data) > 5:
                client_corr = calculate_correlation_analysis(client_data, x_metric, y_metric)
                if client_corr:
                    x_min = client_data[x_metric].min()
                    x_max = client_data[x_metric].max()
                    
                    # Extrapolate to 4s if enabled
                    if extrapolate_to_deadline and client_corr['slope'] != 0:
                        x_at_4s = (4000 - client_corr['intercept']) / client_corr['slope']
                        # Only use extrapolation if it's reasonable (not too far from data)
                        # Limit to max 3x the current max to prevent chart breaking
                        if x_at_4s > 0 and x_at_4s <= x_max * 3:
                            x_max = max(x_max, x_at_4s)
                        elif x_at_4s > x_max * 3:
                            logger.warning(f"Client {client} extrapolation would extend to {x_at_4s:.0f}, skipping")
                    
                    x_range = np.linspace(x_min, x_max, 100)
                    y_trend = client_corr['slope'] * x_range + client_corr['intercept']
                    
                    fig.add_trace(
                        go.Scatter(
                            x=x_range,
                            y=y_trend,
                            mode='lines',
                            name=f'{client} Trend',
                            line=dict(
                                color=colors[(color_idx - 1) % len(colors)],
                                width=1.5,
                                dash='dash'
                            ),
                            opacity=0.7,
                            showlegend=False,
                            hovertemplate=f'Trend: {client}<br>R² = {client_corr["r_squared"]:.3f}<extra></extra>'
                        )
                    )
    else:
        # Single series
        fig.add_trace(
            go.Scatter(
                x=data[x_metric],
                y=data[y_metric],
                mode='markers',
                name='Data Points',
                marker=dict(
                    color=colors[0],
                    size=8,
                    opacity=0.8
                ),
                hovertemplate=f'{x_info["title"]}: %{{x:.0f}} {x_info["unit"]}<br>' +
                             f'{y_info["title"]}: %{{y:.2f}} {y_info["unit"]}<extra></extra>'
            )
        )
        
        # Add overall trend line if enabled
        if show_trend_line and correlation_data:
            x_min = data[x_metric].min()
            x_max = data[x_metric].max()
            
            # Extrapolate to 4s if enabled
            deadline_intersection = None
            if extrapolate_to_deadline and correlation_data['slope'] != 0:
                x_at_4s = (4000 - correlation_data['intercept']) / correlation_data['slope']
                # Only use extrapolation if it's reasonable (not too far from data)
                # Limit to max 3x the current max to prevent chart breaking
                if x_at_4s > 0 and x_at_4s <= x_max * 3:
                    deadline_intersection = x_at_4s
                    x_max = max(x_max, x_at_4s)
                elif x_at_4s > x_max * 3:
                    logger.warning(f"Extrapolation to 4s would extend to {x_at_4s:.0f}, limiting to {x_max * 1.5:.0f}")
            
            x_range = np.linspace(x_min, x_max, 100)
            y_trend = correlation_data['slope'] * x_range + correlation_data['intercept']
            
            fig.add_trace(
                go.Scatter(
                    x=x_range,
                    y=y_trend,
                    mode='lines',
                    name='Trend Line',
                    line=dict(
                        color=colors[0],
                        width=2,
                        dash='dash'
                    ),
                    opacity=0.8,
                    showlegend=True,
                    hovertemplate=f'Trend<br>R² = {correlation_data["r_squared"]:.3f}<extra></extra>'
                )
            )
            
            # Add annotation for 4s intersection
            if deadline_intersection:
                fig.add_annotation(
                    x=deadline_intersection,
                    y=4000,
                    text=f"{int(deadline_intersection)} blobs",
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=2,
                    arrowcolor=colors[0],
                    bgcolor="rgba(255,255,255,0.8)",
                    bordercolor=colors[0],
                    borderwidth=1,
                    borderpad=6,
                    font=dict(size=12, color=colors[0])
                )
    
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
    
    # Update layout to match multi-metric analysis exactly
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
            x=1.02,
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
            title=f'{x_info["title"]} ({x_info["unit"]})' if x_info.get("unit") else x_info["title"],
            type='linear'  # Changed from category to allow trend lines to work properly
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            mirror=False,
            ticks='outside',
            title=f'{y_info["title"]} ({y_info["unit"]})',
            rangemode='tozero'
        ),
        margin=dict(r=200, t=120, l=80)
    )
    
    # Add 4s attestation deadline if requested
    if show_attestation_deadline and 'ms' in y_info.get("unit", ""):
        fig.add_hline(
            y=4000,
            line_dash="dot",
            line_color="red",
            line_width=2,
            opacity=0.7,
            annotation_text="4s Attestation Deadline",
            annotation_position="top left",
            annotation_font_size=10,
            annotation_font_color="red"
        )
        
        # Set minimum y-axis max to 5000ms for buffer
        y_data_max = data[y_metric].max() if not data[y_metric].isna().all() else 0
        y_axis_max = max(5000, y_data_max * 1.05)
        fig.update_yaxes(range=[0, y_axis_max])
    
    return fig


def create_node_classification_boxplot(
    data: pd.DataFrame,
    bucket_size: Optional[int] = None,
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    show_attestation_deadline: bool = True,
    grouping_dimensions: List[str] = None
) -> go.Figure:
    """
    Create box plot visualization comparing groups for each blob count.
    
    Args:
        data: DataFrame with raw PeerDAS data including node_class and consensus_implementation
        bucket_size: Optional bucket size for grouping blob counts
        network: Network name
        time_range: Time range string
        metadata: Additional metadata
        show_attestation_deadline: Show 4s attestation deadline
        grouping_dimensions: List of dimensions to group by ['node_class', 'consensus_client']
        
    Returns:
        Plotly figure with box plots grouped by blob count and selected dimensions
    """
    if data.empty:
        logger.warning("Cannot create box plot: empty data")
        return go.Figure()
    
    # Default to node_class if not specified
    if not grouping_dimensions:
        grouping_dimensions = ['node_class']
    
    # Convert milliseconds to seconds
    data = data.copy()
    data['data_available_time'] = data['data_available_time'] / 1000.0
    
    # Log initial data
    logger.info(f"Initial data shape: {data.shape}")
    logger.info(f"Initial blob counts: {sorted(data['blob_count'].unique())}")
    logger.info(f"Grouping dimensions: {grouping_dimensions}")
    
    # Create grouping column based on selected dimensions
    if len(grouping_dimensions) == 1:
        # Single dimension grouping
        if grouping_dimensions[0] == 'consensus_client':
            data['group'] = data['consensus_implementation']
        else:  # node_class
            data['group'] = data['node_class']
    else:
        # Multiple dimensions - combine them
        if 'node_class' in grouping_dimensions and 'consensus_client' in grouping_dimensions:
            data['group'] = data['node_class'] + ' / ' + data['consensus_implementation']
        else:
            data['group'] = data[grouping_dimensions[0]]  # Fallback
    
    # Apply bucketing if requested
    if bucket_size and bucket_size > 1:
        # Create bucket labels - use clear format to avoid date interpretation
        data['blob_bucket'] = ((data['blob_count'] - 1) // bucket_size) * bucket_size + 1
        data['blob_bucket_label'] = data['blob_bucket'].apply(
            lambda x: f"[{int(x)}-{int(x+bucket_size-1)}]"
        )
        logger.info(f"After bucketing - unique bucket labels: {data['blob_bucket_label'].unique()}")
        group_col = 'blob_bucket_label'
        x_title = f'Blob Count (buckets of {bucket_size})'
    else:
        data['blob_bucket_label'] = data['blob_count'].apply(lambda x: str(int(x)))
        group_col = 'blob_bucket_label'
        x_title = 'Blob Count'
    
    # Generate colors for groups - use a larger palette for flexibility
    import plotly.express as px
    unique_groups = sorted(data['group'].unique())
    
    # Define colors based on grouping type
    if grouping_dimensions == ['node_class']:
        # Use specific colors for node classes
        group_colors = {
            'non-validating': '#1E88E5',      # Blue
            'validating-standard': '#43A047',  # Green
            'supernode': '#E53935'             # Red
        }
        group_names = {
            'non-validating': 'Non-Validating (8 columns)',
            'validating-standard': 'Validating Standard (9-127 columns)',
            'supernode': 'Supernode (128 columns)'
        }
    else:
        # Use a color palette for other groupings
        colors = px.colors.qualitative.Plotly + px.colors.qualitative.Bold
        group_colors = {group: colors[i % len(colors)] for i, group in enumerate(unique_groups)}
        group_names = {group: group for group in unique_groups}
    
    # Create figure
    fig = go.Figure()
    
    # Get unique blob buckets and sort them
    # Handle both "[X-Y]" format and single number format
    def sort_key(x):
        if '[' in x and '-' in x:
            # Extract first number from "[X-Y]" format
            return int(x.strip('[]').split('-')[0])
        else:
            return int(x)
    
    unique_buckets = sorted(data[group_col].unique(), key=sort_key)
    
    # Log bucket information for debugging
    logger.info(f"Bucket size: {bucket_size}")
    logger.info(f"Unique blob counts: {sorted(data['blob_count'].unique())}")
    logger.info(f"Created buckets: {unique_buckets}")
    logger.info(f"Unique groups: {unique_groups}")
    
    # Create box plots for each group
    for group in unique_groups:
        group_data = data[data['group'] == group]
        
        if not group_data.empty:
            logger.info(f"Group {group}: {len(group_data)} data points")
            logger.info(f"  Buckets present: {sorted(group_data[group_col].unique(), key=sort_key)}")
            
            # Get color and display name
            color = group_colors.get(group, '#808080')
            display_name = group_names.get(group, group)
            
            # Create box plot trace for this group
            fig.add_trace(
                go.Box(
                    x=group_data[group_col],
                    y=group_data['data_available_time'],
                    name=display_name,
                    marker_color=color,
                    boxmean='sd',  # Show mean and standard deviation
                    hovertemplate='<b>%{x}</b><br>' +
                                 f'{display_name}<br>' +
                                 'Q1: %{q1:.2f}s<br>' +
                                 'Median: %{median:.2f}s<br>' +
                                 'Q3: %{q3:.2f}s<br>' +
                                 'Mean: %{mean:.2f}s<br>' +
                                 'SD: %{sd:.2f}s<extra></extra>'
                )
            )
        else:
            logger.warning(f"No data for group: {group}")
    
    # Create title based on grouping dimensions
    if grouping_dimensions == ['node_class']:
        main_title = 'Performance by Node Classification'
    elif grouping_dimensions == ['consensus_client']:
        main_title = 'Performance by Consensus Client'
    elif len(grouping_dimensions) == 2:
        main_title = 'Performance by Node Class and Client'
    else:
        main_title = 'Performance Analysis'
    
    # Create metadata parts for subtitle
    metadata_parts = []
    if network:
        metadata_parts.append(f"Network: {network}")
    if time_range:
        metadata_parts.append(f"Period: {time_range}")
    
    # Add data stats
    if metadata:
        if 'total_blocks' in metadata:
            metadata_parts.append(f"Blocks: {metadata['total_blocks']:,}")
        if 'unique_nodes' in metadata:
            metadata_parts.append(f"Nodes: {metadata['unique_nodes']}")
    
    # Count samples per group
    group_counts = data['group'].value_counts()
    # Limit to showing top 5 groups if too many
    if len(group_counts) > 5:
        top_groups = group_counts.head(5)
        samples_info = ", ".join([f"{group_names.get(k, k)}: {v:,}" for k, v in top_groups.items()])
        samples_info += f", and {len(group_counts) - 5} more groups"
    else:
        samples_info = ", ".join([f"{group_names.get(k, k)}: {v:,}" for k, v in group_counts.items()])
    if samples_info:
        metadata_parts.append(f"Samples: {samples_info}")
    
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
    
    # Update layout
    fig.update_layout(
        title=main_title,
        height=600,
        showlegend=True,
        hovermode='closest',
        boxmode='group',  # Group boxes for each blob count
        legend=dict(
            itemclick="toggle",
            itemdoubleclick="toggleothers",
            orientation="v",
            yanchor="top",
            y=0.95,
            xanchor="left",
            x=1.02,
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
            title=x_title,
            type='category',  # Explicitly set as categorical
            categoryorder='array',
            categoryarray=unique_buckets
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            mirror=False,
            ticks='outside',
            title='Data Available Time (seconds)',
            rangemode='tozero',
            tickformat='.1f',
            ticksuffix='s'
        ),
        margin=dict(r=250, t=120, l=80)
    )
    
    # Add 4s attestation deadline if requested
    if show_attestation_deadline:
        fig.add_hline(
            y=4.0,  # 4 seconds
            line_dash="dot",
            line_color="red",
            line_width=2,
            opacity=0.7,
            annotation_text="4s Attestation Deadline",
            annotation_position="top left",
            annotation_font_size=10,
            annotation_font_color="red"
        )
        
        # Set minimum y-axis max to 5s for buffer  
        y_data_max = data['data_available_time'].max() if not data['data_available_time'].isna().all() else 0
        y_axis_max = max(5.0, y_data_max * 1.05)
        fig.update_yaxes(range=[0, y_axis_max])
    
    return fig