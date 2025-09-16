"""
Plot generation for Reorg Rates Analysis with ethPandaOps branding.

This module creates visualizations for reorg rate analysis, showing
reorganization percentages across different proposer characteristics
and time periods.
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
    node_type = filters.get('proposer_type')
    if node_type == 'supernode':
        parts.append('Supernodes')
    elif node_type == 'regular':
        parts.append('Regular nodes')
    else:
        parts.append('Supernodes + Regular nodes')
    
    # CL clients
    cl_filter = filters.get('proposer_cl')
    if cl_filter and len(cl_filter) < 6:  # Not all CL clients
        cl_str = '+'.join([cl.title() for cl in cl_filter])
        parts.append(f"({cl_str} CL)")
    else:
        parts.append("(All CLs)")
    
    # EL clients  
    el_filter = filters.get('proposer_el')
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


def create_reorg_count_bar_chart(
    data: pd.DataFrame,
    grouping_dimension: Optional[str] = None,
    title_suffix: str = "",
    network: str = "unknown",
    time_range: str = "",
    metadata: Optional[Dict] = None,
    proposer_filters: Optional[Dict] = None
) -> go.Figure:
    """
    Create a bar chart showing reorg counts by group.
    
    This is more appropriate for reorg data than distributions since reorgs are rare events.
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    
    # Calculate reorg counts and rates by group
    if grouping_dimension and 'group_key' in data.columns:
        # Group data
        grouped = data.groupby('group_key').agg({
            'is_reorged': ['sum', 'count', 'mean']
        }).reset_index()
        grouped.columns = ['group_key', 'reorged_count', 'total_blocks', 'reorg_rate']
        grouped['reorg_rate'] = grouped['reorg_rate'] * 100
        
        # Sort by reorg count
        grouped = grouped.sort_values('reorged_count', ascending=False)
    else:
        # Overall stats
        grouped = pd.DataFrame({
            'group_key': ['Overall'],
            'reorged_count': [data['is_reorged'].sum()],
            'total_blocks': [len(data)],
            'reorg_rate': [data['is_reorged'].mean() * 100]
        })
    
    # Create bar chart
    fig = go.Figure()
    
    # Add reorg count bars
    fig.add_trace(go.Bar(
        x=grouped['group_key'],
        y=grouped['reorged_count'],
        name='Reorged Blocks',
        text=grouped['reorged_count'],
        textposition='auto',
        marker=dict(
            color='#FF6B6B'
        ),
        hovertemplate=(
            '<b>%{x}</b><br>' +
            'Reorged Blocks: %{y}<br>' +
            'Total Blocks: %{customdata[0]:,}<br>' +
            'Reorg Rate: %{customdata[1]:.2f}%<br>' +
            '<extra></extra>'
        ),
        customdata=grouped[['total_blocks', 'reorg_rate']].values
    ))
    
    # Update layout
    title = f"Reorg Counts by {grouping_dimension.replace('_', ' ').title() if grouping_dimension else 'Overall'}"
    if network != "unknown":
        title = f"{network.upper()} - {title}"
    title += f" ({time_range})" if time_range else ""
    
    fig.update_layout(
        title=dict(
            text=title + title_suffix,
            x=0,
            xanchor='left',
            font=dict(size=16)
        ),
        xaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title="Group",
            tickangle=-45
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title="Number of Reorged Blocks"
        ),
        showlegend=False,
        height=500,
        margin=dict(b=100, r=200, t=120, l=80),
        hovermode='x unified'
    )
    
    # Add ethpandaops logo
    fig.add_layout_image(dict(
        source='https://ethpandaops.io/img/logo-slim.png',
        xref='paper',
        yref='paper',
        x=0.02,
        y=0.98,
        sizex=0.08,
        sizey=0.08,
        xanchor='left',
        yanchor='top'
    ))
    
    # Add annotation with overall stats
    if metadata:
        total_blocks = metadata.get('total_blocks', 0)
        reorged_blocks = metadata.get('reorged_blocks', 0)
        reorg_rate = (reorged_blocks / total_blocks * 100) if total_blocks > 0 else 0
        
        fig.add_annotation(
            text=f"Overall: {reorged_blocks:,} reorged out of {total_blocks:,} blocks ({reorg_rate:.2f}%)",
            xref="paper", yref="paper",
            x=0.5, y=1.05,
            showarrow=False,
            font=dict(size=12, color="#b0b0b0"),
            align="center"
        )
    
    return fig


