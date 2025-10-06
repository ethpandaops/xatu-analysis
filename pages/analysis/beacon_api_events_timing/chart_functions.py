"""Additional chart functions for beacon API events timing analysis."""

import streamlit as st
import pandas as pd
from typing import Dict, Any


def render_histogram_analysis(data: Dict[str, Any], config: Dict[str, Any] = None):
    """Render focused histogram analysis."""
    from pages.analysis.beacon_api_events_timing.plot_generators import _build_simple_histogram, apply_blob_bucketing

    samples: pd.DataFrame = data.get('samples', pd.DataFrame())
    if samples.empty or 'diff_ms' not in samples.columns:
        st.info("No timing data available for histogram analysis.")
        return

    # Apply blob bucketing if enabled
    samples = apply_blob_bucketing(samples, config)
    if samples.empty:
        st.warning("No data available after applying filters.")
        return

    st.subheader("Timing Distribution Analysis")

    col1, col2 = st.columns([2, 1])

    with col1:
        _build_simple_histogram(samples, config)

    with col2:
        st.subheader("Distribution Statistics")
        stats = samples['diff_ms'].describe()

        # Add additional statistics
        extended_stats = pd.DataFrame({
            'Value': [
                f"{stats['count']:.0f}",
                f"{stats['mean']:.2f}ms",
                f"{stats['std']:.2f}ms",
                f"{stats['min']:.2f}ms",
                f"{stats['25%']:.2f}ms",
                f"{stats['50%']:.2f}ms",
                f"{stats['75%']:.2f}ms",
                f"{stats['max']:.2f}ms",
                f"{samples['diff_ms'].quantile(0.95):.2f}ms",
                f"{samples['diff_ms'].quantile(0.99):.2f}ms",
            ]
        }, index=[
            'Count', 'Mean', 'Std Dev', 'Min', 'Q1 (25%)',
            'Median (50%)', 'Q3 (75%)', 'Max', 'P95', 'P99'
        ])

        st.dataframe(extended_stats, use_container_width=True)


def render_statistical_summary(data: Dict[str, Any], config: Dict[str, Any] = None):
    """Render statistical summary table view."""
    from pages.analysis.beacon_api_events_timing.plot_generators import apply_blob_bucketing

    samples: pd.DataFrame = data.get('samples', pd.DataFrame())
    if samples.empty:
        st.info("No data available for statistical summary.")
        return

    # Filter out empty group labels
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

    # Apply blob bucketing if enabled
    samples = apply_blob_bucketing(samples, config)
    if samples.empty:
        st.warning("No data available after applying filters.")
        return

    st.subheader("Statistical Summary")

    if 'proposer_group' in samples.columns and config.get('proposer_grouping', 'none') != 'none':
        # Group by proposer characteristics
        st.subheader("Summary by Proposer Group")

        grouped_stats = samples.groupby('proposer_group')['diff_ms'].agg([
            'count', 'mean', 'std', 'min',
            lambda x: x.quantile(0.25),
            lambda x: x.quantile(0.50),
            lambda x: x.quantile(0.75),
            lambda x: x.quantile(0.95),
            'max'
        ]).round(2)

        grouped_stats.columns = ['Count', 'Mean (ms)', 'Std Dev (ms)', 'Min (ms)', 'Q1 (ms)', 'Median (ms)', 'Q3 (ms)', 'P95 (ms)', 'Max (ms)']

        st.dataframe(grouped_stats, use_container_width=True)

        # Show group distribution
        st.subheader("Sample Distribution by Proposer Group")
        group_counts = samples['proposer_group'].value_counts()

        col1, col2 = st.columns(2)
        with col1:
            st.bar_chart(group_counts)
        with col2:
            pct_distribution = (group_counts / group_counts.sum() * 100).round(1)
            pct_df = pd.DataFrame({
                'Count': group_counts,
                'Percentage': pct_distribution.astype(str) + '%'
            })
            st.dataframe(pct_df, use_container_width=True)

    # Also show receiver grouping if available
    if 'receiver_group' in samples.columns and config.get('receiver_grouping', 'none') != 'none':
        # Group by receiver characteristics
        st.subheader("Summary by Event Receiver Group")

        grouped_stats = samples.groupby('receiver_group')['diff_ms'].agg([
            'count', 'mean', 'std', 'min',
            lambda x: x.quantile(0.25),
            lambda x: x.quantile(0.50),
            lambda x: x.quantile(0.75),
            lambda x: x.quantile(0.95),
            'max'
        ]).round(2)

        grouped_stats.columns = ['Count', 'Mean (ms)', 'Std Dev (ms)', 'Min (ms)', 'Q1 (ms)', 'Median (ms)', 'Q3 (ms)', 'P95 (ms)', 'Max (ms)']

        st.dataframe(grouped_stats, use_container_width=True)

        # Show group distribution
        st.subheader("Sample Distribution by Receiver Group")
        group_counts = samples['receiver_group'].value_counts()

        col1, col2 = st.columns(2)
        with col1:
            st.bar_chart(group_counts)
        with col2:
            pct_distribution = (group_counts / group_counts.sum() * 100).round(1)
            pct_df = pd.DataFrame({
                'Count': group_counts,
                'Percentage': pct_distribution.astype(str) + '%'
            })
            st.dataframe(pct_df, use_container_width=True)
    else:
        # Overall statistics
        st.subheader("Overall Statistics")
        if 'diff_ms' in samples.columns:
            stats = samples['diff_ms'].describe()

            # Create a more detailed summary
            summary_data = {
                'Metric': ['Count', 'Mean', 'Std Dev', 'Min', '25%', '50%', '75%', '95%', '99%', 'Max'],
                'Value (ms)': [
                    f"{stats['count']:.0f}",
                    f"{stats['mean']:.2f}",
                    f"{stats['std']:.2f}",
                    f"{stats['min']:.2f}",
                    f"{stats['25%']:.2f}",
                    f"{stats['50%']:.2f}",
                    f"{stats['75%']:.2f}",
                    f"{samples['diff_ms'].quantile(0.95):.2f}",
                    f"{samples['diff_ms'].quantile(0.99):.2f}",
                    f"{stats['max']:.2f}",
                ]
            }

            summary_df = pd.DataFrame(summary_data)
            st.dataframe(summary_df, use_container_width=True, hide_index=True)