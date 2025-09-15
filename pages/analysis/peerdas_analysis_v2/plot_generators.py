"""
Plot generation for PeerDAS Analysis V2 with ethPandaOps branding.

This module creates visualizations for head correctness analysis,
showing attestation accuracy percentages (for proposed blocks, including
reorged ones) bucketed by blob count. Charts render only from real 
grouped data computed by ClickHouse.
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, Any, Optional
import logging
from scipy import stats

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_metric_label(metadata: Dict[str, Any] = None) -> str:
    """Get the metric label based on view mode (Correctness or Incorrectness)."""
    if metadata and metadata.get('view_mode') == 'incorrect':
        return 'Incorrectness'
    return 'Correctness'


def _get_legend_title(data: pd.DataFrame) -> str:
    """Get the legend title based on data type (Proposed by or Attested by)."""
    if 'data_type' in data.columns and len(data) > 0:
        # Check if all non-null values are 'attester'
        unique_types = data['data_type'].dropna().unique()
        if len(unique_types) == 1 and unique_types[0] == 'attester':
            return 'Attested by'
    return 'Proposed by'


def _get_smart_colors(group_keys: list, grouping_dimension: str) -> Dict[str, str]:
    """
    Generate smart color assignments based on grouping hierarchy.
    
    For hierarchical groupings (e.g., CL+NodeType), assigns base colors to primary
    components and shade variations to secondary components.
    
    Args:
        group_keys: List of unique group keys
        grouping_dimension: The grouping dimension being used
        
    Returns:
        Dictionary mapping group_key to color hex code
    """
    # Base color palette - diverse, visually distinct colors
    base_colors = [
        '#FF6B6B',  # Coral red
        '#FFD93D',  # Bright yellow
        '#6C5CE7',  # Purple
        '#4ECDC4',  # Teal
        '#FF6FB5',  # Hot pink
        '#95E77E',  # Lime green
        '#FFA500',  # Orange
        '#45B7D1',  # Sky blue
        '#B19CD9',  # Lavender
        '#FFAB91',  # Peach
        '#81C784',  # Green
        '#F06292',  # Pink
        '#A1887F',  # Brown
        '#64B5F6',  # Light blue
        '#FFB74D'   # Amber
    ]
    
    color_map = {}
    
    # Simple groupings - just assign colors directly
    if grouping_dimension in ['none', 'node_type', 'cl_client', 'el_client', 'block_building']:
        for idx, key in enumerate(sorted(group_keys)):
            color_map[key] = base_colors[idx % len(base_colors)]
        return color_map
    
    # Hierarchical groupings - parse and assign colors intelligently
    if grouping_dimension in ['cl_el_combined', 'cl_node_type', 'el_node_type', 'node_type_mev', 'cl_node_type_mev']:
        # Parse keys to find primary components
        primary_components = {}
        
        for key in group_keys:
            if not key or key == 'unknown':
                primary_components[key] = ['unknown']
                continue
                
            # Parse based on grouping type
            if grouping_dimension == 'cl_el_combined':
                # Format: "lighthouse-geth"
                parts = key.split('-')
                if len(parts) >= 1:
                    primary = parts[0]  # CL client
                    primary_components.setdefault(primary, []).append(key)
            
            elif grouping_dimension == 'cl_node_type':
                # Format: "lighthouse-supernode"
                parts = key.split('-')
                if len(parts) >= 1:
                    primary = parts[0]  # CL client
                    primary_components.setdefault(primary, []).append(key)

            elif grouping_dimension == 'el_node_type':
                # Format: "geth-supernode"
                parts = key.split('-')
                if len(parts) >= 1:
                    primary = parts[0]  # EL client
                    primary_components.setdefault(primary, []).append(key)

            elif grouping_dimension == 'node_type_mev':
                # Format: "supernode-mev" or "regular-non-mev"
                parts = key.split('-')
                if len(parts) >= 1:
                    primary = parts[0]  # Node type
                    primary_components.setdefault(primary, []).append(key)
            
            elif grouping_dimension == 'cl_node_type_mev':
                # Format: "lighthouse-supernode-mev"
                parts = key.split('-')
                if len(parts) >= 1:
                    primary = parts[0]  # CL client
                    primary_components.setdefault(primary, []).append(key)
        
        # Assign base colors to primary components
        primary_colors = {}
        for idx, primary in enumerate(sorted(primary_components.keys())):
            primary_colors[primary] = base_colors[idx % len(base_colors)]
        
        # Create shade variations for each primary's group
        for primary, keys in primary_components.items():
            base_color = primary_colors[primary]
            
            if len(keys) == 1:
                # Only one variant, use base color
                color_map[keys[0]] = base_color
            else:
                # Multiple variants, create shades
                # Convert hex to RGB for manipulation
                base_rgb = tuple(int(base_color[i:i+2], 16) for i in (1, 3, 5))
                
                for idx, key in enumerate(sorted(keys)):
                    if idx == 0:
                        # First variant gets the base color
                        color_map[key] = base_color
                    else:
                        # Create variations by adjusting brightness
                        # Alternate between darker and lighter
                        if idx % 2 == 1:
                            # Darker variant
                            factor = 0.7 + (0.15 * ((idx - 1) // 2))  # 0.7, 0.85
                            new_rgb = tuple(int(c * factor) for c in base_rgb)
                        else:
                            # Lighter variant
                            factor = 0.15 * (idx // 2)  # 0.15, 0.30
                            new_rgb = tuple(min(255, int(c + (255 - c) * factor)) for c in base_rgb)
                        
                        # Convert back to hex
                        color_map[key] = '#{:02x}{:02x}{:02x}'.format(*new_rgb)
    
    else:
        # Fallback for unknown grouping dimensions
        for idx, key in enumerate(sorted(group_keys)):
            color_map[key] = base_colors[idx % len(base_colors)]
    
    return color_map


def _format_filter_description(filter_type: str, filters: Dict[str, Any]) -> str:
    """Format filter information for display."""
    if not filters:
        return f"{filter_type} by All nodes"
    
    parts = []
    
    # Node type
    node_type = filters.get('node_type')
    if node_type == 'supernode':
        parts.append('Supernodes')
    elif node_type == 'regular':
        parts.append('Regular nodes')
    else:
        parts.append('Supernodes + Regular nodes')
    
    # CL clients
    cl_filter = filters.get('cl_filter')
    if cl_filter and len(cl_filter) < 6:  # Not all CL clients
        cl_str = '+'.join([cl.title() for cl in cl_filter])
        parts.append(f"({cl_str} CL)")
    else:
        parts.append("(All CLs)")
    
    # EL clients  
    el_filter = filters.get('el_filter')
    if el_filter and len(el_filter) < 6:  # Not all EL clients
        el_str = '+'.join([el.title() for el in el_filter])
        parts.append(f"({el_str} EL)")
    else:
        parts.append("(All ELs)")
    
    return f"{filter_type} " + ' '.join(parts)


def calculate_correlation_analysis(data: pd.DataFrame, x_metric: str, y_metric: str) -> Optional[Dict[str, float]]:
    """Calculate correlation statistics between two metrics."""
    try:
        from scipy import stats
        import math

        clean = data[[x_metric, y_metric]].dropna()
        if len(clean) < 2:
            return None

        x = clean[x_metric].values
        y = clean[y_metric].values

        correlation, p_value = stats.pearsonr(x, y)
        slope, intercept, r_value, _, _ = stats.linregress(x, y)
        if any(map(lambda v: math.isnan(v) or math.isinf(v), [slope, intercept])):
            return None

        return {
            'correlation': correlation,
            'p_value': p_value,
            'slope': slope,
            'intercept': intercept,
            'r_squared': r_value ** 2
        }
    except Exception as e:
        logger.debug(f"Correlation unavailable: {e}")
        return None


def create_head_correctness_chart(
    data: pd.DataFrame,
    num_buckets: int = 6,
    title_suffix: str = "",
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    show_trend_line: bool = True,
    aggregation_method: str = 'p95',
    grouping_dimension: str = 'node_type',
    proposer_filters: Dict[str, Any] = None,
    attester_filters: Dict[str, Any] = None
) -> go.Figure:
    """Create head correctness chart showing aggregated accuracy percentage by blob count buckets with grouping."""
    if data.empty:
        return go.Figure()

    if 'blob_count' not in data.columns or 'head_correctness_pct' not in data.columns:
        logger.error("Missing required columns for chart: blob_count, head_correctness_pct")
        return go.Figure()

    df = data.copy()
    
    # Add grouping if not present
    if 'group_key' not in df.columns:
        df['group_key'] = 'all'
        df['group_label'] = 'All Nodes'
    if 'group_label' not in df.columns:
        df['group_label'] = df['group_key']
    
    # Calculate bucket size from number of buckets
    max_blobs = int(df['blob_count'].max())
    min_blobs = int(df['blob_count'].min())
    blob_range = max_blobs - min_blobs + 1
    
    # Apply bucketing if requested
    if num_buckets == 1:
        # Special case: single bucket for all blob counts
        df['blob_bucket_label'] = 'All'
        x_col = 'blob_bucket_label'
        x_order = ['All']
        x_title = 'All Blob Counts'
    elif num_buckets and num_buckets > 1:
        # If we have fewer unique blob counts than requested buckets, show individual counts
        if blob_range <= num_buckets:
            x_col = 'blob_count'
            x_order = sorted(df['blob_count'].dropna().unique())
            x_title = 'Blob Count'
        else:
            # Create exactly num_buckets buckets across the blob range
            bucket_width = (max_blobs - min_blobs + 1) / num_buckets
            edges = [min_blobs + i * bucket_width for i in range(num_buckets + 1)]
            edges[-1] = max_blobs + 1  # Ensure last edge includes max value
            
            df['blob_bucket'] = pd.cut(df['blob_count'], bins=edges, include_lowest=True, right=False)
            df['blob_bucket_label'] = df['blob_bucket'].apply(
                lambda x: f"{int(np.floor(x.left))}-{int(np.ceil(x.right)-1)}" if pd.notna(x) else "Unknown"
            )
            x_col = 'blob_bucket_label'
            x_order = sorted(df['blob_bucket_label'].dropna().unique(), 
                            key=lambda s: int(str(s).split('-')[0]) if '-' in str(s) else 0)
            x_title = 'Blob Count (Bucketed)'
    else:
        x_col = 'blob_count'
        x_order = sorted(df['blob_count'].dropna().unique())
        x_title = 'Blob Count'
    
    fig = go.Figure()
    
    # Get smart color assignments
    unique_groups = df['group_key'].unique()
    color_map = _get_smart_colors(list(unique_groups), grouping_dimension)
    
    # Create traces for each group
    for g in sorted(df['group_key'].unique()):
        gdf = df[df['group_key'] == g]
        glabel = gdf['group_label'].iloc[0] if not gdf.empty else str(g)
        color = color_map.get(g, '#999999')  # Fallback to gray if not found
        
        # Calculate aggregation for each x value based on selected method
        if aggregation_method == 'mean':
            agg_func = 'mean'
        elif aggregation_method == 'median':
            agg_func = 'median'
        elif aggregation_method == 'min':
            agg_func = 'min'
        elif aggregation_method == 'max':
            agg_func = 'max'
        elif aggregation_method.startswith('p'):
            # Extract percentile value (p25, p50, p75, p90, p95, p99)
            percentile = int(aggregation_method[1:]) / 100.0
            agg_func = lambda x: x.quantile(percentile)
        else:
            # Default to p95
            agg_func = lambda x: x.quantile(0.95)
        
        agg = gdf.groupby(x_col).agg({
            'head_correctness_pct': agg_func,
            'slot': 'nunique'  # Count unique slots, not rows
        }).reset_index()
        agg.rename(columns={'slot': 'sample_count'}, inplace=True)
        
        # Sort by x_order to ensure proper line connection
        agg['sort_key'] = agg[x_col].apply(
            lambda x: x_order.index(x) if x in x_order else -1
        )
        agg = agg[agg['sort_key'] >= 0].sort_values('sort_key')
        
        # Format aggregation method for display
        agg_display = {
            'mean': 'Mean',
            'median': 'Median',
            'min': 'Min',
            'max': 'Max',
            'p25': '25th %ile',
            'p50': '50th %ile',
            'p75': '75th %ile',
            'p90': '90th %ile',
            'p95': '95th %ile',
            'p99': '99th %ile'
        }.get(aggregation_method, aggregation_method.upper())
        
        if not agg.empty:
            fig.add_trace(
                go.Scatter(
                    x=agg[x_col],
                    y=agg['head_correctness_pct'],
                    mode='lines+markers',
                    name=f'{glabel} ({agg_display})',
                    line=dict(color=color, width=2),
                    marker=dict(size=6),
                    hovertemplate=f'<b>{glabel}</b><br>Blob: %{{x}}<br>{agg_display} Head Correctness: %{{y:.1f}}%<br>Samples: %{{customdata}}<extra></extra>',
                    customdata=agg['sample_count']
                )
            )

            # Add sample count annotations below each point
            for idx, row in agg.iterrows():
                fig.add_annotation(
                    x=row[x_col],
                    y=0,
                    text=f"({row['sample_count']:,} slots)",
                    showarrow=False,
                    font=dict(size=10, color=color),
                    yshift=-20,
                    opacity=0.8,
                    xref='x',
                    yref='paper'
                )

    # Skip trend line for multi-group charts as it becomes too cluttered
    # Trend lines only make sense for single-group analysis

    # Build compact subtitle
    subtitle_parts = []
    
    # First line: Network, time range, and slots
    if network:
        subtitle_parts.append(f'<b>{network}</b>')
    if time_range:
        subtitle_parts.append(time_range)
    if metadata and 'total_slots' in metadata:
        subtitle_parts.append(f'{metadata["total_slots"]:,} slots')
    
    subtitle_line1 = '  •  '.join(subtitle_parts) if subtitle_parts else None
    
    # Second line: Filter descriptions (more detailed)
    filter_parts = []
    if proposer_filters:
        filter_desc = _format_filter_description("Proposed by", proposer_filters)
        filter_parts.append(filter_desc)
    if attester_filters:
        filter_desc = _format_filter_description("Attested by", attester_filters)
        filter_parts.append(filter_desc)
    
    subtitle_line2 = '  |  '.join(filter_parts) if filter_parts else None
    
    # Set title based on grouping and aggregation method
    group_names = {
        'node_type': 'Node Type',
        'cl_client': 'CL Client',
        'el_client': 'EL Client',
        'cl_el_combined': 'CL+EL Combination',
        'cl_node_type': 'CL+Node Type',
        'el_node_type': 'EL+Node Type'
    }
    gname = group_names.get(grouping_dimension, grouping_dimension)
    
    # Get display name for aggregation method
    agg_title = {
        'mean': 'Mean',
        'median': 'Median',
        'min': 'Min',
        'max': 'Max',
        'p25': '25th Percentile',
        'p50': '50th Percentile',
        'p75': '75th Percentile',
        'p90': '90th Percentile',
        'p95': '95th Percentile',
        'p99': '99th Percentile'
    }.get(aggregation_method, aggregation_method.upper())
    
    metric_label = _get_metric_label(metadata)
    main_title = f'Head {metric_label} ({agg_title}) vs. Blob Count by {gname}'
    if title_suffix:
        main_title += f' — {title_suffix}'
    
    # Combine subtitle lines
    subtitle_html = []
    if subtitle_line1:
        subtitle_html.append(f'<span style="font-size: 12px; color: #666;">{subtitle_line1}</span>')
    if subtitle_line2:
        subtitle_html.append(f'<span style="font-size: 11px; color: #888;">{subtitle_line2}</span>')
    
    if subtitle_html:
        main_title = main_title + '<br>' + '<br>'.join(subtitle_html)

    is_bucketed = num_buckets and num_buckets >= 1
    
    # Determine legend title based on data type
    legend_title = _get_legend_title(data)
    
    fig.update_layout(
        title=dict(
            text=main_title,
            x=0,
            xanchor='left',
            font=dict(size=16)
        ),
        height=600,
        showlegend=True,
        hovermode='closest',
        legend=dict(title=dict(text=legend_title), itemclick='toggle', itemdoubleclick='toggleothers', orientation='v', yanchor='top', y=0.95, xanchor='left', x=1.02, bgcolor='rgba(255,255,255,0.9)', bordercolor='rgba(0,0,0,0.3)', borderwidth=1),
        xaxis=dict(showline=True, linewidth=1, linecolor='black', ticks='outside', title=x_title, type='category' if is_bucketed else 'linear'),
        yaxis=dict(showline=True, linewidth=1, linecolor='black', ticks='outside', title=f'Head {metric_label} (%)', range=[0, 100]),
        margin=dict(r=200, t=120, l=80, b=80)
    )

    fig.add_layout_image(dict(source='https://ethpandaops.io/img/logo-slim.png', xref='paper', yref='paper', x=0.02, y=0.98, sizex=0.08, sizey=0.08, xanchor='left', yanchor='top'))
    return fig


def create_head_correctness_boxplot(
    data: pd.DataFrame,
    num_buckets: Optional[int] = None,
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    grouping_dimension: str = 'node_type',
    proposer_filters: Dict[str, Any] = None,
    attester_filters: Dict[str, Any] = None,
    title_suffix: str = ""
) -> go.Figure:
    """Create grouped box plot using real grouped data (no synthetic expansion)."""
    if data.empty:
        return go.Figure()

    if 'blob_count' not in data.columns or 'head_correctness_pct' not in data.columns:
        logger.error("Missing required columns for boxplot: blob_count, head_correctness_pct")
        return go.Figure()

    df = data.copy()
    
    # Debug logging to see what columns we have
    logger.info(f"Boxplot received columns: {df.columns.tolist()}")
    if 'group_key' in df.columns and len(df) > 0:
        sample_keys = df['group_key'].unique()[:3].tolist()
        logger.info(f"Sample group_keys: {sample_keys}")
    if 'group_label' in df.columns and len(df) > 0:
        sample_labels = df['group_label'].unique()[:3].tolist()
        logger.info(f"Sample group_labels: {sample_labels}")
    
    if 'group_key' not in df.columns:
        df['group_key'] = 'all'
        df['group_label'] = 'All Nodes'
    if 'group_label' not in df.columns:
        logger.warning("group_label column missing, using group_key as fallback")
        df['group_label'] = df['group_key']

    # Calculate bucket size from number of buckets
    max_blobs = int(df['blob_count'].max()) if len(df) else 0
    min_blobs = int(df['blob_count'].min()) if len(df) else 0
    blob_range = max_blobs - min_blobs + 1
    
    if num_buckets == 1:
        # Special case: single bucket for all blob counts
        df['blob_bucket_label'] = 'All'
        x_col = 'blob_bucket_label'
        x_order = ['All']
    elif num_buckets and num_buckets > 1:
        # If we have fewer unique blob counts than requested buckets, show individual counts
        if blob_range <= num_buckets:
            x_col = 'blob_count'
            x_order = sorted(df['blob_count'].dropna().unique())
        else:
            # Create exactly num_buckets buckets across the blob range
            bucket_width = (max_blobs - min_blobs + 1) / num_buckets
            edges = [min_blobs + i * bucket_width for i in range(num_buckets + 1)]
            edges[-1] = max_blobs + 1  # Ensure last edge includes max value
            
            df['blob_bucket'] = pd.cut(df['blob_count'], bins=edges, include_lowest=True, right=False)
            df['blob_bucket_label'] = df['blob_bucket'].apply(
                lambda x: f"{int(np.floor(x.left))}-{int(np.ceil(x.right)-1)}" if pd.notna(x) else "Unknown"
            )
            x_col = 'blob_bucket_label'
            x_order = sorted(df['blob_bucket_label'].dropna().unique(), 
                            key=lambda s: int(str(s).split('-')[0]) if '-' in str(s) else 0)
    else:
        x_col = 'blob_count'
        x_order = sorted(df['blob_count'].dropna().unique())

    fig = go.Figure()
    
    # Get smart color assignments
    unique_groups = df['group_key'].unique()
    color_map = _get_smart_colors(list(unique_groups), grouping_dimension)
    
    # Track unique slots per bucket (across all groups)
    # Calculate from actual data to ensure accuracy with grouped data
    unique_slots_per_bucket = {}
    for x_val in x_order:
        bucket_data = df[df[x_col] == x_val]
        if not bucket_data.empty:
            # Ensure we have the slot column and count unique values properly
            if 'slot' not in bucket_data.columns:
                logger.error(f"Missing 'slot' column in data for bucket {x_val}")
                unique_slots_per_bucket[x_val] = len(bucket_data)
            else:
                # Count unique slots in this bucket (regardless of how many groups we have)
                unique_count = bucket_data['slot'].nunique()
                unique_slots_per_bucket[x_val] = unique_count

    for g in sorted(df['group_key'].unique()):
        gdf = df[df['group_key'] == g]
        # Get the group label if it exists, otherwise format the key
        if 'group_label' in gdf.columns and not gdf.empty:
            glabel = gdf['group_label'].iloc[0]
        else:
            # Format the raw key if label is missing
            if str(g) == 'mev':
                glabel = 'Via MEV Relay'
            elif str(g) == 'non-mev':
                glabel = 'Locally Built'
            elif '-mev' in str(g) or '-non-mev' in str(g):
                if str(g).endswith('-non-mev'):
                    base = str(g)[:-8]  # Remove '-non-mev'
                    if base == 'supernode' or base == 'regular':
                        node_label = 'Supernode' if base == 'supernode' else 'Regular'
                        glabel = f"{node_label} (Locally built)"
                    elif '-' in base:
                        parts = base.split('-')
                        if len(parts) == 2:
                            cl, node_type = parts
                            node_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                            glabel = f"{cl.title()} {node_label} (Locally built)"
                        else:
                            glabel = str(g)
                    else:
                        glabel = str(g)
                elif str(g).endswith('-mev'):
                    base = str(g)[:-4]  # Remove '-mev'
                    if base == 'supernode' or base == 'regular':
                        node_label = 'Supernode' if base == 'supernode' else 'Regular'
                        glabel = f"{node_label} (Via MEV)"
                    elif '-' in base:
                        parts = base.split('-')
                        if len(parts) == 2:
                            cl, node_type = parts
                            node_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                            glabel = f"{cl.title()} {node_label} (Via MEV)"
                        else:
                            glabel = str(g)
                    else:
                        glabel = str(g)
                else:
                    glabel = str(g)
            else:
                glabel = str(g).replace('supernode', 'Supernode').replace('regular', 'Regular').replace('-', ' + ').title()

        color = color_map.get(g, '#999999')  # Use smart color map

        # No longer need to track per-group sample counts

        fig.add_trace(
            go.Box(
                x=gdf[x_col],
                y=gdf['head_correctness_pct'],
                name=glabel,
                marker_color=color,
                boxmean='sd',
                hovertemplate=f'<b>{glabel}</b><br><b>Blob Count</b>: %{{x}}<br>Head Correctness: %{{y:.1f}}%<extra></extra>',
                offsetgroup=str(g)
            )
        )

    # Add sample count annotations with true unique slot counts
    for x_val in x_order:
        if x_val in unique_slots_per_bucket:
            fig.add_annotation(
                x=x_val,
                y=-0.12,  # Position below the plot area
                text=f"({unique_slots_per_bucket[x_val]:,} slots)",
                showarrow=False,
                font=dict(size=10, color='#333'),
                xref='x',
                yref='paper'
            )

    group_names = {'node_type': 'Node Type', 'cl_client': 'CL Client', 'el_client': 'EL Client', 'cl_el_combined': 'CL+EL Combination', 'cl_node_type': 'CL+Node Type', 'el_node_type': 'EL+Node Type'}
    metric_label = _get_metric_label(metadata)
    gname = group_names.get(grouping_dimension, grouping_dimension)
    title = f'Head {metric_label} Distribution by {gname}'
    if title_suffix:
        title += f' — {title_suffix}'

    # Build compact subtitle
    subtitle_parts = []
    
    # First line: Network, time range, and slots
    if network:
        subtitle_parts.append(f'<b>{network}</b>')
    if time_range:
        subtitle_parts.append(time_range)
    if metadata and 'total_slots' in metadata:
        subtitle_parts.append(f'{metadata["total_slots"]:,} slots')
    
    subtitle_line1 = '  •  '.join(subtitle_parts) if subtitle_parts else None
    
    # Second line: Filter descriptions (more detailed)
    filter_parts = []
    if proposer_filters:
        filter_desc = _format_filter_description("Proposed by", proposer_filters)
        filter_parts.append(filter_desc)
    if attester_filters:
        filter_desc = _format_filter_description("Attested by", attester_filters)
        filter_parts.append(filter_desc)
    
    subtitle_line2 = '  |  '.join(filter_parts) if filter_parts else None

    # Build title with integrated subtitle
    subtitle_html = []
    if subtitle_line1:
        subtitle_html.append(f'<span style="font-size: 12px; color: #666;">{subtitle_line1}</span>')
    if subtitle_line2:
        subtitle_html.append(f'<span style="font-size: 11px; color: #888;">{subtitle_line2}</span>')
    
    if subtitle_html:
        title = title + '<br>' + '<br>'.join(subtitle_html)
    
    # Determine legend title based on data type
    legend_title = _get_legend_title(data)
    
    fig.update_layout(
        title=dict(
            text=title,
            x=0,
            xanchor='left',
            font=dict(size=16)
        ),
        height=600,
        showlegend=True,
        hovermode='closest',
        legend=dict(title=dict(text=legend_title), itemclick='toggle', itemdoubleclick='toggleothers', orientation='v', yanchor='top', y=0.95, xanchor='left', x=1.02, bgcolor='rgba(255,255,255,0.9)', bordercolor='rgba(0,0,0,0.3)', borderwidth=1),
        xaxis=dict(showline=True, linewidth=1, linecolor='black', ticks='outside', title=dict(text='All Blob Counts' if num_buckets == 1 else ('Blob Count Buckets' if num_buckets and num_buckets > 1 else 'Blob Count'), standoff=25), categoryorder='array', categoryarray=x_order),
        yaxis=dict(showline=True, linewidth=1, linecolor='black', ticks='outside', title=f'Head {metric_label} (%)', range=[0, 100]),
        margin=dict(r=200, t=120, l=80, b=100),
        boxmode='group'
    )

    fig.add_layout_image(dict(source='https://ethpandaops.io/img/logo-slim.png', xref='paper', yref='paper', x=0.02, y=0.98, sizex=0.08, sizey=0.08, xanchor='left', yanchor='top'))
    return fig


def create_head_correctness_violin(
    data: pd.DataFrame,
    num_buckets: Optional[int] = None,
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    grouping_dimension: str = 'node_type',
    proposer_filters: Dict[str, Any] = None,
    attester_filters: Dict[str, Any] = None,
    title_suffix: str = ""
) -> go.Figure:
    """Create violin plot showing distribution of head correctness by blob count."""
    if data.empty:
        return go.Figure()
    
    if 'blob_count' not in data.columns or 'head_correctness_pct' not in data.columns:
        logger.error("Missing required columns for violin plot: blob_count, head_correctness_pct")
        return go.Figure()
    
    df = data.copy()
    
    # Add grouping if not present
    if 'group_key' not in df.columns:
        df['group_key'] = 'all'
        df['group_label'] = 'All Nodes'
    if 'group_label' not in df.columns:
        df['group_label'] = df['group_key']
    
    # Calculate bucket size from number of buckets
    max_blobs = int(df['blob_count'].max())
    min_blobs = int(df['blob_count'].min())
    blob_range = max_blobs - min_blobs + 1
    
    # Apply bucketing if requested
    if num_buckets == 1:
        # Special case: single bucket for all blob counts
        df['blob_bucket_label'] = 'All'
        x_col = 'blob_bucket_label'
        x_order = ['All']
    elif num_buckets and num_buckets > 1:
        # Create exactly num_buckets buckets by using linspace to generate edges
        edges = np.linspace(min_blobs, max_blobs + 1, num_buckets + 1)
        # Adjust edges to be integers and ensure no overlap
        edges = np.unique(np.floor(edges).astype(int))
        df['blob_bucket'] = pd.cut(df['blob_count'], bins=edges, include_lowest=True, right=False)
        df['blob_bucket_label'] = df['blob_bucket'].apply(
            lambda x: f"{int(x.left)}-{int(x.right-1)}" if pd.notna(x) else "Unknown"
        )
        x_col = 'blob_bucket_label'
        x_order = sorted(df['blob_bucket_label'].dropna().unique(), 
                        key=lambda s: int(str(s).split('-')[0]) if '-' in str(s) else 0)
    else:
        x_col = 'blob_count'
        x_order = sorted(df['blob_count'].dropna().unique())
    
    fig = go.Figure()

    # Get smart color assignments
    unique_groups = df['group_key'].unique()
    color_map = _get_smart_colors(list(unique_groups), grouping_dimension)

    # Track unique slots per bucket (across all groups)
    # Calculate from actual data to ensure accuracy with grouped data
    unique_slots_per_bucket = {}
    for x_val in x_order:
        bucket_data = df[df[x_col] == x_val]
        if not bucket_data.empty:
            # Ensure we have the slot column and count unique values properly
            if 'slot' not in bucket_data.columns:
                logger.error(f"Missing 'slot' column in data for bucket {x_val}")
                unique_slots_per_bucket[x_val] = len(bucket_data)
            else:
                # Count unique slots in this bucket (regardless of how many groups we have)
                unique_count = bucket_data['slot'].nunique()
                unique_slots_per_bucket[x_val] = unique_count

    for g in sorted(df['group_key'].unique()):
        gdf = df[df['group_key'] == g]
        # Get the group label if it exists, otherwise format the key
        if 'group_label' in gdf.columns and not gdf.empty:
            glabel = gdf['group_label'].iloc[0]
        else:
            # Format the raw key if label is missing
            if '-mev' in str(g) or '-non-mev' in str(g):
                parts = str(g).split('-')
                if len(parts) == 2:
                    node_type, mev_status = parts
                    node_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                    mev_label = 'Via MEV' if mev_status == 'mev' else 'Locally built'
                    glabel = f"{node_label} ({mev_label})"
                elif len(parts) == 3:
                    cl, node_type, mev_status = parts
                    node_label = 'Supernode' if node_type == 'supernode' else 'Regular'
                    mev_label = 'Via MEV' if mev_status == 'mev' else 'Locally built'
                    glabel = f"{cl.title()} {node_label} ({mev_label})"
                else:
                    glabel = str(g)
            else:
                glabel = str(g).replace('supernode', 'Supernode').replace('regular', 'Regular').replace('-', ' + ').title()

        # For each x value (blob count or bucket), create a violin
        for x_val in x_order:
            subset = gdf[gdf[x_col] == x_val]
            if not subset.empty:
                # No longer track per-group counts (handled at bucket level)

                fig.add_trace(
                    go.Violin(
                        x=[x_val] * len(subset),
                        y=subset['head_correctness_pct'],
                        name=glabel,
                        legendgroup=glabel,
                        showlegend=(x_val == x_order[0]),  # Only show legend once per group
                        marker_color=color_map.get(g, '#999999'),
                        box_visible=True,
                        meanline_visible=True,
                        opacity=0.7,
                        points='outliers',
                        hovertemplate=f'<b>{glabel}</b><br>Blob: %{{x}}<br>Head Correctness: %{{y:.1f}}%<extra></extra>',
                        offsetgroup=str(g),
                        scalegroup=str(g),
                        scalemode='width'
                    )
                )

    # Add sample count annotations with true unique slot counts
    for x_val in x_order:
        if x_val in unique_slots_per_bucket:
            fig.add_annotation(
                x=x_val,
                y=-0.12,  # Position below the plot area
                text=f"({unique_slots_per_bucket[x_val]:,} slots)",
                showarrow=False,
                font=dict(size=10, color='#333'),
                xref='x',
                yref='paper'
            )
    
    # Set title based on grouping
    group_names = {
        'node_type': 'Node Type',
        'cl_client': 'CL Client',
        'el_client': 'EL Client',
        'cl_el_combined': 'CL+EL Combination',
        'cl_node_type': 'CL+Node Type',
        'el_node_type': 'EL+Node Type'
    }
    metric_label = _get_metric_label(metadata)
    gname = group_names.get(grouping_dimension, grouping_dimension)
    title = f'Head {metric_label} Distribution by {gname} (Violin Plot)'
    if title_suffix:
        title += f' — {title_suffix}'
    
    # Build compact subtitle
    subtitle_parts = []
    
    # First line: Network, time range, and slots
    if network:
        subtitle_parts.append(f'<b>{network}</b>')
    if time_range:
        subtitle_parts.append(time_range)
    if metadata and 'total_slots' in metadata:
        subtitle_parts.append(f'{metadata["total_slots"]:,} slots')
    
    subtitle_line1 = '  •  '.join(subtitle_parts) if subtitle_parts else None
    
    # Second line: Filter descriptions (more detailed)
    filter_parts = []
    if proposer_filters:
        filter_desc = _format_filter_description("Proposed by", proposer_filters)
        filter_parts.append(filter_desc)
    if attester_filters:
        filter_desc = _format_filter_description("Attested by", attester_filters)
        filter_parts.append(filter_desc)
    
    subtitle_line2 = '  |  '.join(filter_parts) if filter_parts else None
    
    # Build title with integrated subtitle
    subtitle_html = []
    if subtitle_line1:
        subtitle_html.append(f'<span style="font-size: 12px; color: #666;">{subtitle_line1}</span>')
    if subtitle_line2:
        subtitle_html.append(f'<span style="font-size: 11px; color: #888;">{subtitle_line2}</span>')
    
    if subtitle_html:
        title = title + '<br>' + '<br>'.join(subtitle_html)
    
    fig.update_layout(
        title=dict(
            text=title,
            x=0,
            xanchor='left',
            font=dict(size=16)
        ),
        height=600,
        showlegend=True,
        hovermode='closest',
        legend=dict(
            title=dict(text=_get_legend_title(data)),
            itemclick='toggle',
            itemdoubleclick='toggleothers',
            orientation='v',
            yanchor='top',
            y=0.95,
            xanchor='left',
            x=1.02,
            bgcolor='rgba(255,255,255,0.9)',
            bordercolor='rgba(0,0,0,0.3)',
            borderwidth=1
        ),
        xaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title=dict(
                text='All Blob Counts' if num_buckets == 1 else ('Blob Count Buckets' if num_buckets and num_buckets > 1 else 'Blob Count'),
                standoff=25
            ),
            categoryorder='array',
            categoryarray=x_order
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title=f'Head {metric_label} (%)',
            range=[0, 100]
        ),
        margin=dict(r=200, t=120, l=80, b=100),
        violinmode='group'
    )
    
    fig.add_layout_image(
        dict(
            source='https://ethpandaops.io/img/logo-slim.png',
            xref='paper',
            yref='paper',
            x=0.02,
            y=0.98,
            sizex=0.08,
            sizey=0.08,
            xanchor='left',
            yanchor='top'
        )
    )
    
    return fig


def create_head_correctness_ridgeline(
    data: pd.DataFrame,
    num_buckets: Optional[int] = None,
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    grouping_dimension: str = 'node_type',
    proposer_filters: Dict[str, Any] = None,
    attester_filters: Dict[str, Any] = None,
    title_suffix: str = ""
) -> go.Figure:
    """Create overlaid ridgeline plot with blob buckets overlaid per group."""
    if data.empty:
        return go.Figure()

    if 'head_correctness_pct' not in data.columns or 'blob_count' not in data.columns:
        logger.error("Missing required columns: head_correctness_pct, blob_count")
        return go.Figure()

    df = data.copy()

    # Add grouping if not present
    if 'group_key' not in df.columns:
        df['group_key'] = 'all'
        df['group_label'] = 'All Nodes'
    if 'group_label' not in df.columns:
        df['group_label'] = df['group_key']

    # Create blob buckets
    max_blobs = int(df['blob_count'].max())
    min_blobs = int(df['blob_count'].min())
    blob_range = max_blobs - min_blobs + 1

    if num_buckets == 1:
        df['blob_bucket_label'] = 'All blobs'
        bucket_col = 'blob_bucket_label'
        bucket_order = ['All blobs']
    elif num_buckets and num_buckets > 1:
        if blob_range <= num_buckets:
            df['blob_bucket_label'] = df['blob_count'].astype(str) + ' blobs'
            bucket_col = 'blob_bucket_label'
            bucket_order = [f"{i} blobs" for i in sorted(df['blob_count'].unique())]
        else:
            bucket_width = (max_blobs - min_blobs + 1) / num_buckets
            edges = [min_blobs + i * bucket_width for i in range(num_buckets + 1)]
            edges[-1] = max_blobs + 1

            df['blob_bucket'] = pd.cut(df['blob_count'], bins=edges, include_lowest=True, right=False)
            df['blob_bucket_label'] = df['blob_bucket'].apply(
                lambda x: f"{int(np.floor(x.left))}-{int(np.ceil(x.right)-1)} blobs" if pd.notna(x) else "Unknown"
            )
            bucket_col = 'blob_bucket_label'
            bucket_order = sorted(df['blob_bucket_label'].dropna().unique(),
                                key=lambda s: int(str(s).split('-')[0]) if '-' in str(s).split()[0] else int(str(s).split()[0]) if str(s).split()[0].isdigit() else 0)
    else:
        df['blob_bucket_label'] = df['blob_count'].astype(str) + ' blobs'
        bucket_col = 'blob_bucket_label'
        bucket_order = [f"{i} blobs" for i in sorted(df['blob_count'].unique())]

    fig = go.Figure()

    # Get unique groups and format labels
    unique_groups = sorted(df['group_key'].unique())
    group_labels = {}
    for g in unique_groups:
        group_df = df[df['group_key'] == g]
        if not group_df.empty and 'group_label' in group_df.columns:
            label = group_df['group_label'].iloc[0]
            if label:
                label = str(label).replace('supernode', 'Supernode').replace('regular', 'Regular')
            group_labels[g] = label
        else:
            group_labels[g] = str(g).replace('supernode', 'Supernode').replace('regular', 'Regular').title()

    # Define consistent colors for blob buckets
    bucket_colors = {
        bucket: f'hsl({i * 360 / len(bucket_order)}, 70%, 50%)'
        for i, bucket in enumerate(bucket_order)
    }

    # Ridge parameters
    y_step = 1.0  # Vertical spacing between groups
    ridge_height = 0.8  # Max height of density curves
    x_range = np.linspace(0, 100, 300)  # Head correctness grid

    # Create ridges for each group
    for group_idx, group_key in enumerate(unique_groups):
        y_base = group_idx * y_step
        group_data = df[df['group_key'] == group_key]
        group_label = group_labels.get(group_key, str(group_key))

        # Add invisible baseline trace for this ridge first
        fig.add_trace(go.Scatter(
            x=x_range,
            y=[y_base] * len(x_range),
            mode='lines',
            line=dict(color='rgba(0,0,0,0)', width=0),
            showlegend=False,
            hoverinfo='skip',
            name=f'{group_label}_baseline'
        ))

        # Overlay blob buckets on this ridge
        for bucket_idx, bucket in enumerate(bucket_order):
            bucket_data = group_data[group_data[bucket_col] == bucket]

            if not bucket_data.empty and len(bucket_data) > 1:
                try:
                    values = bucket_data['head_correctness_pct'].dropna().values

                    # Safe KDE with fallback
                    if len(values) > 1 and np.std(values) > 0:
                        kde = stats.gaussian_kde(values, bw_method='scott')
                        density = kde(x_range)
                    else:
                        # Fallback: small gaussian around mean
                        mean_val = np.mean(values)
                        density = np.exp(-0.5 * ((x_range - mean_val) / 1.0) ** 2)

                    # Normalize and scale
                    if np.max(density) > 0:
                        density = density / np.max(density) * ridge_height

                    y_values = density + y_base

                    # Get color for this bucket
                    color = bucket_colors[bucket]
                    # Convert to rgba for transparency
                    fillcolor = color.replace('hsl', 'hsla').replace(')', ', 0.4)')

                    fig.add_trace(go.Scatter(
                        x=x_range,
                        y=y_values,
                        mode='lines',
                        fill='tonexty',  # Fill to the previous trace (baseline or previous bucket)
                        fillcolor=fillcolor,
                        line=dict(color=color, width=1.5),
                        name=bucket,
                        legendgroup=bucket,
                        showlegend=(group_idx == 0),  # Show legend only for first group
                        hovertemplate=(
                            f'<b>{group_label}</b><br>'
                            f'Bucket: {bucket}<br>'
                            f'Head Correctness: %{{x:.1f}}%<br>'
                            f'Density: %{{y:.3f}}<br>'
                            f'n={bucket_data["slot"].nunique()}<extra></extra>'  # Count unique slots
                        )
                    ))

                    # Add another baseline trace after each bucket to reset the fill reference
                    if bucket_idx < len(bucket_order) - 1:  # Don't add after the last bucket
                        fig.add_trace(go.Scatter(
                            x=x_range,
                            y=[y_base] * len(x_range),
                            mode='lines',
                            line=dict(color='rgba(0,0,0,0)', width=0),
                            showlegend=False,
                            hoverinfo='skip',
                            name=f'{group_label}_baseline_{bucket_idx}'
                        ))

                except Exception as e:
                    logger.warning(f"Could not create density for {group_key}/{bucket}: {e}")

    # Set title based on grouping
    group_names = {
        'node_type': 'Node Type',
        'cl_client': 'CL Client',
        'el_client': 'EL Client',
        'cl_el_combined': 'CL+EL Combination',
        'cl_node_type': 'CL+Node Type',
        'el_node_type': 'EL+Node Type'
    }
    metric_label = _get_metric_label(metadata)
    gname = group_names.get(grouping_dimension, grouping_dimension)

    title = f'Head {metric_label} Density by {gname} (Ridgeline Plot)'
    if title_suffix:
        title += f' — {title_suffix}'

    # Build compact subtitle
    subtitle_parts = []
    if network:
        subtitle_parts.append(f'<b>{network}</b>')
    if time_range:
        subtitle_parts.append(time_range)
    if metadata and 'total_slots' in metadata:
        subtitle_parts.append(f'{metadata["total_slots"]:,} slots')

    subtitle_line1 = '  •  '.join(subtitle_parts) if subtitle_parts else None

    # Add filter descriptions
    filter_parts = []
    if proposer_filters:
        filter_desc = _format_filter_description("Proposed by", proposer_filters)
        filter_parts.append(filter_desc)
    if attester_filters:
        filter_desc = _format_filter_description("Attested by", attester_filters)
        filter_parts.append(filter_desc)

    subtitle_line2 = '  |  '.join(filter_parts) if filter_parts else None

    # Build title with integrated subtitle
    subtitle_html = []
    if subtitle_line1:
        subtitle_html.append(f'<span style="font-size: 12px; color: #666;">{subtitle_line1}</span>')
    if subtitle_line2:
        subtitle_html.append(f'<span style="font-size: 11px; color: #888;">{subtitle_line2}</span>')

    if subtitle_html:
        title = title + '<br>' + '<br>'.join(subtitle_html)

    # Set up y-axis labels for each group
    y_tick_vals = [i * y_step for i in range(len(unique_groups))]
    y_tick_labels = [group_labels.get(g, str(g)) for g in unique_groups]

    fig.update_layout(
        title=dict(
            text=title,
            x=0,
            xanchor='left',
            font=dict(size=16)
        ),
        height=max(350, 120 * len(unique_groups)),  # Dynamic height based on number of groups
        showlegend=True,
        legend=dict(
            title=dict(text='Blob Buckets'),
            orientation='v',
            yanchor='top',
            y=0.95,
            xanchor='left',
            x=1.02,
            bgcolor='rgba(255,255,255,0.9)',
            bordercolor='rgba(0,0,0,0.3)',
            borderwidth=1
        ),
        hovermode='closest',
        xaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title='Head Correctness (%)',
            range=[0, 100],
            showgrid=True,
            gridcolor='rgba(200,200,200,0.3)',
            dtick=10
        ),
        yaxis=dict(
            tickmode='array',
            tickvals=y_tick_vals,
            ticktext=y_tick_labels,
            showline=False,
            showgrid=False,
            zeroline=False,
            range=[-0.2, (len(unique_groups) - 1) * y_step + ridge_height + 0.2]
        ),
        margin=dict(r=180, t=120, l=150, b=80),
        plot_bgcolor='white'
    )

    # Add logo
    fig.add_layout_image(
        dict(
            source='https://ethpandaops.io/img/logo-slim.png',
            xref='paper',
            yref='paper',
            x=0.02,
            y=0.98,
            sizex=0.08,
            sizey=0.08,
            xanchor='left',
            yanchor='top'
        )
    )

    return fig


def create_advanced_grouped_boxplot(
    data: pd.DataFrame,
    network_spec_data: Dict[str, Any] = None,
    num_buckets: Optional[int] = None,
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    grouping_dimension: str = 'node_type',
    proposer_filters: Dict[str, Any] = None,
    attester_filters: Dict[str, Any] = None
) -> go.Figure:
    """Delegate to grouped boxplot; client map is already applied in SQL."""
    return create_head_correctness_boxplot(
        data=data,
        num_buckets=num_buckets,
        network=network,
        time_range=time_range,
        metadata=metadata,
        grouping_dimension=grouping_dimension,
        proposer_filters=proposer_filters,
        attester_filters=attester_filters
    )


def create_head_correctness_ecdf(
    data: pd.DataFrame,
    num_buckets: Optional[int] = None,
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    grouping_dimension: str = 'node_type',
    proposer_filters: Dict[str, Any] = None,
    attester_filters: Dict[str, Any] = None,
    difference_mode: bool = True,
    title_suffix: str = ""
) -> go.Figure:
    """Create ECDF (Empirical Cumulative Distribution Function) for head correctness by blob buckets."""
    if data.empty:
        return go.Figure()
    
    if 'blob_count' not in data.columns or 'head_correctness_pct' not in data.columns:
        logger.error("Missing required columns for ECDF: blob_count, head_correctness_pct")
        return go.Figure()
    
    df = data.copy()
    
    # Add grouping if not present
    if 'group_key' not in df.columns:
        df['group_key'] = 'all'
        df['group_label'] = 'All Nodes'
    if 'group_label' not in df.columns:
        df['group_label'] = df['group_key']
    
    # Calculate bucket size from number of buckets
    max_blobs = int(df['blob_count'].max())
    min_blobs = int(df['blob_count'].min())
    blob_range = max_blobs - min_blobs + 1
    
    # Apply bucketing if requested
    if num_buckets == 1:
        # Special case: single bucket for all blob counts
        df['blob_bucket_label'] = 'All'
        bucket_col = 'blob_bucket_label'
        bucket_order = ['All']
    elif num_buckets and num_buckets > 1:
        # If we have fewer unique blob counts than requested buckets, show individual counts
        if blob_range <= num_buckets:
            df['blob_bucket_label'] = df['blob_count'].astype(str)
            bucket_col = 'blob_bucket_label'
            bucket_order = sorted(df['blob_bucket_label'].dropna().unique(), key=lambda s: int(s) if s.isdigit() else 0)
        else:
            # Create exactly num_buckets buckets across the blob range
            bucket_width = (max_blobs - min_blobs + 1) / num_buckets
            edges = [min_blobs + i * bucket_width for i in range(num_buckets + 1)]
            edges[-1] = max_blobs + 1  # Ensure last edge includes max value
            
            df['blob_bucket'] = pd.cut(df['blob_count'], bins=edges, include_lowest=True, right=False)
            df['blob_bucket_label'] = df['blob_bucket'].apply(
                lambda x: f"{int(np.floor(x.left))}-{int(np.ceil(x.right)-1)}" if pd.notna(x) else "Unknown"
            )
            bucket_col = 'blob_bucket_label'
            bucket_order = sorted(df['blob_bucket_label'].dropna().unique(), 
                                key=lambda s: int(str(s).split('-')[0]) if '-' in str(s) else 0)
    else:
        df['blob_bucket_label'] = df['blob_count'].astype(str)
        bucket_col = 'blob_bucket_label'
        bucket_order = sorted(df['blob_bucket_label'].unique(), key=lambda x: int(x) if x.isdigit() else 0)
    
    fig = go.Figure()
    
    # Get smart color assignments
    unique_groups = df['group_key'].unique()
    color_map = _get_smart_colors(list(unique_groups), grouping_dimension)
    
    # Store reference ECDF for difference calculation if needed
    reference_ecdf = None
    reference_label = None
    
    # Create ECDF for each blob bucket
    for bucket_idx, bucket in enumerate(bucket_order):
        bucket_df = df[df[bucket_col] == bucket]
        
        if not bucket_df.empty:
            # For each group, calculate ECDF
            for group_idx, group_key in enumerate(sorted(df['group_key'].unique())):
                group_df = bucket_df[bucket_df['group_key'] == group_key]
                
                if not group_df.empty:
                    # Calculate ECDF
                    sorted_values = np.sort(group_df['head_correctness_pct'].values)
                    n = len(sorted_values)
                    ecdf_y = np.arange(1, n + 1) / n
                    
                    # Store first group as reference for difference mode
                    if difference_mode and bucket_idx == 0 and group_idx == 0:
                        reference_ecdf = (sorted_values, ecdf_y)
                        reference_label = group_df['group_label'].iloc[0]
                    
                    # Calculate difference if in difference mode and not the reference
                    if difference_mode and reference_ecdf is not None and group_idx > 0:
                        # Interpolate reference ECDF at current x values
                        ref_x, ref_y = reference_ecdf
                        ref_ecdf_interp = np.interp(sorted_values, ref_x, ref_y, left=0, right=1)
                        y_values = ecdf_y - ref_ecdf_interp
                        y_label = 'ECDF Difference from Reference'
                    else:
                        y_values = ecdf_y * 100  # Convert to percentage
                        y_label = 'Cumulative Probability (%)'
                    
                    group_label = group_df['group_label'].iloc[0]
                    
                    fig.add_trace(
                        go.Scatter(
                            x=sorted_values,
                            y=y_values if difference_mode else y_values,
                            mode='lines',
                            name=f'{group_label} - Bucket {bucket}',
                            line=dict(
                                color=color_map.get(group_key, '#999999'),
                                width=2,
                                dash='solid' if bucket_idx == 0 else ['dash', 'dot', 'dashdot'][bucket_idx % 3]
                            ),
                            legendgroup=group_label,
                            hovertemplate=f'<b>{group_label}</b><br>Bucket: {bucket}<br>Head Correctness: %{{x:.1f}}%<br>{y_label}: %{{y:.2f}}{"%" if not difference_mode else ""}<extra></extra>'
                        )
                    )
    
    # Set title
    group_names = {
        'node_type': 'Node Type',
        'cl_client': 'CL Client',
        'el_client': 'EL Client',
        'cl_el_combined': 'CL+EL Combination',
        'cl_node_type': 'CL+Node Type',
        'el_node_type': 'EL+Node Type'
    }
    metric_label = _get_metric_label(metadata)
    gname = group_names.get(grouping_dimension, grouping_dimension)
    
    if difference_mode:
        title = f'Difference ECDF: Head {metric_label} by {gname} and Blob Buckets'
        if reference_label:
            title += f'<br><span style="font-size: 12px; color: #666;">Reference: {reference_label}</span>'
    else:
        title = f'ECDF: Head {metric_label} by {gname} and Blob Buckets'
    
    if title_suffix:
        title += f' — {title_suffix}'
    
    # Build subtitle
    subtitle_parts = []
    if network:
        subtitle_parts.append(f'<b>{network}</b>')
    if time_range:
        subtitle_parts.append(time_range)
    if metadata and 'total_slots' in metadata:
        subtitle_parts.append(f'{metadata["total_slots"]:,} slots')
    
    subtitle_line1 = '  •  '.join(subtitle_parts) if subtitle_parts else None
    
    # Filter descriptions
    filter_parts = []
    if proposer_filters:
        filter_desc = _format_filter_description("Proposed by", proposer_filters)
        filter_parts.append(filter_desc)
    if attester_filters:
        filter_desc = _format_filter_description("Attested by", attester_filters)
        filter_parts.append(filter_desc)
    
    subtitle_line2 = '  |  '.join(filter_parts) if filter_parts else None
    
    # Combine subtitle
    subtitle_html = []
    if subtitle_line1:
        subtitle_html.append(f'<span style="font-size: 12px; color: #666;">{subtitle_line1}</span>')
    if subtitle_line2:
        subtitle_html.append(f'<span style="font-size: 11px; color: #888;">{subtitle_line2}</span>')
    
    if subtitle_html:
        title = title + '<br>' + '<br>'.join(subtitle_html)
    
    # Add reference line at y=0 for difference mode
    if difference_mode:
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    
    fig.update_layout(
        title=dict(
            text=title,
            x=0,
            xanchor='left',
            font=dict(size=16)
        ),
        height=600,
        showlegend=True,
        hovermode='closest',
        legend=dict(
            title=dict(text=_get_legend_title(data)),
            itemclick='toggle',
            itemdoubleclick='toggleothers',
            orientation='v',
            yanchor='top',
            y=0.95,
            xanchor='left',
            x=1.02,
            bgcolor='rgba(255,255,255,0.9)',
            bordercolor='rgba(0,0,0,0.3)',
            borderwidth=1
        ),
        xaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title=f'Head {metric_label} (%)',
            range=[0, 100]
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title='ECDF Difference' if difference_mode else 'Cumulative Probability (%)',
            range=[-0.5, 0.5] if difference_mode else [0, 100]
        ),
        margin=dict(r=250, t=140, l=80)
    )
    
    # Add logo
    fig.add_layout_image(
        dict(
            source='https://ethpandaops.io/img/logo-slim.png',
            xref='paper',
            yref='paper',
            x=0.02,
            y=0.98,
            sizex=0.08,
            sizey=0.08,
            xanchor='left',
            yanchor='top'
        )
    )
    
    return fig


def create_head_correctness_cdf(
    data: pd.DataFrame,
    num_buckets: Optional[int] = None,
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    grouping_dimension: str = 'node_type',
    proposer_filters: Dict[str, Any] = None,
    attester_filters: Dict[str, Any] = None,
    inverse: bool = True,
    title_suffix: str = ""
) -> go.Figure:
    """Create CDF (or inverse CDF/quantile plot) for head correctness by blob buckets."""
    if inverse:
        # Create inverse CDF (quantile plot) with swapped axes
        return create_head_correctness_inverse_cdf(
            data=data,
            num_buckets=num_buckets,
            network=network,
            time_range=time_range,
            metadata=metadata,
            grouping_dimension=grouping_dimension,
            proposer_filters=proposer_filters,
            attester_filters=attester_filters,
            title_suffix=title_suffix
        )
    else:
        # Use ECDF function with difference_mode=False for normal CDF
        return create_head_correctness_ecdf(
            data=data,
            num_buckets=num_buckets,
            network=network,
            time_range=time_range,
            metadata=metadata,
            grouping_dimension=grouping_dimension,
            proposer_filters=proposer_filters,
            attester_filters=attester_filters,
            difference_mode=False
        )


def create_head_correctness_inverse_cdf(
    data: pd.DataFrame,
    num_buckets: Optional[int] = None,
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    grouping_dimension: str = 'node_type',
    proposer_filters: Dict[str, Any] = None,
    attester_filters: Dict[str, Any] = None,
    title_suffix: str = ""
) -> go.Figure:
    """Create inverse CDF (quantile plot) with axes swapped - percentiles on X, values on Y."""
    if data.empty:
        return go.Figure()
    
    if 'blob_count' not in data.columns or 'head_correctness_pct' not in data.columns:
        logger.error("Missing required columns for CDF: blob_count, head_correctness_pct")
        return go.Figure()
    
    df = data.copy()
    
    # Add grouping if not present
    if 'group_key' not in df.columns:
        df['group_key'] = 'all'
        df['group_label'] = 'All Nodes'
    if 'group_label' not in df.columns:
        df['group_label'] = df['group_key']
    
    # Calculate bucket size from number of buckets
    max_blobs = int(df['blob_count'].max())
    min_blobs = int(df['blob_count'].min())
    blob_range = max_blobs - min_blobs + 1
    
    # Apply bucketing if requested
    if num_buckets == 1:
        # Special case: single bucket for all blob counts
        df['blob_bucket_label'] = 'All'
        bucket_col = 'blob_bucket_label'
        bucket_order = ['All']
    elif num_buckets and num_buckets > 1:
        # If we have fewer unique blob counts than requested buckets, show individual counts
        if blob_range <= num_buckets:
            df['blob_bucket_label'] = df['blob_count'].astype(str)
            bucket_col = 'blob_bucket_label'
            bucket_order = sorted(df['blob_bucket_label'].dropna().unique(), key=lambda s: int(s) if s.isdigit() else 0)
        else:
            # Create exactly num_buckets buckets across the blob range
            bucket_width = (max_blobs - min_blobs + 1) / num_buckets
            edges = [min_blobs + i * bucket_width for i in range(num_buckets + 1)]
            edges[-1] = max_blobs + 1  # Ensure last edge includes max value
            
            df['blob_bucket'] = pd.cut(df['blob_count'], bins=edges, include_lowest=True, right=False)
            df['blob_bucket_label'] = df['blob_bucket'].apply(
                lambda x: f"{int(np.floor(x.left))}-{int(np.ceil(x.right)-1)}" if pd.notna(x) else "Unknown"
            )
            bucket_col = 'blob_bucket_label'
            bucket_order = sorted(df['blob_bucket_label'].dropna().unique(), 
                                key=lambda s: int(str(s).split('-')[0]) if '-' in str(s) else 0)
    else:
        df['blob_bucket_label'] = df['blob_count'].astype(str)
        bucket_col = 'blob_bucket_label'
        bucket_order = sorted(df['blob_bucket_label'].unique(), key=lambda x: int(x) if x.isdigit() else 0)
    
    fig = go.Figure()
    
    # Get smart color assignments
    unique_groups = df['group_key'].unique()
    color_map = _get_smart_colors(list(unique_groups), grouping_dimension)
    
    # Create inverse CDF for each blob bucket
    for bucket_idx, bucket in enumerate(bucket_order):
        bucket_df = df[df[bucket_col] == bucket]
        
        if not bucket_df.empty:
            # For each group, calculate inverse CDF
            for group_idx, group_key in enumerate(sorted(df['group_key'].unique())):
                group_df = bucket_df[bucket_df['group_key'] == group_key]
                
                if not group_df.empty:
                    # Calculate CDF
                    sorted_values = np.sort(group_df['head_correctness_pct'].values)
                    n = len(sorted_values)
                    percentiles = np.arange(1, n + 1) / n * 100  # Convert to percentage
                    
                    group_label = group_df['group_label'].iloc[0]
                    
                    fig.add_trace(
                        go.Scatter(
                            x=percentiles,  # Percentiles on X-axis
                            y=sorted_values,  # Head correctness values on Y-axis
                            mode='lines',
                            name=f'{group_label} - Bucket {bucket}',
                            line=dict(
                                color=color_map.get(group_key, '#999999'),
                                width=2,
                                dash='solid' if bucket_idx == 0 else ['dash', 'dot', 'dashdot'][bucket_idx % 3]
                            ),
                            legendgroup=group_label,
                            hovertemplate=f'<b>{group_label}</b><br>Bucket: {bucket}<br>Percentile: %{{x:.1f}}%<br>Head Correctness: %{{y:.1f}}%<extra></extra>'
                        )
                    )
    
    # Set title
    group_names = {
        'node_type': 'Node Type',
        'cl_client': 'CL Client',
        'el_client': 'EL Client',
        'cl_el_combined': 'CL+EL Combination',
        'cl_node_type': 'CL+Node Type',
        'el_node_type': 'EL+Node Type'
    }
    gname = group_names.get(grouping_dimension, grouping_dimension)
    
    metric_label = _get_metric_label(metadata)
    title = f'Quantile Plot: Head {metric_label} by {gname} and Blob Buckets'
    if title_suffix:
        title += f' — {title_suffix}'
    
    # Build subtitle
    subtitle_parts = []
    if network:
        subtitle_parts.append(f'<b>{network}</b>')
    if time_range:
        subtitle_parts.append(time_range)
    if metadata and 'total_slots' in metadata:
        subtitle_parts.append(f'{metadata["total_slots"]:,} slots')
    
    subtitle_line1 = '  •  '.join(subtitle_parts) if subtitle_parts else None
    
    # Filter descriptions
    filter_parts = []
    if proposer_filters:
        filter_desc = _format_filter_description("Proposed by", proposer_filters)
        filter_parts.append(filter_desc)
    if attester_filters:
        filter_desc = _format_filter_description("Attested by", attester_filters)
        filter_parts.append(filter_desc)
    
    subtitle_line2 = '  |  '.join(filter_parts) if filter_parts else None
    
    # Combine subtitle
    subtitle_html = []
    if subtitle_line1:
        subtitle_html.append(f'<span style="font-size: 12px; color: #666;">{subtitle_line1}</span>')
    if subtitle_line2:
        subtitle_html.append(f'<span style="font-size: 11px; color: #888;">{subtitle_line2}</span>')
    
    if subtitle_html:
        title = title + '<br>' + '<br>'.join(subtitle_html)
    
    # Add reference lines for key percentiles
    for p in [50, 90, 95, 99]:
        fig.add_vline(x=p, line_dash="dot", line_color="gray", opacity=0.3,
                     annotation_text=f"P{p}", annotation_position="top")
    
    fig.update_layout(
        title=dict(
            text=title,
            x=0,
            xanchor='left',
            font=dict(size=16)
        ),
        height=600,
        showlegend=True,
        hovermode='closest',
        legend=dict(
            title=dict(text=_get_legend_title(data)),
            itemclick='toggle',
            itemdoubleclick='toggleothers',
            orientation='v',
            yanchor='top',
            y=0.95,
            xanchor='left',
            x=1.02,
            bgcolor='rgba(255,255,255,0.9)',
            bordercolor='rgba(0,0,0,0.3)',
            borderwidth=1
        ),
        xaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title='Percentile (%)',
            range=[0, 100]
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title=f'Head {metric_label} (%)',
            range=[0, 100]
        ),
        margin=dict(r=250, t=140, l=80)
    )
    
    # Add logo
    fig.add_layout_image(
        dict(
            source='https://ethpandaops.io/img/logo-slim.png',
            xref='paper',
            yref='paper',
            x=0.02,
            y=0.98,
            sizex=0.08,
            sizey=0.08,
            xanchor='left',
            yanchor='top'
        )
    )
    
    return fig



def create_head_correctness_summary(
    data: pd.DataFrame,
    num_buckets: Optional[int] = None,
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    grouping_dimension: str = "node_type",
    proposer_filters: Dict[str, Any] = None,
    attester_filters: Dict[str, Any] = None,
    performance_threshold: float = 95.0
) -> go.Figure:
    """Create statistical summary table for head correctness data."""
    if data.empty:
        return go.Figure()
    
    if "blob_count" not in data.columns or "head_correctness_pct" not in data.columns:
        logger.error("Missing required columns for summary: blob_count, head_correctness_pct")
        return go.Figure()
    
    df = data.copy()
    
    # Add grouping if not present
    if "group_key" not in df.columns:
        df["group_key"] = "all"
    if "group_label" not in df.columns:
        df["group_label"] = df["group_key"]
    
    # Calculate bucket size from number of buckets
    max_blobs = int(df["blob_count"].max()) if len(df) else 0
    min_blobs = int(df["blob_count"].min()) if len(df) else 0
    blob_range = max_blobs - min_blobs + 1
    
    # Apply bucketing if requested
    if num_buckets == 1:
        # Special case: single bucket for all blob counts
        df["blob_bucket_label"] = "All"
        bucket_col = "blob_bucket_label"
        bucket_order = ["All"]
    elif num_buckets and num_buckets > 1:
        # If we have fewer unique blob counts than requested buckets, show individual counts
        if blob_range <= num_buckets:
            df["blob_bucket_label"] = df["blob_count"].astype(str)
            bucket_col = "blob_bucket_label"
            bucket_order = sorted(df["blob_bucket_label"].dropna().unique(), key=lambda s: int(s) if s.isdigit() else 0)
        else:
            # Create exactly num_buckets buckets across the blob range
            bucket_width = (max_blobs - min_blobs + 1) / num_buckets
            edges = [min_blobs + i * bucket_width for i in range(num_buckets + 1)]
            edges[-1] = max_blobs + 1  # Ensure last edge includes max value
            
            df["blob_bucket"] = pd.cut(df["blob_count"], bins=edges, include_lowest=True, right=False)
            df["blob_bucket_label"] = df["blob_bucket"].apply(
                lambda x: f"{int(np.floor(x.left))}-{int(np.ceil(x.right)-1)}" if pd.notna(x) else "Unknown"
            )
            bucket_col = "blob_bucket_label"
            bucket_order = sorted(df["blob_bucket_label"].dropna().unique(), 
                                key=lambda s: int(str(s).split("-")[0]) if "-" in str(s) else 0)
    else:
        df["blob_bucket_label"] = df["blob_count"].astype(str)
        bucket_col = "blob_bucket_label"
        bucket_order = sorted(df["blob_bucket_label"].unique(), key=lambda x: int(x) if x.isdigit() else 0)
    
    # Calculate statistics for each group and bucket combination
    summary_data = []
    
    for group_key in sorted(df["group_key"].unique()):
        group_df = df[df["group_key"] == group_key]
        group_label = group_df["group_label"].iloc[0] if not group_df.empty else str(group_key)
        
        # Format group label
        if group_label:
            group_label = str(group_label).replace("supernode", "Supernode").replace("regular", "Regular").replace("-", " + ").title()
        
        for bucket in bucket_order:
            bucket_df = group_df[group_df[bucket_col] == bucket]
            
            if not bucket_df.empty:
                correctness_values = bucket_df["head_correctness_pct"].values
                
                # Calculate statistics
                total_slots = bucket_df['slot'].nunique()  # Count unique slots
                slots_above_threshold = np.sum(correctness_values >= performance_threshold)
                pct_above_threshold = (slots_above_threshold / len(correctness_values) * 100) if len(correctness_values) > 0 else 0
                
                mean_val = np.mean(correctness_values)
                median_val = np.median(correctness_values)
                std_val = np.std(correctness_values)
                min_val = np.min(correctness_values)
                max_val = np.max(correctness_values)
                q25 = np.percentile(correctness_values, 25)
                q75 = np.percentile(correctness_values, 75)
                
                summary_data.append({
                    "Group": group_label,
                    "Blob Bucket": bucket,
                    "Total Slots": total_slots,
                    f"% ≥{performance_threshold:.0f}%": f"{pct_above_threshold:.1f}%",
                    "Mean": f"{mean_val:.1f}%",
                    "Median": f"{median_val:.1f}%",
                    "Std Dev": f"{std_val:.1f}",
                    "Q25": f"{q25:.1f}%",
                    "Q75": f"{q75:.1f}%",
                    "Min": f"{min_val:.1f}%",
                    "Max": f"{max_val:.1f}%"
                })
    
    # Create table figure
    if summary_data:
        # Convert to dataframe for easier handling
        summary_df = pd.DataFrame(summary_data)
        
        # Create color coding for performance column
        perf_col_name = f"% ≥{performance_threshold:.0f}%"
        perf_values = [float(val.strip("%")) for val in summary_df[perf_col_name]]
        
        # Color scale: red (<70%), yellow (70-90%), green (>90%)
        cell_colors = []
        for val in perf_values:
            if val >= 90:
                cell_colors.append("#c8e6c9")  # Light green
            elif val >= 70:
                cell_colors.append("#fff9c4")  # Light yellow
            else:
                cell_colors.append("#ffcdd2")  # Light red
        
        # Create table
        fig = go.Figure(data=[go.Table(
            header=dict(
                values=list(summary_df.columns),
                fill_color="#2c3e50",
                font=dict(color="white", size=12),
                align="center",
                height=35
            ),
            cells=dict(
                values=[summary_df[col] for col in summary_df.columns],
                fill_color=["white"] * 3 + [cell_colors] + ["white"] * 7,  # Color only the performance column
                font=dict(size=11),
                align=["left", "center"] + ["right"] * 9,
                height=30
            )
        )])
        
        # Build title and subtitle
        group_names = {
            "node_type": "Node Type",
            "cl_client": "CL Client",
            "el_client": "EL Client",
            "cl_el_combined": "CL+EL Combination",
            "cl_node_type": "CL+Node Type",
            "el_node_type": "EL+Node Type",
            "block_building": "Block Building Method",
            "node_type_mev": "Node Type + Block Building",
            "cl_node_type_mev": "CL+Node Type + Block Building"
        }
        metric_label = _get_metric_label(metadata)
        gname = group_names.get(grouping_dimension, grouping_dimension)
        title = f"Head {metric_label} Statistical Summary by {gname}"
        
        # Build subtitle
        subtitle_parts = []
        
        if network:
            subtitle_parts.append(f"<b>{network}</b>")
        if time_range:
            subtitle_parts.append(time_range)
        if metadata:
            total_slots = metadata.get("total_slots", 0)
            if total_slots:
                subtitle_parts.append(f"{total_slots:,} slots analyzed")
        
        subtitle_line1 = "  •  ".join(subtitle_parts) if subtitle_parts else None
        
        # Filter descriptions
        filter_parts = []
        if proposer_filters:
            filter_desc = _format_filter_description("Proposed by", proposer_filters)
            filter_parts.append(filter_desc)
        if attester_filters:
            filter_desc = _format_filter_description("Attested by", attester_filters)
            filter_parts.append(filter_desc)
        
        subtitle_line2 = "  |  ".join(filter_parts) if filter_parts else None
        
        # Combine subtitle
        subtitle_html = []
        if subtitle_line1:
            subtitle_html.append(f'<span style="font-size: 12px; color: #666;">{subtitle_line1}</span>')
        if subtitle_line2:
            subtitle_html.append(f'<span style="font-size: 11px; color: #888;">{subtitle_line2}</span>')
        
        # Add performance threshold note
        subtitle_html.append(f'<span style="font-size: 10px; color: #999;">Performance threshold: ≥{performance_threshold:.0f}% head correctness | Colors: 🟢 ≥90% slots meeting threshold, 🟡 70-90%, 🔴 <70%</span>')
        
        if subtitle_html:
            title = title + "<br>" + "<br>".join(subtitle_html)
        
        fig.update_layout(
            title=dict(
                text=title,
                x=0,
                xanchor="left",
                font=dict(size=16)
            ),
            height=max(400, 180 + len(summary_data) * 35),  # Dynamic height to show all rows without scrolling
            margin=dict(t=140, l=20, r=20, b=20)
        )
    else:
        # No data to display
        fig = go.Figure()
        fig.add_annotation(
            text="No data available for the selected filters",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color="gray")
        )
        fig.update_layout(
            height=400,
            xaxis=dict(visible=False),
            yaxis=dict(visible=False)
        )
    
    return fig


def create_head_correctness_bar(
    data: pd.DataFrame,
    num_buckets: Optional[int] = None,
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    grouping_dimension: str = "node_type",
    proposer_filters: Dict[str, Any] = None,
    attester_filters: Dict[str, Any] = None,
    title_suffix: str = ""
) -> go.Figure:
    """Create grouped bar chart for head correctness/incorrectness data by blob buckets."""
    if data.empty:
        return go.Figure()
    
    if "blob_count" not in data.columns or "head_correctness_pct" not in data.columns:
        logger.error("Missing required columns for bar chart: blob_count, head_correctness_pct")
        return go.Figure()
    
    df = data.copy()
    
    # Add grouping if not present
    if "group_key" not in df.columns:
        df["group_key"] = "all"
        df["group_label"] = "All Nodes"
    if "group_label" not in df.columns:
        df["group_label"] = df["group_key"]
    
    # Calculate bucket size from number of buckets
    max_blobs = int(df["blob_count"].max()) if len(df) else 0
    min_blobs = int(df["blob_count"].min()) if len(df) else 0
    blob_range = max_blobs - min_blobs + 1
    
    # Apply bucketing if requested
    if num_buckets == 1:
        # Special case: single bucket for all blob counts
        df["blob_bucket_label"] = "All"
        bucket_col = "blob_bucket_label"
        bucket_order = ["All"]
    elif num_buckets and num_buckets > 1:
        # If we have fewer unique blob counts than requested buckets, show individual counts
        if blob_range <= num_buckets:
            df["blob_bucket_label"] = df["blob_count"].astype(str)
            bucket_col = "blob_bucket_label"
            bucket_order = sorted(df["blob_bucket_label"].dropna().unique(), key=lambda s: int(s) if s.isdigit() else 0)
        else:
            # Create exactly num_buckets buckets across the blob range
            bucket_width = (max_blobs - min_blobs + 1) / num_buckets
            edges = [min_blobs + i * bucket_width for i in range(num_buckets + 1)]
            edges[-1] = max_blobs + 1  # Ensure last edge includes max value
            
            df["blob_bucket"] = pd.cut(df["blob_count"], bins=edges, include_lowest=True, right=False)
            df["blob_bucket_label"] = df["blob_bucket"].apply(
                lambda x: f"{int(np.floor(x.left))}-{int(np.ceil(x.right)-1)}" if pd.notna(x) else "Unknown"
            )
            bucket_col = "blob_bucket_label"
            bucket_order = sorted(df["blob_bucket_label"].dropna().unique(), 
                                key=lambda s: int(str(s).split("-")[0]) if "-" in str(s) else 0)
    else:
        df["blob_bucket_label"] = df["blob_count"].astype(str)
        bucket_col = "blob_bucket_label"
        bucket_order = sorted(df["blob_bucket_label"].unique(), key=lambda x: int(x) if x.isdigit() else 0)
    
    # Calculate mean correctness for each group and bucket combination
    bar_data = []
    for group_key in sorted(df["group_key"].unique()):
        group_df = df[df["group_key"] == group_key]
        group_label = group_df["group_label"].iloc[0] if not group_df.empty else str(group_key)
        
        # Format group label
        if group_label:
            group_label = str(group_label).replace("supernode", "Supernode").replace("regular", "Regular").replace("-", " + ").title()
        
        bucket_means = []
        bucket_stds = []
        bucket_counts = []
        
        for bucket in bucket_order:
            bucket_df = group_df[group_df[bucket_col] == bucket]
            if not bucket_df.empty:
                bucket_means.append(bucket_df["head_correctness_pct"].mean())
                bucket_stds.append(bucket_df["head_correctness_pct"].std())
                bucket_counts.append(bucket_df['slot'].nunique())  # Count unique slots
            else:
                bucket_means.append(0)
                bucket_stds.append(0)
                bucket_counts.append(0)
        
        bar_data.append({
            "group": group_label,
            "buckets": bucket_order,
            "means": bucket_means,
            "stds": bucket_stds,
            "counts": bucket_counts
        })
    
    # Create figure
    fig = go.Figure()
    
    # Get smart color assignments for the groups
    group_keys = df['group_key'].unique()
    color_map = _get_smart_colors(list(group_keys), grouping_dimension)
    
    # Map group labels back to keys for color lookup
    label_to_key_map = {}
    for key in df['group_key'].unique():
        key_df = df[df['group_key'] == key]
        if not key_df.empty:
            label = key_df['group_label'].iloc[0] if 'group_label' in key_df.columns else str(key)
            # Apply same formatting as in bar_data creation
            label = str(label).replace("supernode", "Supernode").replace("regular", "Regular").replace("-", " + ").title()
            label_to_key_map[label] = key
    
    # Add bars for each group
    for group_data in bar_data:
        # Create custom hover text for each bar
        hover_texts = []
        for i, bucket in enumerate(group_data["buckets"]):
            hover_text = (
                f"<b>{group_data['group']}</b><br>"
                f"Blob Bucket: {bucket}<br>"
                f"Mean: {group_data['means'][i]:.1f}%<br>"
                f"Std Dev: {group_data['stds'][i]:.1f}%<br>"
                f"Slots: {group_data['counts'][i]}"
            )
            hover_texts.append(hover_text)
        
        # Add main bars
        fig.add_trace(go.Bar(
            name=group_data["group"],
            x=group_data["buckets"],
            y=group_data["means"],
            marker_color=color_map.get(label_to_key_map.get(group_data["group"], group_data["group"]), '#999999'),
            opacity=0.9,
            text=[f"{mean:.1f}%" for mean in group_data["means"]],
            textposition='outside',
            textfont=dict(size=10),
            hovertemplate=hover_texts,
            hovertext=hover_texts
        ))

    # Add sample count annotations
    # Aggregate counts for each bucket across all groups
    bucket_totals = {}
    for group_data in bar_data:
        for i, bucket in enumerate(group_data["buckets"]):
            if bucket not in bucket_totals:
                bucket_totals[bucket] = 0
            bucket_totals[bucket] += group_data["counts"][i]

    # Add annotations for each bucket
    for bucket in bucket_order:
        if bucket in bucket_totals:
            fig.add_annotation(
                x=bucket,
                y=-0.12,  # Position below the plot area
                text=f"({bucket_totals[bucket]:,} slots)",
                showarrow=False,
                font=dict(size=10, color='#333'),
                xref='x',
                yref='paper'
            )

    # Determine if showing correctness or incorrectness
    is_incorrect = metadata and metadata.get('view_mode') == 'incorrect'
    metric_label = _get_metric_label(metadata)
    
    # Create title with subtitle
    title = f"<b>Head {metric_label} by Blob Count and {_get_grouping_label(grouping_dimension)}</b>"
    if title_suffix:
        title += f" — {title_suffix}"
    
    subtitle_parts = []
    if network:
        subtitle_parts.append(f"Network: {network}")
    if time_range:
        subtitle_parts.append(f"Period: {time_range}")
    if metadata:
        subtitle_parts.append(f"Slots Analyzed: {metadata.get('total_slots_analyzed', 0):,}")
    
    subtitle_line1 = '  |  '.join(subtitle_parts) if subtitle_parts else None
    
    # Add filter information
    filter_parts = []
    if proposer_filters:
        filter_desc = _format_filter_description("Proposed by", proposer_filters)
        filter_parts.append(filter_desc)
    if attester_filters:
        filter_desc = _format_filter_description("Attested by", attester_filters)
        filter_parts.append(filter_desc)
    
    subtitle_line2 = '  |  '.join(filter_parts) if filter_parts else None
    
    # Combine subtitle
    subtitle_html = []
    if subtitle_line1:
        subtitle_html.append(f'<span style="font-size: 12px; color: #666;">{subtitle_line1}</span>')
    if subtitle_line2:
        subtitle_html.append(f'<span style="font-size: 11px; color: #888;">{subtitle_line2}</span>')
    
    if subtitle_html:
        title = title + '<br>' + '<br>'.join(subtitle_html)
    
    # Reference lines removed for cleaner visualization
    
    # Update layout
    fig.update_layout(
        title=dict(
            text=title,
            x=0,
            xanchor='left',
            font=dict(size=16)
        ),
        barmode='group',
        xaxis=dict(
            title=dict(
                text='All Blob Counts' if num_buckets == 1 else 'Blob Count Bucket',
                standoff=25
            ),
            tickmode='array',
            tickvals=bucket_order,
            ticktext=bucket_order,
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside'
        ),
        yaxis=dict(
            title=f'Head {metric_label} (%)',
            range=[0, 100] if not is_incorrect else [0, max(30, max([max(d["means"]) for d in bar_data if d["means"]]) * 1.2 if bar_data else 30)],
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside'
        ),
        height=600,
        showlegend=True,
        legend=dict(
            title=dict(text=_get_legend_title(data)),
            itemclick='toggle',
            itemdoubleclick='toggleothers',
            orientation='v',
            yanchor='top',
            y=0.95,
            xanchor='left',
            x=1.02,
            bgcolor='rgba(255,255,255,0.9)',
            bordercolor='rgba(0,0,0,0.3)',
            borderwidth=1
        ),
        bargap=0.15,
        bargroupgap=0.1,
        hovermode='x unified',
        margin=dict(r=200, t=140, l=80, b=100)
    )
    
    # Add logo
    fig.add_layout_image(
        dict(
            source='https://ethpandaops.io/img/logo-slim.png',
            xref='paper',
            yref='paper',
            x=0.02,
            y=0.98,
            sizex=0.08,
            sizey=0.08,
            xanchor='left',
            yanchor='top'
        )
    )
    
    return fig


def _get_grouping_label(grouping_dimension: str) -> str:
    """Get human-readable label for grouping dimension."""
    labels = {
        'node_type': 'Node Type',
        'cl_client': 'CL Client',
        'el_client': 'EL Client',
        'cl_el_combined': 'CL+EL Combination',
        'cl_node_type': 'CL+Node Type',
        'el_node_type': 'EL+Node Type',
        'block_building': 'Block Building Method',
        'node_type_mev': 'Node Type + MEV',
        'cl_node_type_mev': 'CL+Node Type + MEV'
    }
    return labels.get(grouping_dimension, grouping_dimension)


def create_dual_chart_if_needed(
    data: pd.DataFrame,
    chart_function,
    **kwargs
) -> go.Figure:
    """
    Wrapper function to create dual charts when both proposer and attester data are present.
    
    If data contains both data_type='proposer' and data_type='attester', creates side-by-side
    subplots. Otherwise, returns a single chart.
    """
    # Check if we have dual data
    if 'data_type' not in data.columns:
        # No data_type column, treat as single chart
        return chart_function(data, **kwargs)
    
    data_types = data['data_type'].unique()
    
    if len(data_types) == 1:
        # Only one data type, create single chart
        return chart_function(data, **kwargs)
    
    # We have both proposer and attester data - create dual charts
    proposer_data = data[data['data_type'] == 'proposer'].copy()
    attester_data = data[data['data_type'] == 'attester'].copy()
    
    # Create subplots
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=("Proposer Grouping", "Attester Grouping"),
        horizontal_spacing=0.12
    )
    
    # Generate individual charts
    proposer_fig = chart_function(proposer_data, **kwargs)
    attester_fig = chart_function(attester_data, **kwargs)
    
    # Extract traces and add to subplots
    for trace in proposer_fig.data:
        fig.add_trace(trace, row=1, col=1)
    
    for trace in attester_fig.data:
        # Update trace names to avoid legend conflicts
        trace.name = f"{trace.name} (Attester)" if trace.name else "Attester"
        trace.showlegend = False  # Hide attester legend to avoid clutter
        fig.add_trace(trace, row=1, col=2)
    
    # Update layout
    metric_label = _get_metric_label(kwargs.get('metadata'))
    main_title = f'Head {metric_label} Analysis: Proposer vs Attester Characteristics'
    
    if kwargs.get('network'):
        main_title = f'{kwargs["network"]} — {main_title}'
    if kwargs.get('time_range'):
        main_title += f'<br><span style="font-size: 12px; color: #666;">Time: {kwargs["time_range"]}</span>'
    
    fig.update_layout(
        title=dict(
            text=main_title,
            x=0,
            xanchor='left',
            font=dict(size=16)
        ),
        height=600,
        showlegend=True,
        hovermode='x unified',
        margin=dict(r=150, t=120, l=80, b=80)
    )
    
    # Update axes labels
    fig.update_xaxes(title_text="Blob Count", row=1, col=1)
    fig.update_xaxes(title_text="Blob Count", row=1, col=2)
    fig.update_yaxes(title_text=f"Head {metric_label} (%)", range=[0, 100], row=1, col=1)
    fig.update_yaxes(title_text=f"Head {metric_label} (%)", range=[0, 100], row=1, col=2)
    
    # Add logo
    fig.add_layout_image(
        dict(
            source='https://ethpandaops.io/img/logo-slim.png',
            xref='paper',
            yref='paper',
            x=0.02,
            y=0.98,
            sizex=0.08,
            sizey=0.08,
            xanchor='left',
            yanchor='top'
        )
    )
    
    return fig