def create_reorg_rate_chart(
    data: pd.DataFrame,
    num_buckets: int = 6,
    title_suffix: str = "",
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    show_trend_line: bool = True,
    aggregation_method: str = 'p95',
    grouping_dimension: str = 'node_type',
    proposer_filters: Dict[str, Any] = None
) -> go.Figure:
    """Create reorg rate chart showing aggregated reorg percentage by time buckets with grouping."""
    if data.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available for the selected filters",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=16, color="gray")
        )
        fig.update_layout(
            title=f"Reorg Rates{title_suffix}",
            showlegend=False,
            height=400
        )
        return fig

    # Convert slot_start_date_time to datetime if it's a string
    if 'slot_start_date_time' in data.columns:
        data['slot_start_date_time'] = pd.to_datetime(data['slot_start_date_time'])
    
    # Check if we have grouping
    if 'group_key' in data.columns and 'group_label' in data.columns:
        # Grouped data
        groups = data['group_label'].unique()
        
        # Create time buckets
        time_col = 'slot_start_date_time' if 'slot_start_date_time' in data.columns else 'slot'
        if time_col == 'slot_start_date_time':
            min_time = data[time_col].min()
            max_time = data[time_col].max()
            time_bins = pd.date_range(start=min_time, end=max_time, periods=num_buckets + 1)
            data['time_bucket'] = pd.cut(data[time_col], bins=time_bins, labels=False, include_lowest=True)
            data['time_bucket_label'] = pd.cut(data[time_col], bins=time_bins, include_lowest=True)
            data['time_bucket_mid'] = data['time_bucket_label'].apply(lambda x: x.mid if pd.notna(x) else None)
        else:
            # Use slot numbers
            min_slot = data['slot'].min()
            max_slot = data['slot'].max()
            slot_bins = np.linspace(min_slot, max_slot, num_buckets + 1)
            data['time_bucket'] = pd.cut(data['slot'], bins=slot_bins, labels=False, include_lowest=True)
            data['time_bucket_mid'] = pd.cut(data['slot'], bins=slot_bins, include_lowest=True).apply(lambda x: x.mid if pd.notna(x) else None)
        
        # Calculate reorg rates by group and time bucket
        agg_data = []
        for group in groups:
            group_data = data[data['group_label'] == group]
            for bucket in range(num_buckets):
                bucket_data = group_data[group_data['time_bucket'] == bucket]
                if len(bucket_data) > 0:
                    reorg_rate = (bucket_data['is_reorged'].sum() / len(bucket_data)) * 100
                    time_point = bucket_data['time_bucket_mid'].iloc[0] if not bucket_data['time_bucket_mid'].isna().all() else bucket
                    
                    agg_data.append({
                        'group': group,
                        'time_bucket': bucket,
                        'time_point': time_point,
                        'reorg_rate': reorg_rate,
                        'total_blocks': len(bucket_data),
                        'reorged_blocks': bucket_data['is_reorged'].sum()
                    })
        
        agg_df = pd.DataFrame(agg_data)
        
        # Create figure
        fig = go.Figure()
        
        # Color palette for groups
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']
        
        for i, group in enumerate(groups):
            group_data = agg_df[agg_df['group'] == group]
            if not group_data.empty:
                color = colors[i % len(colors)]
                
                # Add scatter plot for each group
                fig.add_trace(go.Scatter(
                    x=group_data['time_point'] if time_col == 'slot_start_date_time' else group_data['time_bucket'],
                    y=group_data['reorg_rate'],
                    mode='lines+markers',
                    name=group,
                    line=dict(color=color, width=2),
                    marker=dict(color=color, size=6),
                    hovertemplate=f"""<b>{group}</b><br>""" +
                                  "Time: %{x}<br>" +
                                  "Reorg Rate: %{y:.2f}%<br>" +
                                  "Total Blocks: %{customdata[0]}<br>" +
                                  "Reorged Blocks: %{customdata[1]}<extra></extra>",
                    customdata=group_data[['total_blocks', 'reorged_blocks']].values
                ))
                
                # Add trend line if requested
                if show_trend_line and len(group_data) > 1:
                    try:
                        x_vals = range(len(group_data)) if time_col != 'slot_start_date_time' else group_data['time_bucket'].values
                        z = np.polyfit(x_vals, group_data['reorg_rate'], 1)
                        p = np.poly1d(z)
                        trend_x = group_data['time_point'] if time_col == 'slot_start_date_time' else group_data['time_bucket']
                        fig.add_trace(go.Scatter(
                            x=trend_x,
                            y=p(x_vals),
                            mode='lines',
                            name=f'{group} Trend',
                            line=dict(color=color, width=1, dash='dash'),
                            showlegend=False,
                            hoverinfo='skip'
                        ))
                    except Exception as e:
                        logger.debug(f"Could not add trend line for {group}: {e}")
    else:
        # Non-grouped data - overall reorg rates over time
        time_col = 'slot_start_date_time' if 'slot_start_date_time' in data.columns else 'slot'
        if time_col == 'slot_start_date_time':
            min_time = data[time_col].min()
            max_time = data[time_col].max()
            time_bins = pd.date_range(start=min_time, end=max_time, periods=num_buckets + 1)
            data['time_bucket'] = pd.cut(data[time_col], bins=time_bins, labels=False, include_lowest=True)
            data['time_bucket_label'] = pd.cut(data[time_col], bins=time_bins, include_lowest=True)
            data['time_bucket_mid'] = data['time_bucket_label'].apply(lambda x: x.mid if pd.notna(x) else None)
        else:
            min_slot = data['slot'].min()
            max_slot = data['slot'].max()
            slot_bins = np.linspace(min_slot, max_slot, num_buckets + 1)
            data['time_bucket'] = pd.cut(data['slot'], bins=slot_bins, labels=False, include_lowest=True)
            data['time_bucket_mid'] = pd.cut(data['slot'], bins=slot_bins, include_lowest=True).apply(lambda x: x.mid if pd.notna(x) else None)
        
        # Calculate reorg rates by time bucket
        agg_data = []
        for bucket in range(num_buckets):
            bucket_data = data[data['time_bucket'] == bucket]
            if len(bucket_data) > 0:
                reorg_rate = (bucket_data['is_reorged'].sum() / len(bucket_data)) * 100
                time_point = bucket_data['time_bucket_mid'].iloc[0] if not bucket_data['time_bucket_mid'].isna().all() else bucket
                
                agg_data.append({
                    'time_bucket': bucket,
                    'time_point': time_point,
                    'reorg_rate': reorg_rate,
                    'total_blocks': len(bucket_data),
                    'reorged_blocks': bucket_data['is_reorged'].sum()
                })
        
        agg_df = pd.DataFrame(agg_data)
        
        # Create figure
        fig = go.Figure()
        
        # Add main trace
        fig.add_trace(go.Scatter(
            x=agg_df['time_point'] if time_col == 'slot_start_date_time' else agg_df['time_bucket'],
            y=agg_df['reorg_rate'],
            mode='lines+markers',
            name='Reorg Rate',
            line=dict(color='#1f77b4', width=3),
            marker=dict(color='#1f77b4', size=8),
            hovertemplate="Time: %{x}<br>" +
                          "Reorg Rate: %{y:.2f}%<br>" +
                          "Total Blocks: %{customdata[0]}<br>" +
                          "Reorged Blocks: %{customdata[1]}<extra></extra>",
            customdata=agg_df[['total_blocks', 'reorged_blocks']].values
        ))
        
        # Add trend line if requested
        if show_trend_line and len(agg_df) > 1:
            try:
                x_vals = range(len(agg_df)) if time_col != 'slot_start_date_time' else agg_df['time_bucket'].values
                z = np.polyfit(x_vals, agg_df['reorg_rate'], 1)
                p = np.poly1d(z)
                trend_x = agg_df['time_point'] if time_col == 'slot_start_date_time' else agg_df['time_bucket']
                fig.add_trace(go.Scatter(
                    x=trend_x,
                    y=p(x_vals),
                    mode='lines',
                    name='Trend',
                    line=dict(color='red', width=2, dash='dash'),
                    hoverinfo='skip'
                ))
            except Exception as e:
                logger.debug(f"Could not add trend line: {e}")
    
    # Build title
    title_parts = [f"Reorg Rates{title_suffix}"]
    if network:
        title_parts.append(f" - {network.title()}")
    if time_range:
        title_parts.append(f" ({time_range})")
    
    title = "".join(title_parts)
    
    # Build subtitle with filter info
    subtitle_parts = []
    if proposer_filters:
        proposer_desc = _format_filter_description("Proposers", proposer_filters)
        subtitle_parts.append(proposer_desc)
    
    if metadata and 'mev_filter' in metadata and metadata['mev_filter'] != 'both':
        mev_desc = 'MEV Relay' if metadata['mev_filter'] == 'yes' else 'Local Build'
        subtitle_parts.append(f"Block Building: {mev_desc}")
    
    subtitle = " | ".join(subtitle_parts) if subtitle_parts else None
    
    # Update layout
    fig.update_layout(
        title=dict(
            text=title + (f"<br><sub>{subtitle}</sub>" if subtitle else ""),
            x=0,
            xanchor='left',
            font=dict(size=16)
        ),
        xaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title="Time" if time_col == 'slot_start_date_time' else "Time Bucket"
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title="Reorg Rate (%)",
            range=[0, max(5, data['is_reorged'].mean() * 100 * 1.2) if not data.empty else 5],  # Start from 0, expected low values
            ticksuffix="%"
        ),
        height=500,
        hovermode='closest',
        showlegend=True,
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
        margin=dict(r=200, t=120, l=80)
    )
    
    # Add ethpandaops logo
    fig.add_layout_image(dict(
        source='https://ethpandaops.io/img/logo-slim.png',
        xref='paper',
        yref='paper',
        x=0.02,
        y=0.98,
        sizex=0.08,
        sizey=0.08,
        xanchor='left',
        yanchor='top'
    ))
    
    return fig


