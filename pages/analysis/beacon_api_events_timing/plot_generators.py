"""
Plot generators for Beacon API Events Timing.

Provides a minimal set of visuals similar to peerdas v2: a time-series
summary with quantiles and grouped box plots for proposer/attester views.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, Any, List
import numpy as np
import plotly.express as px


def _get_color_palette(n_colors: int) -> List[str]:
    """Generate a consistent color palette for node groups using Plotly colors."""
    if n_colors <= 0:
        return []

    # Use Plotly's qualitative color sequences for consistent, distinguishable colors
    # These are designed to be visually distinct and colorblind-friendly
    if n_colors <= 10:
        # Use Plotly's default color sequence (D3 categorical)
        return px.colors.qualitative.Plotly[:n_colors]
    elif n_colors <= 24:
        # Use extended color palette
        return px.colors.qualitative.Dark24[:n_colors]
    else:
        # For very large numbers, cycle through multiple palettes
        colors = []
        palettes = [
            px.colors.qualitative.Plotly,
            px.colors.qualitative.Dark24,
            px.colors.qualitative.Light24,
        ]
        palette_idx = 0
        color_idx = 0

        for _ in range(n_colors):
            colors.append(palettes[palette_idx][color_idx])
            color_idx += 1
            if color_idx >= len(palettes[palette_idx]):
                color_idx = 0
                palette_idx = (palette_idx + 1) % len(palettes)

        return colors


def apply_blob_bucketing(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """Apply blob count bucketing to the DataFrame if enabled."""
    if not config.get('enable_blob_bucketing', False) or 'blob_count' not in df.columns:
        return df

    # Filter out rows with missing or invalid blob_count data
    original_count = len(df)
    df = df[df['blob_count'].notna() & (df['blob_count'] >= 0)].copy()

    # Filter zero blob slots if enabled
    if config.get('filter_zero_blobs', True):
        df = df[df['blob_count'] > 0].copy()
        filtered_count = len(df)
        if original_count > filtered_count:
            st.info(f"🗂️ Filtered out {original_count - filtered_count:,} slots with null/zero blobs ({(original_count - filtered_count)/original_count*100:.1f}%)")

    if df.empty:
        return df

    num_buckets = config.get('num_buckets', 6)
    max_blobs = int(df['blob_count'].max())
    min_blobs = int(df['blob_count'].min())
    blob_range = max_blobs - min_blobs + 1

    if num_buckets == 1:
        # Single bucket for all blob counts
        df['blob_bucket_label'] = 'All'
        df['blob_bucket_sort_key'] = 0
    elif blob_range <= num_buckets:
        # Show individual blob counts if fewer than buckets requested
        df['blob_bucket_label'] = df['blob_count'].astype(str)
        df['blob_bucket_sort_key'] = df['blob_count']
    else:
        # Create non-overlapping integer buckets
        bucket_size = blob_range // num_buckets
        remainder = blob_range % num_buckets

        edges = []
        current = min_blobs
        for i in range(num_buckets):
            edges.append(current)
            # Distribute remainder across first buckets
            current += bucket_size + (1 if i < remainder else 0)
        edges.append(max_blobs + 1)

        df['blob_bucket'] = pd.cut(df['blob_count'], bins=edges, include_lowest=True, right=False)
        df['blob_bucket_label'] = df['blob_bucket'].apply(
            lambda x: f"{int(x.left)}-{int(x.right-1)}" if pd.notna(x) else "Unknown"
        )
        # Add sort key based on the left edge of the bucket
        df['blob_bucket_sort_key'] = df['blob_bucket'].apply(
            lambda x: int(x.left) if pd.notna(x) else 999
        )

    return df


def filter_outliers(df: pd.DataFrame, value_column: str, config: Dict[str, Any]) -> pd.DataFrame:
    """Filter outliers from a DataFrame based on the specified method."""
    if df.empty or value_column not in df.columns:
        return df

    outlier_method = config.get('outlier_method', 'none')

    if outlier_method == 'none':
        return df

    values = df[value_column]

    if outlier_method == 'iqr':
        # IQR method: remove values beyond 1.5 * IQR from Q1/Q3
        q1 = values.quantile(0.25)
        q3 = values.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        mask = (values >= lower_bound) & (values <= upper_bound)

    elif outlier_method == 'percentile':
        # Percentile capping
        percentile = config.get('outlier_percentile', 95)
        upper_bound = values.quantile(percentile / 100)
        mask = values <= upper_bound

    elif outlier_method == 'zscore':
        # Z-score method
        threshold = config.get('zscore_threshold', 3.0)
        z_scores = np.abs((values - values.mean()) / values.std())
        mask = z_scores <= threshold

    else:
        return df

    filtered_df = df[mask].copy()

    # Add summary info about filtering
    original_count = len(df)
    filtered_count = len(filtered_df)
    removed_count = original_count - filtered_count

    if removed_count > 0:
        st.info(f"🔍 Outlier filtering removed {removed_count:,} data points ({removed_count/original_count*100:.1f}%) using {outlier_method} method. Showing {filtered_count:,} points.")

    return filtered_df


def render_data_summary(data: Dict[str, Any], config: Dict[str, Any]):
    """Render detailed data summary section with metrics and information."""

    time_series_df = data.get('time_series', pd.DataFrame())
    samples_df = data.get('samples', pd.DataFrame())

    with st.expander("📊 Data Summary", expanded=True):
        # First row of metrics
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "Data Source",
                config.get('data_source', 'unknown').title(),
                help="Source of timing data: Beacon API events or LibP2P Gossipsub messages"
            )

        with col2:
            st.metric(
                "Event Type",
                config.get('event_type', 'unknown').replace('_', ' ').title(),
                help="Type of blockchain event being analyzed"
            )

        with col3:
            time_points = len(time_series_df) if not time_series_df.empty else 0
            st.metric(
                "Time Series Points",
                f"{time_points:,}",
                help="Number of 5-minute time buckets with data"
            )

        with col4:
            sample_count = len(samples_df) if not samples_df.empty else 0
            st.metric(
                "Sample Count",
                f"{sample_count:,}",
                help="Number of individual event timing measurements"
            )

        # Second row with timing and filtering info
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            if not samples_df.empty and 'diff_ms' in samples_df.columns:
                avg_timing = samples_df['diff_ms'].mean()
                st.metric(
                    "Avg Timing",
                    f"{avg_timing:.1f}ms",
                    help="Average event timing across all samples"
                )

        with col2:
            if not samples_df.empty and 'diff_ms' in samples_df.columns:
                p95_timing = samples_df['diff_ms'].quantile(0.95)
                st.metric(
                    "P95 Timing",
                    f"{p95_timing:.1f}ms",
                    help="95th percentile event timing"
                )

        with col3:
            st.metric(
                "Sample Rate",
                f"{config.get('sample_rate', 100)}%",
                help="Percentage of data sampled to manage performance"
            )

        with col4:
            st.metric(
                "Max Records",
                f"{config.get('max_records', 0):,}",
                help="Maximum number of records returned"
            )

        # Time range and slot information
        if not samples_df.empty and 'slot' in samples_df.columns:
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                min_slot = samples_df['slot'].min()
                st.metric(
                    "Min Slot",
                    f"{min_slot:,}",
                    help="Earliest slot in the analyzed data"
                )

            with col2:
                max_slot = samples_df['slot'].max()
                st.metric(
                    "Max Slot",
                    f"{max_slot:,}",
                    help="Latest slot in the analyzed data"
                )

            with col3:
                slot_range = max_slot - min_slot + 1
                st.metric(
                    "Slot Range",
                    f"{slot_range:,}",
                    help="Total range of slots covered"
                )

            with col4:
                coverage = (len(samples_df['slot'].unique()) / slot_range * 100) if slot_range > 0 else 0
                st.metric(
                    "Coverage",
                    f"{coverage:.1f}%",
                    help="Percentage of slots in range with data"
                )

        # Grouping and Bucketing information
        grouping_info = []
        if config.get('proposer_grouping', 'none') != 'none':
            grouping_info.append(f"**Proposer Grouping:** {config.get('proposer_grouping', 'none').replace('_', ' ').title()}")
        if config.get('receiver_grouping', 'none') != 'none':
            grouping_info.append(f"**Event Receiver Grouping:** {config.get('receiver_grouping', 'none').replace('_', ' ').title()}")

        blob_bucketing_info = []
        if config.get('enable_blob_bucketing', False):
            blob_bucketing_info.append(f"**Blob Bucketing:** Enabled ({config.get('num_buckets', 6)} buckets)")
            if config.get('filter_zero_blobs', False):
                blob_bucketing_info.append("**Zero Blob Filter:** Enabled")

        if grouping_info or blob_bucketing_info:
            st.markdown("### 🔍 Analysis Configuration")

            if grouping_info:
                col1, col2 = st.columns(2)
                for idx, info in enumerate(grouping_info):
                    with col1 if idx == 0 else col2:
                        st.info(info)

            if blob_bucketing_info:
                st.markdown("#### 🗂️ Blob Count Bucketing")
                for info in blob_bucketing_info:
                    st.info(info)

                # Show blob count distribution if available
                if not samples_df.empty and 'blob_count' in samples_df.columns:
                    st.markdown("#### 📊 Blob Count Distribution")
                    blob_stats = samples_df['blob_count'].value_counts().sort_index()

                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Blob Count Summary:**")
                        st.dataframe(blob_stats.to_frame('Count'), use_container_width=True)

                    with col2:
                        blob_summary = {
                            'Min Blobs': int(samples_df['blob_count'].min()),
                            'Max Blobs': int(samples_df['blob_count'].max()),
                            'Avg Blobs': round(samples_df['blob_count'].mean(), 2),
                            'Total Slots': len(samples_df['blob_count'].unique()),
                            'Total Records': len(samples_df)
                        }
                        st.markdown("**Statistics:**")
                        for key, value in blob_summary.items():
                            st.metric(key, value)

        # Filter information
        proposer_filters = config.get('proposer_filters', {})
        receiver_filters = config.get('receiver_filters', {})

        active_filters = []
        for filter_type, filters in [("Proposer", proposer_filters), ("Event Receiver", receiver_filters)]:
            for key, value in filters.items():
                if value and value != ['all']:
                    if isinstance(value, list):
                        active_filters.append(f"{filter_type} {key.replace('_', ' ')}: {', '.join(value)}")
                    else:
                        active_filters.append(f"{filter_type} {key.replace('_', ' ')}: {value}")

        if active_filters:
            st.markdown("### 🎯 Active Filters")
            for filter_desc in active_filters:
                st.info(filter_desc)


def render_time_series_summary(data: dict, config: Dict[str, Any] = None):
    df: pd.DataFrame = data.get('time_series', pd.DataFrame())
    if df.empty or 'time' not in df.columns:
        st.info("No time series data available for selection.")
        return

    fig = go.Figure()
    colors = {"average": "#1f77b4", "p50": "#ff7f0e", "p95": "#d62728"}

    for col, name in [("average", "avg"), ("p50", "p50"), ("p95", "p95")]:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df['time'],
                y=df[col],
                mode='lines+markers',
                name=name,
                line=dict(color=colors.get(col, "#2ca02c"), width=2),
                marker=dict(size=4)
            ))

    # Add data source and configuration annotations
    data_source = config.get('data_source', 'unknown') if config else 'unknown'
    event_type = config.get('event_type', 'unknown') if config else 'unknown'
    sample_rate = config.get('sample_rate', 100) if config else 100

    # Calculate some basic stats for annotation
    total_points = len(df)
    if not df.empty and 'average' in df.columns:
        avg_value = df['average'].mean()
        annotation_text = f"Data: {data_source.title()} | Event: {event_type.replace('_', ' ').title()}<br>"
        annotation_text += f"Points: {total_points:,} | Sample Rate: {sample_rate}% | Avg: {avg_value:.1f}ms"
    else:
        annotation_text = f"Data: {data_source.title()} | Event: {event_type.replace('_', ' ').title()}<br>"
        annotation_text += f"Points: {total_points:,} | Sample Rate: {sample_rate}%"

    fig.add_annotation(
        x=0.02,
        y=0.98,
        xref="paper",
        yref="paper",
        text=annotation_text,
        showarrow=False,
        font=dict(size=10, color="gray"),
        bgcolor="rgba(255,255,255,0.8)",
        bordercolor="gray",
        borderwidth=1,
        align="left"
    )

    fig.update_layout(
        title="Event Timing Over Time",
        xaxis_title="Time (UTC)",
        yaxis_title="Timing (ms)",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        margin=dict(t=60, r=10, b=20, l=10),
        hovermode='x unified'
    )
    st.plotly_chart(fig, use_container_width=True)


def _build_boxplot(df: pd.DataFrame, group_col: str, title: str, config: Dict[str, Any] = None):
    if df.empty or group_col not in df.columns:
        st.info(f"No data for {title}.")
        return

    # Apply outlier filtering if configured
    if config and config.get('outlier_method', 'none') != 'none':
        df = filter_outliers(df, 'diff_ms', config)
        if df.empty:
            st.warning("All data was filtered out by outlier removal.")
            return

    # Determine boxplot outlier display
    show_outliers = config.get('show_outliers_toggle', False) if config else False
    boxpoints = 'outliers' if show_outliers else False

    # Plotly box needs y values per group - filter out empty strings and unknowns
    groups = df[group_col].dropna().unique().tolist()
    groups = [g for g in groups if g and str(g).strip() and str(g).strip().lower() not in ['', 'unknown', 'null', 'none']]

    if not groups:
        st.info(f"No valid groups found for {title} after filtering empty values.")
        return

    # Sort groups for blob bucket analysis
    if group_col == 'blob_bucket_label' and 'blob_bucket_sort_key' in df.columns:
        # Create a mapping of label to sort key for blob buckets
        label_to_sort = df.groupby('blob_bucket_label')['blob_bucket_sort_key'].first().to_dict()
        groups = sorted(groups, key=lambda x: label_to_sort.get(x, 999))
    else:
        # Sort alphabetically for other group types
        groups = sorted(groups)

    # Add interactive legend instructions
    st.info("💡 **Interactive Legend**: Click legend items to show/hide groups. Double-click to show only one group.")

    fig = go.Figure()

    for g in groups:
        vals = df.loc[df[group_col] == g, 'diff_ms']
        if not vals.empty:
            fig.add_trace(go.Box(
                y=vals,
                name=str(g),
                boxpoints=boxpoints,
                jitter=0.3,
                hovertemplate=f"Group: {g}<br>Value: %{{y:.1f}}ms<br>Count: {len(vals):,}<extra></extra>"
            ))

    # Add sample count annotations
    for idx, g in enumerate(groups):
        vals = df.loc[df[group_col] == g, 'diff_ms']
        if not vals.empty:
            fig.add_annotation(
                x=idx,
                y=vals.min() - (vals.max() - vals.min()) * 0.1,
                text=f"n={len(vals):,}",
                showarrow=False,
                font=dict(size=9, color="gray"),
                yshift=-10
            )

    # Add data source annotation
    if config:
        data_source = config.get('data_source', 'unknown')
        event_type = config.get('event_type', 'unknown')
        annotation_text = f"Data: {data_source.title()} | Event: {event_type.replace('_', ' ').title()}"

        fig.add_annotation(
            x=0.02,
            y=0.98,
            xref="paper",
            yref="paper",
            text=annotation_text,
            showarrow=False,
            font=dict(size=9, color="gray"),
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="gray",
            borderwidth=1,
            align="left"
        )

    fig.update_layout(
        title=title,
        yaxis_title="Timing (ms)",
        margin=dict(t=60, r=50, b=40, l=10),  # More right margin for legend
        showlegend=True,  # Enable interactive legend
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,  # Position legend to the right
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="rgba(0,0,0,0.2)",
            borderwidth=1
        ),
        hovermode='closest'
    )
    st.plotly_chart(fig, use_container_width=True)


def _build_combined_boxplot(df: pd.DataFrame, group_col: str, sort_col: str, title: str, config: Dict[str, Any] = None):
    """Build boxplot with blob buckets grouped together, with visual spacing between bucket groups."""
    if df.empty or group_col not in df.columns:
        st.info(f"No data for {title}.")
        return

    # Apply outlier filtering if configured
    if config and config.get('outlier_method', 'none') != 'none':
        df = filter_outliers(df, 'diff_ms', config)
        if df.empty:
            st.warning("All data was filtered out by outlier removal.")
            return

    # Determine boxplot outlier display
    show_outliers = config.get('show_outliers_toggle', False) if config else False
    boxpoints = 'outliers' if show_outliers else False

    # Get unique groups and filter out empty/unknown values
    groups = df[group_col].dropna().unique().tolist()
    groups = [g for g in groups if g and str(g).strip() and str(g).strip().lower() not in ['', 'unknown', 'null', 'none']]

    if not groups:
        st.info(f"No valid groups found for {title} after filtering empty values.")
        return

    # Extract blob buckets and node groups from combined labels
    blob_bucket_to_node_groups = {}
    blob_bucket_to_sort_key = {}
    all_node_groups = set()

    for g in groups:
        if ' blobs: ' in g:
            parts = g.split(' blobs: ')
            blob_bucket = parts[0]
            node_group = parts[1]

            if blob_bucket not in blob_bucket_to_node_groups:
                blob_bucket_to_node_groups[blob_bucket] = []
            blob_bucket_to_node_groups[blob_bucket].append(node_group)
            all_node_groups.add(node_group)

            # Get sort key for this blob bucket
            if 'blob_bucket_sort_key' in df.columns:
                group_data = df[df[group_col] == g]
                if not group_data.empty:
                    blob_bucket_to_sort_key[blob_bucket] = group_data['blob_bucket_sort_key'].iloc[0]

    # Sort blob buckets by their sort key
    blob_buckets = sorted(blob_bucket_to_node_groups.keys(), key=lambda x: blob_bucket_to_sort_key.get(x, 999))

    # Sort node groups within each blob bucket alphabetically
    for blob_bucket in blob_buckets:
        blob_bucket_to_node_groups[blob_bucket] = sorted(blob_bucket_to_node_groups[blob_bucket])

    # Create color palette for node groups (consistent across blob buckets)
    all_node_groups = sorted(list(all_node_groups))
    color_palette = _get_color_palette(len(all_node_groups))
    node_group_colors = {node_group: color_palette[i] for i, node_group in enumerate(all_node_groups)}

    # Create x-axis positions with gaps between blob bucket groups
    fig = go.Figure()
    x_position = 0
    x_tick_positions = []
    x_tick_labels = []
    gap_between_buckets = 1.5  # Gap between different blob bucket groups
    gap_within_bucket = 0.8    # Gap between node groups within same bucket

    for blob_bucket_idx, blob_bucket in enumerate(blob_buckets):
        node_groups = blob_bucket_to_node_groups[blob_bucket]

        for node_group_idx, node_group in enumerate(node_groups):
            combined_label = f"{blob_bucket} blobs: {node_group}"
            if combined_label in groups:
                vals = df.loc[df[group_col] == combined_label, 'diff_ms']
                if not vals.empty:
                    color = node_group_colors.get(node_group, '#1f77b4')

                    fig.add_trace(go.Box(
                        y=vals,
                        name=node_group,  # Legend shows node group
                        legendgroup=node_group,
                        showlegend=(blob_bucket_idx == 0),  # Only show in legend once
                        x=[x_position] * len(vals),
                        marker=dict(color=color),
                        line=dict(color=color),
                        boxpoints=boxpoints,
                        jitter=0.3,
                        width=0.6,
                        hovertemplate=f"{blob_bucket} blobs<br>{node_group}<br>Value: %{{y:.1f}}ms<br>Count: {len(vals):,}<extra></extra>"
                    ))

                    x_tick_positions.append(x_position)
                    x_tick_labels.append(f"{blob_bucket}\n{node_group}")
                    x_position += gap_within_bucket

        # Add gap between blob bucket groups
        x_position += gap_between_buckets

    # Add visual separators between blob bucket groups
    y_range = [df['diff_ms'].min(), df['diff_ms'].max()]
    separator_x = 0
    for blob_bucket_idx, blob_bucket in enumerate(blob_buckets[:-1]):  # Don't add after last group
        node_count = len(blob_bucket_to_node_groups[blob_bucket])
        separator_x += (node_count * gap_within_bucket) + (gap_between_buckets / 2)

        fig.add_vline(
            x=separator_x,
            line_dash="dash",
            line_color="lightgray",
            line_width=1,
            opacity=0.5
        )

        separator_x += (gap_between_buckets / 2)

    # Add blob bucket group labels as annotations
    label_x = 0
    for blob_bucket in blob_buckets:
        node_count = len(blob_bucket_to_node_groups[blob_bucket])
        # Calculate center position for this blob bucket group
        group_center = label_x + (node_count * gap_within_bucket) / 2 - (gap_within_bucket / 2)

        fig.add_annotation(
            x=group_center,
            y=1.05,
            yref="paper",
            text=f"<b>{blob_bucket} blobs</b>",
            showarrow=False,
            font=dict(size=11, color="darkblue"),
            xanchor="center"
        )

        label_x += (node_count * gap_within_bucket) + gap_between_buckets

    # Add data source annotation
    if config:
        data_source = config.get('data_source', 'unknown')
        event_type = config.get('event_type', 'unknown')
        annotation_text = f"Data: {data_source.title()} | Event: {event_type.replace('_', ' ').title()}"

        fig.add_annotation(
            x=0.02,
            y=0.98,
            xref="paper",
            yref="paper",
            text=annotation_text,
            showarrow=False,
            font=dict(size=9, color="gray"),
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="gray",
            borderwidth=1,
            align="left"
        )

    # Interactive usage hint
    st.info("💡 **Visualization**: Blob buckets are grouped together with visual spacing. Node groups within each bucket use consistent colors. Click legend items to show/hide specific node types.")

    fig.update_layout(
        title=title,
        xaxis_title="",
        yaxis_title="Timing (ms)",
        margin=dict(t=80, r=50, b=100, l=10),  # More top/bottom margin for labels
        showlegend=True,  # Enable interactive legend
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,  # Position legend to the right
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="rgba(0,0,0,0.2)",
            borderwidth=1
        ),
        hovermode='closest',
        xaxis=dict(
            tickmode='array',
            tickvals=x_tick_positions,
            ticktext=x_tick_labels,
            tickangle=-45,
            automargin=True
        )
    )
    st.plotly_chart(fig, use_container_width=True)


def render_group_boxplots(data: dict, config: Dict[str, Any] = None):
    samples: pd.DataFrame = data.get('samples', pd.DataFrame())
    if samples.empty:
        st.info("No samples available.")
        return

    # Filter out rows with empty/invalid group labels early
    original_count = len(samples)

    # Clean proposer_group
    if 'proposer_group' in samples.columns:
        samples = samples[
            samples['proposer_group'].notna() &
            (samples['proposer_group'].astype(str).str.strip() != '') &
            (~samples['proposer_group'].astype(str).str.lower().isin(['unknown', 'null', 'none']))
        ].copy()

    # Clean receiver_group
    if 'receiver_group' in samples.columns:
        samples = samples[
            samples['receiver_group'].notna() &
            (samples['receiver_group'].astype(str).str.strip() != '') &
            (~samples['receiver_group'].astype(str).str.lower().isin(['unknown', 'null', 'none']))
        ].copy()

    filtered_count = len(samples)
    if original_count > filtered_count:
        st.info(f"🧹 Filtered out {original_count - filtered_count:,} records with empty/unknown group labels ({(original_count - filtered_count)/original_count*100:.1f}%)")

    # Apply blob bucketing if enabled
    samples = apply_blob_bucketing(samples, config)
    if samples.empty:
        st.warning("No data available after applying filters.")
        return

    # Check if blob bucketing is enabled for special handling
    blob_bucketing_enabled = config.get('enable_blob_bucketing', False) and 'blob_bucket_label' in samples.columns

    if blob_bucketing_enabled:
        # When blob bucketing is enabled, show blob bucket analysis
        st.subheader("Blob Count Bucketing Analysis")
        _build_boxplot(samples, 'blob_bucket_label', 'Event timing by Blob Count Buckets (ms)', config)

        # Also show grouped analysis within blob buckets if grouping is enabled
        if 'proposer_group' in samples.columns or 'receiver_group' in samples.columns:
            st.subheader("Grouped Analysis within Blob Buckets")

            # Create combined grouping for visualization - group by blob bucket first
            if 'proposer_group' in samples.columns and 'receiver_group' in samples.columns:
                st.subheader("Blob Bucket × Proposer Analysis")
                samples['combined_group'] = samples['blob_bucket_label'].astype(str) + ' blobs: ' + samples['proposer_group'].astype(str)
                _build_combined_boxplot(samples, 'combined_group', 'blob_bucket_label', 'Event timing by Blob Count × Proposer Group (ms)', config)
            elif 'proposer_group' in samples.columns:
                st.subheader("Blob Bucket × Proposer Analysis")
                samples['combined_group'] = samples['blob_bucket_label'].astype(str) + ' blobs: ' + samples['proposer_group'].astype(str)
                _build_combined_boxplot(samples, 'combined_group', 'blob_bucket_label', 'Event timing by Blob Count × Proposer Group (ms)', config)
            elif 'receiver_group' in samples.columns:
                st.subheader("Blob Bucket × Receiver Analysis")
                samples['combined_group'] = samples['blob_bucket_label'].astype(str) + ' blobs: ' + samples['receiver_group'].astype(str)
                _build_combined_boxplot(samples, 'combined_group', 'blob_bucket_label', 'Event timing by Blob Count × Receiver Group (ms)', config)

    # Show grouped analysis if grouping columns exist (regular mode)
    elif 'proposer_group' in samples.columns or 'receiver_group' in samples.columns:
        st.subheader("Grouped Analysis")
        col1, col2 = st.columns(2)
        with col1:
            if 'proposer_group' in samples.columns:
                _build_boxplot(samples, 'proposer_group', 'Event timing by Proposer groups (ms)', config)
        with col2:
            if 'receiver_group' in samples.columns:
                _build_boxplot(samples, 'receiver_group', 'Event timing by Receiver groups (ms)', config)
    else:
        # Show basic distribution and summary statistics
        st.subheader("Distribution Analysis")

        if 'diff_ms' in samples.columns:
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("Basic Statistics")
                stats = samples['diff_ms'].describe()
                st.dataframe(stats.to_frame().T)

            with col2:
                st.subheader("Timing Distribution")
                _build_simple_histogram(samples, config)


def _build_simple_histogram(df: pd.DataFrame, config: Dict[str, Any] = None):
    if df.empty or 'diff_ms' not in df.columns:
        st.info("No timing data available.")
        return

    # Apply outlier filtering if configured
    if config and config.get('outlier_method', 'none') != 'none':
        df = filter_outliers(df, 'diff_ms', config)
        if df.empty:
            st.warning("All data was filtered out by outlier removal.")
            return

    import plotly.express as px

    fig = px.histogram(
        df,
        x='diff_ms',
        nbins=50,
        title="Event Timing Distribution",
        labels={'diff_ms': 'Timing (ms)', 'count': 'Count'}
    )

    # Add statistics annotation
    total_samples = len(df)
    mean_val = df['diff_ms'].mean()
    median_val = df['diff_ms'].median()
    p95_val = df['diff_ms'].quantile(0.95)

    stats_text = f"Samples: {total_samples:,}<br>"
    stats_text += f"Mean: {mean_val:.1f}ms<br>"
    stats_text += f"Median: {median_val:.1f}ms<br>"
    stats_text += f"P95: {p95_val:.1f}ms"

    if config:
        data_source = config.get('data_source', 'unknown')
        event_type = config.get('event_type', 'unknown')
        stats_text += f"<br><br>Data: {data_source.title()}<br>Event: {event_type.replace('_', ' ').title()}"

    fig.add_annotation(
        x=0.98,
        y=0.98,
        xref="paper",
        yref="paper",
        text=stats_text,
        showarrow=False,
        font=dict(size=10, color="gray"),
        bgcolor="rgba(255,255,255,0.9)",
        bordercolor="gray",
        borderwidth=1,
        align="right"
    )

    fig.update_layout(
        margin=dict(t=40, r=10, b=20, l=10),
        showlegend=False,
        hovermode='x'
    )
    st.plotly_chart(fig, use_container_width=True)



