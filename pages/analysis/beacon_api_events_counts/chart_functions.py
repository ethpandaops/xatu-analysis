"""Additional chart functions for beacon API events counts analysis."""

import streamlit as st
import pandas as pd
from typing import Dict, Any


def render_histogram_analysis(data: Dict[str, Any], config: Dict[str, Any] = None):
    """Render focused histogram analysis - shows distribution of event counts."""
    from pages.analysis.beacon_api_events_counts.plot_generators import apply_blob_bucketing

    samples: pd.DataFrame = data.get('samples', pd.DataFrame())
    if samples.empty or 'event_count' not in samples.columns:
        st.info("No event count data available for histogram analysis.")
        return

    # Apply blob bucketing if enabled
    samples = apply_blob_bucketing(samples, config)
    if samples.empty:
        st.warning("No data available after applying filters.")
        return

    st.subheader("Event Count Distribution Analysis")

    col1, col2 = st.columns([2, 1])

    with col1:
        import plotly.express as px
        fig = px.histogram(
            samples,
            x='event_count',
            nbins=50,
            title="Event Count Distribution",
            labels={'event_count': 'Event Count', 'count': 'Frequency'}
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Distribution Statistics")
        stats = samples['event_count'].describe()

        # Add additional statistics
        extended_stats = pd.DataFrame({
            'Value': [
                f"{stats['count']:.0f}",
                f"{stats['mean']:.2f}",
                f"{stats['std']:.2f}",
                f"{stats['min']:.0f}",
                f"{stats['25%']:.0f}",
                f"{stats['50%']:.0f}",
                f"{stats['75%']:.0f}",
                f"{stats['max']:.0f}",
                f"{samples['event_count'].quantile(0.95):.0f}",
                f"{samples['event_count'].quantile(0.99):.0f}",
            ]
        }, index=[
            'Count', 'Mean', 'Std Dev', 'Min', 'Q1 (25%)',
            'Median (50%)', 'Q3 (75%)', 'Max', 'P95', 'P99'
        ])

        st.dataframe(extended_stats, use_container_width=True)


def render_statistical_summary(data: Dict[str, Any], config: Dict[str, Any] = None):
    """Render statistical summary table view for event counts."""
    from pages.analysis.beacon_api_events_counts.plot_generators import apply_blob_bucketing

    samples: pd.DataFrame = data.get('samples', pd.DataFrame())
    if samples.empty:
        st.info("No data available for statistical summary.")
        return

    # Filter out empty group labels (but keep 'unknown' - it represents valid data without metadata)
    original_count = len(samples)

    # Clean proposer_group
    if 'proposer_group' in samples.columns:
        samples = samples[
            samples['proposer_group'].notna() &
            (samples['proposer_group'].astype(str).str.strip() != '')
        ].copy()

    # Clean receiver_group
    if 'receiver_group' in samples.columns:
        samples = samples[
            samples['receiver_group'].notna() &
            (samples['receiver_group'].astype(str).str.strip() != '')
        ].copy()

    # Apply blob bucketing if enabled
    samples = apply_blob_bucketing(samples, config)
    if samples.empty:
        st.warning("No data available after applying filters.")
        return

    st.subheader("Statistical Summary")

    if 'proposer_group' in samples.columns and config.get('proposer_grouping', 'none') != 'none':
        # Group by proposer characteristics
        st.subheader("Event Count Summary by Proposer Group")

        grouped_stats = samples.groupby('proposer_group')['event_count'].agg([
            'count', 'sum', 'mean', 'std', 'min',
            lambda x: x.quantile(0.25),
            lambda x: x.quantile(0.50),
            lambda x: x.quantile(0.75),
            lambda x: x.quantile(0.95),
            'max'
        ]).round(2)

        grouped_stats.columns = ['Rows', 'Total Events', 'Mean', 'Std Dev', 'Min', 'Q1', 'Median', 'Q3', 'P95', 'Max']

        st.dataframe(grouped_stats, use_container_width=True)

        # Show group distribution
        st.subheader("Event Distribution by Proposer Group")
        group_totals = samples.groupby('proposer_group')['event_count'].sum()

        col1, col2 = st.columns(2)
        with col1:
            st.bar_chart(group_totals)
        with col2:
            pct_distribution = (group_totals / group_totals.sum() * 100).round(1)
            pct_df = pd.DataFrame({
                'Total Events': group_totals,
                'Percentage': pct_distribution.astype(str) + '%'
            })
            st.dataframe(pct_df, use_container_width=True)

    # Also show receiver grouping if available
    if 'receiver_group' in samples.columns and config.get('receiver_grouping', 'none') != 'none':
        # Group by receiver characteristics
        st.subheader("Event Count Summary by Receiver Group")

        grouped_stats = samples.groupby('receiver_group')['event_count'].agg([
            'count', 'sum', 'mean', 'std', 'min',
            lambda x: x.quantile(0.25),
            lambda x: x.quantile(0.50),
            lambda x: x.quantile(0.75),
            lambda x: x.quantile(0.95),
            'max'
        ]).round(2)

        grouped_stats.columns = ['Rows', 'Total Events', 'Mean', 'Std Dev', 'Min', 'Q1', 'Median', 'Q3', 'P95', 'Max']

        st.dataframe(grouped_stats, use_container_width=True)

        # Show group distribution
        st.subheader("Event Distribution by Receiver Group")
        group_totals = samples.groupby('receiver_group')['event_count'].sum()

        col1, col2 = st.columns(2)
        with col1:
            st.bar_chart(group_totals)
        with col2:
            pct_distribution = (group_totals / group_totals.sum() * 100).round(1)
            pct_df = pd.DataFrame({
                'Total Events': group_totals,
                'Percentage': pct_distribution.astype(str) + '%'
            })
            st.dataframe(pct_df, use_container_width=True)
    else:
        # Overall statistics
        st.subheader("Overall Event Count Statistics")
        if 'event_count' in samples.columns:
            stats = samples['event_count'].describe()

            # Create a more detailed summary
            summary_data = {
                'Metric': ['Rows', 'Total Events', 'Mean', 'Std Dev', 'Min', '25%', '50%', '75%', '95%', '99%', 'Max'],
                'Value': [
                    f"{stats['count']:.0f}",
                    f"{samples['event_count'].sum():.0f}",
                    f"{stats['mean']:.2f}",
                    f"{stats['std']:.2f}",
                    f"{stats['min']:.0f}",
                    f"{stats['25%']:.0f}",
                    f"{stats['50%']:.0f}",
                    f"{stats['75%']:.0f}",
                    f"{samples['event_count'].quantile(0.95):.0f}",
                    f"{samples['event_count'].quantile(0.99):.0f}",
                    f"{stats['max']:.0f}",
                ]
            }

            summary_df = pd.DataFrame(summary_data)
            st.dataframe(summary_df, use_container_width=True, hide_index=True)