def create_reorg_rate_boxplot(
    data: pd.DataFrame,
    grouping_dimension: str = 'node_type',
    title_suffix: str = "",
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    proposer_filters: Dict[str, Any] = None
) -> go.Figure:
    """Create box plot showing reorg rate distribution by groups."""
    if data.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available for the selected filters",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=16, color="gray")
        )
        fig.update_layout(title=f"Reorg Rates Box Plot{title_suffix}")
        return fig
    
    fig = go.Figure()
    
    # Calculate reorg rates per slot for each group
    if 'group_key' in data.columns and 'group_label' in data.columns:
        groups = data['group_label'].unique()
        
        for group in groups:
            group_data = data[data['group_label'] == group]
            # Calculate reorg rate per slot within this group
            slot_reorg_rates = group_data.groupby('slot')['is_reorged'].mean() * 100
            
            fig.add_trace(go.Box(
                y=slot_reorg_rates,
                name=group,
                boxpoints='outliers',
                hovertemplate=f"<b>{group}</b><br>" +
                              "Reorg Rate: %{y:.2f}%<extra></extra>"
            ))
    else:
        # No grouping - show overall distribution
        slot_reorg_rates = data.groupby('slot')['is_reorged'].mean() * 100
        
        fig.add_trace(go.Box(
            y=slot_reorg_rates,
            name='All Proposers',
            boxpoints='outliers',
            hovertemplate="Reorg Rate: %{y:.2f}%<extra></extra>"
        ))
    
    # Build title
    title_parts = [f"Reorg Rates Distribution{title_suffix}"]
    if network:
        title_parts.append(f" - {network.title()}")
    if time_range:
        title_parts.append(f" ({time_range})")
    
    title = "".join(title_parts)
    
    # Build subtitle
    subtitle_parts = []
    if proposer_filters:
        proposer_desc = _format_filter_description("Proposers", proposer_filters)
        subtitle_parts.append(proposer_desc)
    
    subtitle = " | ".join(subtitle_parts) if subtitle_parts else None
    
    fig.update_layout(
        title=dict(
            text=title + (f"<br><sub>{subtitle}</sub>" if subtitle else ""),
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
            ticks='outside'
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title="Reorg Rate (%)",
            ticksuffix="%"
        ),
        margin=dict(r=200, t=120, l=80),
        boxmode='group'
    )
    
    # Add ethpandaops logo
    fig.add_layout_image(dict(
        source='https://ethpandaops.io/img/logo-slim.png',
        xref='paper',
        yref='paper',
        x=0.02,
        y=0.98,
        sizex=0.08,
        sizey=0.08,
        xanchor='left',
        yanchor='top'
    ))
    
    return fig


