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
from typing import Dict, Any, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    grouping_dimension: str = 'node_type',
    proposer_filters: Dict[str, Any] = None,
    attester_filters: Dict[str, Any] = None
) -> go.Figure:
    """Create head correctness chart showing p95 accuracy percentage by blob count buckets with grouping."""
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
    if num_buckets and num_buckets > 1 and blob_range > num_buckets:
        bucket_size = int(np.ceil(blob_range / num_buckets))
        edges = np.arange(min_blobs, max_blobs + bucket_size, bucket_size)
        df['blob_bucket'] = pd.cut(df['blob_count'], bins=edges, include_lowest=True, right=False)
        df['blob_bucket_label'] = df['blob_bucket'].apply(
            lambda x: f"{int(x.left)}-{int(x.right-1)}" if pd.notna(x) else "Unknown"
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
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8', '#6C5CE7', '#FFD93D', '#A8E6CF']
    
    # Create traces for each group
    for idx, g in enumerate(sorted(df['group_key'].unique())):
        gdf = df[df['group_key'] == g]
        glabel = gdf['group_label'].iloc[0] if not gdf.empty else str(g)
        
        # Calculate p95 for each x value
        agg = gdf.groupby(x_col).agg({
            'head_correctness_pct': lambda x: x.quantile(0.95),
            'slot': 'count'
        }).reset_index()
        agg.rename(columns={'slot': 'sample_count'}, inplace=True)
        
        # Sort by x_order to ensure proper line connection
        agg['sort_key'] = agg[x_col].apply(
            lambda x: x_order.index(x) if x in x_order else -1
        )
        agg = agg[agg['sort_key'] >= 0].sort_values('sort_key')
        
        if not agg.empty:
            fig.add_trace(
                go.Scatter(
                    x=agg[x_col],
                    y=agg['head_correctness_pct'],
                    mode='lines+markers',
                    name=f'{glabel} (p95)',
                    line=dict(color=colors[idx % len(colors)], width=2),
                    marker=dict(size=6),
                    hovertemplate=f'<b>{glabel}</b><br>Blob: %{{x}}<br>p95 Head Correctness: %{{y:.1f}}%<br>Samples: %{{customdata}}<extra></extra>',
                    customdata=agg['sample_count']
                )
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
    
    # Set title based on grouping
    group_names = {
        'node_type': 'Node Type',
        'cl_client': 'CL Client', 
        'el_client': 'EL Client',
        'cl_el_combined': 'CL+EL Combination',
        'cl_node_type': 'CL+Node Type'
    }
    gname = group_names.get(grouping_dimension, grouping_dimension)
    main_title = f'Head Correctness (p95) vs. Blob Count by {gname}'
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

    is_bucketed = num_buckets and num_buckets > 1 and blob_range > num_buckets
    
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
        legend=dict(itemclick='toggle', itemdoubleclick='toggleothers', orientation='v', yanchor='top', y=0.95, xanchor='left', x=1.02, bgcolor='rgba(255,255,255,0.9)', bordercolor='rgba(0,0,0,0.3)', borderwidth=1),
        xaxis=dict(showline=True, linewidth=1, linecolor='black', ticks='outside', title=x_title, type='category' if is_bucketed else 'linear'),
        yaxis=dict(showline=True, linewidth=1, linecolor='black', ticks='outside', title='Head Correctness (%)', range=[0, 100]),
        margin=dict(r=200, t=120, l=80)
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
    attester_filters: Dict[str, Any] = None
) -> go.Figure:
    """Create grouped box plot using real grouped data (no synthetic expansion)."""
    if data.empty:
        return go.Figure()

    if 'blob_count' not in data.columns or 'head_correctness_pct' not in data.columns:
        logger.error("Missing required columns for boxplot: blob_count, head_correctness_pct")
        return go.Figure()

    df = data.copy()
    if 'group_key' not in df.columns:
        df['group_key'] = 'all'
        df['group_label'] = 'All Nodes'
    if 'group_label' not in df.columns:
        df['group_label'] = df['group_key']

    # Calculate bucket size from number of buckets
    max_blobs = int(df['blob_count'].max()) if len(df) else 0
    min_blobs = int(df['blob_count'].min()) if len(df) else 0
    blob_range = max_blobs - min_blobs + 1
    
    if num_buckets and num_buckets > 1 and blob_range > num_buckets:
        bucket_size = int(np.ceil(blob_range / num_buckets))
        edges = np.arange(min_blobs, max_blobs + bucket_size, bucket_size)
        df['blob_bucket'] = pd.cut(df['blob_count'], bins=edges, include_lowest=True, right=False)
        df['blob_bucket_label'] = df['blob_bucket'].apply(lambda x: f"{int(x.left)}-{int(x.right-1)}" if pd.notna(x) else "Unknown")
        x_col = 'blob_bucket_label'
        x_order = sorted(df['blob_bucket_label'].dropna().unique(), key=lambda s: int(str(s).split('-')[0]) if '-' in str(s) else 0)
    else:
        x_col = 'blob_count'
        x_order = sorted(df['blob_count'].dropna().unique())

    fig = go.Figure()
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8', '#6C5CE7', '#FFD93D', '#A8E6CF']
    for idx, g in enumerate(sorted(df['group_key'].unique())):
        gdf = df[df['group_key'] == g]
        glabel = gdf['group_label'].iloc[0] if not gdf.empty else str(g)
        fig.add_trace(
            go.Box(
                x=gdf[x_col],
                y=gdf['head_correctness_pct'],
                name=glabel,
                marker_color=colors[idx % len(colors)],
                boxmean='sd',
                hovertemplate=f'<b>{glabel}</b><br><b>Blob Count</b>: %{{x}}<br>Head Correctness: %{{y:.1f}}%<extra></extra>',
                offsetgroup=str(g)
            )
        )

    group_names = {'node_type': 'Node Type', 'cl_client': 'CL Client', 'el_client': 'EL Client', 'cl_el_combined': 'CL+EL Combination', 'cl_node_type': 'CL+Node Type'}
    gname = group_names.get(grouping_dimension, grouping_dimension)
    title = f'Head Correctness Distribution by {gname}'

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
        legend=dict(itemclick='toggle', itemdoubleclick='toggleothers', orientation='v', yanchor='top', y=0.95, xanchor='left', x=1.02, bgcolor='rgba(255,255,255,0.9)', bordercolor='rgba(0,0,0,0.3)', borderwidth=1),
        xaxis=dict(showline=True, linewidth=1, linecolor='black', ticks='outside', title='Blob Count Buckets' if num_buckets and num_buckets > 1 and blob_range > num_buckets else 'Blob Count', categoryorder='array', categoryarray=x_order),
        yaxis=dict(showline=True, linewidth=1, linecolor='black', ticks='outside', title='Head Correctness (%)', range=[0, 100]),
        margin=dict(r=200, t=120, l=80),
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
    attester_filters: Dict[str, Any] = None
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
    if num_buckets and num_buckets > 1 and blob_range > num_buckets:
        bucket_size = int(np.ceil(blob_range / num_buckets))
        edges = np.arange(min_blobs, max_blobs + bucket_size, bucket_size)
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
    
    # Create violin plots for each group
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8', '#6C5CE7', '#FFD93D', '#A8E6CF']
    
    for idx, g in enumerate(sorted(df['group_key'].unique())):
        gdf = df[df['group_key'] == g]
        glabel = gdf['group_label'].iloc[0] if not gdf.empty else str(g)
        
        # For each x value (blob count or bucket), create a violin
        for x_val in x_order:
            subset = gdf[gdf[x_col] == x_val]
            if not subset.empty:
                fig.add_trace(
                    go.Violin(
                        x=[x_val] * len(subset),
                        y=subset['head_correctness_pct'],
                        name=glabel,
                        legendgroup=glabel,
                        showlegend=(x_val == x_order[0]),  # Only show legend once per group
                        marker_color=colors[idx % len(colors)],
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
    
    # Set title based on grouping
    group_names = {
        'node_type': 'Node Type',
        'cl_client': 'CL Client', 
        'el_client': 'EL Client',
        'cl_el_combined': 'CL+EL Combination',
        'cl_node_type': 'CL+Node Type'
    }
    gname = group_names.get(grouping_dimension, grouping_dimension)
    title = f'Head Correctness Distribution by {gname} (Violin Plot)'
    
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
            title='Blob Count Buckets' if num_buckets and num_buckets > 1 and blob_range > num_buckets else 'Blob Count',
            categoryorder='array',
            categoryarray=x_order
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title='Head Correctness (%)',
            range=[0, 100]
        ),
        margin=dict(r=200, t=120, l=80),
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
    difference_mode: bool = True
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
    if num_buckets and num_buckets > 1 and blob_range > num_buckets:
        bucket_size = int(np.ceil(blob_range / num_buckets))
        edges = np.arange(min_blobs, max_blobs + bucket_size, bucket_size)
        df['blob_bucket'] = pd.cut(df['blob_count'], bins=edges, include_lowest=True, right=False)
        df['blob_bucket_label'] = df['blob_bucket'].apply(
            lambda x: f"{int(x.left)}-{int(x.right-1)}" if pd.notna(x) else "Unknown"
        )
        bucket_col = 'blob_bucket_label'
        bucket_order = sorted(df['blob_bucket_label'].dropna().unique(), 
                            key=lambda s: int(str(s).split('-')[0]) if '-' in str(s) else 0)
    else:
        df['blob_bucket_label'] = df['blob_count'].astype(str)
        bucket_col = 'blob_bucket_label'
        bucket_order = sorted(df['blob_bucket_label'].unique(), key=lambda x: int(x) if x.isdigit() else 0)
    
    fig = go.Figure()
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8', '#6C5CE7', '#FFD93D', '#A8E6CF']
    
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
                                color=colors[group_idx % len(colors)],
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
        'cl_node_type': 'CL+Node Type'
    }
    gname = group_names.get(grouping_dimension, grouping_dimension)
    
    if difference_mode:
        title = f'Difference ECDF: Head Correctness by {gname} and Blob Buckets'
        if reference_label:
            title += f'<br><span style="font-size: 12px; color: #666;">Reference: {reference_label}</span>'
    else:
        title = f'ECDF: Head Correctness by {gname} and Blob Buckets'
    
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
            title='Head Correctness (%)',
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
    inverse: bool = True
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
            attester_filters=attester_filters
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
    attester_filters: Dict[str, Any] = None
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
    if num_buckets and num_buckets > 1 and blob_range > num_buckets:
        bucket_size = int(np.ceil(blob_range / num_buckets))
        edges = np.arange(min_blobs, max_blobs + bucket_size, bucket_size)
        df['blob_bucket'] = pd.cut(df['blob_count'], bins=edges, include_lowest=True, right=False)
        df['blob_bucket_label'] = df['blob_bucket'].apply(
            lambda x: f"{int(x.left)}-{int(x.right-1)}" if pd.notna(x) else "Unknown"
        )
        bucket_col = 'blob_bucket_label'
        bucket_order = sorted(df['blob_bucket_label'].dropna().unique(), 
                            key=lambda s: int(str(s).split('-')[0]) if '-' in str(s) else 0)
    else:
        df['blob_bucket_label'] = df['blob_count'].astype(str)
        bucket_col = 'blob_bucket_label'
        bucket_order = sorted(df['blob_bucket_label'].unique(), key=lambda x: int(x) if x.isdigit() else 0)
    
    fig = go.Figure()
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8', '#6C5CE7', '#FFD93D', '#A8E6CF']
    
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
                                color=colors[group_idx % len(colors)],
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
        'cl_node_type': 'CL+Node Type'
    }
    gname = group_names.get(grouping_dimension, grouping_dimension)
    
    title = f'Quantile Plot: Head Correctness by {gname} and Blob Buckets'
    
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
            title='Head Correctness (%)',
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