def create_reorg_rate_violin(
    data: pd.DataFrame,
    grouping_dimension: str = 'node_type',
    title_suffix: str = "",
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    proposer_filters: Dict[str, Any] = None
) -> go.Figure:
    """Create violin plot showing reorg rate distribution by groups."""
    if data.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available for the selected filters",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=16, color="gray")
        )
        fig.update_layout(title=f"Reorg Rates Violin Plot{title_suffix}")
        return fig
    
    fig = go.Figure()
    
    # Calculate reorg rates per slot for each group
    if 'group_key' in data.columns and 'group_label' in data.columns:
        groups = data['group_label'].unique()
        
        for group in groups:
            group_data = data[data['group_label'] == group]
            # Calculate reorg rate per slot within this group
            slot_reorg_rates = group_data.groupby('slot')['is_reorged'].mean() * 100
            
            fig.add_trace(go.Violin(
                y=slot_reorg_rates,
                name=group,
                box_visible=True,
                meanline_visible=True,
                hovertemplate=f"<b>{group}</b><br>" +
                              "Reorg Rate: %{y:.2f}%<extra></extra>"
            ))
    else:
        # No grouping - show overall distribution
        slot_reorg_rates = data.groupby('slot')['is_reorged'].mean() * 100
        
        fig.add_trace(go.Violin(
            y=slot_reorg_rates,
            name='All Proposers',
            box_visible=True,
            meanline_visible=True,
            hovertemplate="Reorg Rate: %{y:.2f}%<extra></extra>"
        ))
    
    # Build title
    title_parts = [f"Reorg Rates Distribution{title_suffix}"]
    if network:
        title_parts.append(f" - {network.title()}")
    if time_range:
        title_parts.append(f" ({time_range})")
    
    title = "".join(title_parts)
    
    # Build subtitle
    subtitle_parts = []
    if proposer_filters:
        proposer_desc = _format_filter_description("Proposers", proposer_filters)
        subtitle_parts.append(proposer_desc)
    
    subtitle = " | ".join(subtitle_parts) if subtitle_parts else None
    
    fig.update_layout(
        title=dict(
            text=title + (f"<br><sub>{subtitle}</sub>" if subtitle else ""),
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
            ticks='outside'
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title="Reorg Rate (%)",
            ticksuffix="%"
        ),
        margin=dict(r=200, t=120, l=80),
        boxmode='group'
    )
    
    # Add ethpandaops logo
    fig.add_layout_image(dict(
        source='https://ethpandaops.io/img/logo-slim.png',
        xref='paper',
        yref='paper',
        x=0.02,
        y=0.98,
        sizex=0.08,
        sizey=0.08,
        xanchor='left',
        yanchor='top'
    ))
    
    return fig


def create_advanced_grouped_boxplot(
    data: pd.DataFrame,
    grouping_dimension: str = 'node_type',
    title_suffix: str = "",
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    proposer_filters: Dict[str, Any] = None
) -> go.Figure:
    """Create advanced grouped box plot with statistical annotations."""
    return create_reorg_rate_boxplot(
        data=data,
        grouping_dimension=grouping_dimension,
        title_suffix=" - Advanced" + title_suffix,
        network=network,
        time_range=time_range,
        metadata=metadata,
        proposer_filters=proposer_filters
    )


def create_reorg_rate_ecdf(
    data: pd.DataFrame,
    grouping_dimension: str = 'node_type',
    title_suffix: str = "",
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    proposer_filters: Dict[str, Any] = None
) -> go.Figure:
    """Create Empirical Cumulative Distribution Function plot for reorg rates."""
    if data.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available for the selected filters",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=16, color="gray")
        )
        fig.update_layout(title=f"Reorg Rates ECDF{title_suffix}")
        return fig
    
    fig = go.Figure()
    
    if 'group_key' in data.columns and 'group_label' in data.columns:
        groups = data['group_label'].unique()
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']
        
        for i, group in enumerate(groups):
            group_data = data[data['group_label'] == group]
            # Calculate reorg rate per slot within this group
            slot_reorg_rates = group_data.groupby('slot')['is_reorged'].mean() * 100
            
            # Calculate ECDF
            sorted_rates = np.sort(slot_reorg_rates)
            ecdf_y = np.arange(1, len(sorted_rates) + 1) / len(sorted_rates)
            
            color = colors[i % len(colors)]
            fig.add_trace(go.Scatter(
                x=sorted_rates,
                y=ecdf_y,
                mode='lines+markers',
                name=group,
                line=dict(color=color, width=2),
                marker=dict(color=color, size=4),
                hovertemplate=f"<b>{group}</b><br>" +
                              "Reorg Rate: %{x:.2f}%<br>" +
                              "Cumulative Probability: %{y:.2f}<extra></extra>"
            ))
    else:
        # No grouping
        slot_reorg_rates = data.groupby('slot')['is_reorged'].mean() * 100
        
        sorted_rates = np.sort(slot_reorg_rates)
        ecdf_y = np.arange(1, len(sorted_rates) + 1) / len(sorted_rates)
        
        fig.add_trace(go.Scatter(
            x=sorted_rates,
            y=ecdf_y,
            mode='lines+markers',
            name='All Proposers',
            line=dict(color='#1f77b4', width=2),
            marker=dict(color='#1f77b4', size=4),
            hovertemplate="Reorg Rate: %{x:.2f}%<br>" +
                          "Cumulative Probability: %{y:.2f}<extra></extra>"
        ))
    
    # Build title
    title_parts = [f"Reorg Rates ECDF{title_suffix}"]
    if network:
        title_parts.append(f" - {network.title()}")
    if time_range:
        title_parts.append(f" ({time_range})")
    
    title = "".join(title_parts)
    
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
            title="Reorg Rate (%)",
            ticksuffix="%"
        ),
        yaxis=dict(
            showline=True,
            linewidth=1,
            linecolor='black',
            ticks='outside',
            title="Cumulative Probability"
        ),
        margin=dict(r=200, t=120, l=80)
    )
    
    # Add ethpandaops logo
    fig.add_layout_image(dict(
        source='https://ethpandaops.io/img/logo-slim.png',
        xref='paper',
        yref='paper',
        x=0.02,
        y=0.98,
        sizex=0.08,
        sizey=0.08,
        xanchor='left',
        yanchor='top'
    ))
    
    return fig


def create_reorg_rate_cdf(
    data: pd.DataFrame,
    grouping_dimension: str = 'node_type',
    title_suffix: str = "",
    network: str = None,
    time_range: str = None,
    metadata: Dict[str, Any] = None,
    proposer_filters: Dict[str, Any] = None
) -> go.Figure:
    """Create Cumulative Distribution Function plot for reorg rates."""
    # For this use case, CDF is the same as ECDF
    return create_reorg_rate_ecdf(
        data=data,
        grouping_dimension=grouping_dimension,
        title_suffix=" - CDF" + title_suffix,
        network=network,
        time_range=time_range,
        metadata=metadata,
        proposer_filters=proposer_filters
    )