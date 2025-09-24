import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from shared.ui_components import add_ethPandaOps_logo
from pages.analysis.attestation_cdf.config_utils import get_metric_info


def create_cdf_comparison_plot(aggregated_data, comparison_dimension=None, client_data=None, title=None, **kwargs):
    """Create unified CDF comparison plot showing all conditions on a single chart."""
    
    fig = go.Figure()
    
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']
    color_idx = 0
    
    # Collect all times for percentile calculations
    all_combined_times = []
    
    # If client_data is provided, show individual client CDFs
    if client_data is not None and not client_data.empty:
        # Check which column to use for grouping (backward compatibility)
        available_columns = list(client_data.columns)
        group_column = None
        
        if 'group_name' in available_columns:
            group_column = 'group_name'
        elif 'meta_client_name' in available_columns:
            group_column = 'meta_client_name'
        
        if group_column and group_column in client_data.columns:
            for client_name, client_group in client_data.groupby(group_column):
                # Calculate total attestations for this client
                total_attestations = 0
                if 'received_attestations' in client_group.columns:
                    total_attestations = client_group['received_attestations'].sum()
                elif 'total_attestations' in client_group.columns:
                    total_attestations = client_group['total_attestations'].sum()
                
                # Generate CDF from client data (convert ms to seconds)
                all_times = []
                for _, row in client_group.iterrows():
                    if 'cdf_times' in row and len(row['cdf_times']) > 0:
                        all_times.extend([t/1000 for t in row['cdf_times']])  # Convert ms to seconds
                
                if all_times:
                    sorted_times = np.sort(all_times)
                    probabilities = np.arange(1, len(sorted_times) + 1) / len(sorted_times)
                    
                    # Add to combined times for percentile calculation
                    all_combined_times.extend(all_times)
                    
                    # Include attestation count in the legend name
                    legend_name = f"{client_name} ({total_attestations:,} atts)"
                    
                    fig.add_trace(go.Scatter(
                        x=sorted_times,
                        y=probabilities,
                        mode='lines',
                        name=legend_name,
                        line=dict(color=colors[color_idx % len(colors)], width=2),
                        hovertemplate=f'<b>Client: {client_name}</b><br>' +
                                    f'Total Attestations: {total_attestations:,}<br>' +
                                    'Time: %{x:.2f}s<br>' +
                                    'Cumulative Probability: %{y:.2%}<br>' +
                                    '<extra></extra>'
                    ))
                    color_idx += 1
    
    # Add aggregated condition data if available
    if aggregated_data is not None and not aggregated_data.empty:
        if comparison_dimension:
            condition_data = aggregated_data[aggregated_data['condition_type'] == comparison_dimension]
        else:
            condition_data = aggregated_data
        
        for _, row in condition_data.iterrows():
            condition_label = f"{row['condition_type']}: {row['condition_value']}" if 'condition_type' in row else str(row['condition_value'])
            
            if len(row['combined_cdf_times']) > 0:
                # Convert milliseconds to seconds
                times_seconds = [t/1000 for t in row['combined_cdf_times']]
                
                fig.add_trace(go.Scatter(
                    x=times_seconds,
                    y=row['combined_cdf_probabilities'],
                    mode='lines',
                    name=condition_label,
                    line=dict(color=colors[color_idx % len(colors)], width=3, dash='dash'),
                    hovertemplate=f'<b>{condition_label}</b><br>' +
                                'Time: %{x:.2f}s<br>' +
                                'Cumulative Probability: %{y:.2%}<br>' +
                                '<extra></extra>'
                ))
                color_idx += 1
    
    # Use provided title or default
    plot_title = title if title else 'Unified Attestation Propagation CDF Analysis<br><sub>Cumulative distribution of attestation arrival times across all conditions</sub>'
    
    fig.update_layout(
        title=plot_title,
        xaxis_title='Propagation Time (seconds)',
        yaxis_title='Cumulative Probability',
        height=600,
        hovermode='x unified',
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
        title_font_size=16
    )
    
    # Calculate percentile times from combined data and add vertical reference lines
    if all_combined_times:
        sorted_all_times = np.sort(all_combined_times)
        p66_time = np.percentile(sorted_all_times, 66)
        p95_time = np.percentile(sorted_all_times, 95)
        
        # Add vertical lines at percentile times (only P66 and P95)
        fig.add_vline(x=p66_time, line_dash="dot", line_color="orange", opacity=0.5,
                     annotation_text=f"P66: {p66_time:.2f}s", annotation_position="top")
        fig.add_vline(x=p95_time, line_dash="dot", line_color="red", opacity=0.5,
                     annotation_text=f"P95: {p95_time:.2f}s", annotation_position="top")
    else:
        # Fallback to horizontal lines if no data for percentiles
        fig.add_hline(y=0.66, line_dash="dot", line_color="orange", opacity=0.5,
                     annotation_text="P66", annotation_position="top right")
        fig.add_hline(y=0.95, line_dash="dot", line_color="red", opacity=0.5,
                     annotation_text="P95", annotation_position="top right")
    
    return add_ethPandaOps_logo(fig)


def create_propagation_metrics_summary(aggregated_data):
    """Create summary metrics visualization."""
    
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=('Average P50 Propagation Time', 'Average P90 Propagation Time',
                      'Average Coverage Ratio', 'CDF Area Under Curve'),
        specs=[[{"secondary_y": False}, {"secondary_y": False}],
               [{"secondary_y": False}, {"secondary_y": False}]]
    )
    
    # Extract data for plotting
    condition_labels = []
    p50_values = []
    p90_values = []
    coverage_values = []
    auc_values = []
    
    for _, row in aggregated_data.iterrows():
        label = f"{row['condition_value']}"
        condition_labels.append(label)
        p50_values.append(row['avg_p50_propagation'])
        p90_values.append(row['avg_p90_propagation'])
        coverage_values.append(row['avg_coverage_ratio'] * 100)  # Convert to percentage
        auc_values.append(row['avg_auc'])
    
    # Add bar charts to subplots
    fig.add_trace(go.Bar(x=condition_labels, y=p50_values, name='P50 Time', 
                        marker_color='#1f77b4'), row=1, col=1)
    fig.add_trace(go.Bar(x=condition_labels, y=p90_values, name='P90 Time',
                        marker_color='#ff7f0e'), row=1, col=2)
    fig.add_trace(go.Bar(x=condition_labels, y=coverage_values, name='Coverage %',
                        marker_color='#2ca02c'), row=2, col=1)
    fig.add_trace(go.Bar(x=condition_labels, y=auc_values, name='AUC',
                        marker_color='#d62728'), row=2, col=2)
    
    fig.update_layout(
        height=600,
        title_text="Attestation Propagation Metrics Summary<br><sub>Key performance indicators across network conditions</sub>",
        showlegend=False,
        title_font_size=16
    )
    
    # Update y-axis labels
    fig.update_yaxes(title_text="Time (ms)", row=1, col=1)
    fig.update_yaxes(title_text="Time (ms)", row=1, col=2)
    fig.update_yaxes(title_text="Coverage (%)", row=2, col=1)
    fig.update_yaxes(title_text="AUC Score", row=2, col=2)
    
    return add_ethPandaOps_logo(fig)


def create_time_series_cdf_plot(cdf_data, slot_metadata, metric_column='p50_propagation_time'):
    """Create time series plot of CDF metrics over slots."""
    
    # Merge with slot metadata to get time context
    merged_data = cdf_data.merge(slot_metadata[['slot', 'epoch']], on='slot', how='left')
    
    # Convert slot to approximate timestamp for x-axis
    merged_data['approximate_time'] = pd.to_datetime('2020-12-01') + pd.to_timedelta(merged_data['slot'] * 12, unit='s')
    
    metric_info = get_metric_info(metric_column)
    
    fig = px.line(
        merged_data,
        x='approximate_time',
        y=metric_column,
        color='group_name',
        title=f'{metric_info["title"]} Over Time<br><sub>{metric_info["subtitle"]}</sub>',
        labels={
            'approximate_time': 'Time',
            metric_column: f'{metric_info["title"]} ({metric_info["unit"]})',
            'group_name': 'Client/Node'
        }
    )
    
    fig.update_layout(
        height=500,
        hovermode='x unified',
        title_font_size=16
    )
    
    return add_ethPandaOps_logo(fig)


def create_node_performance_heatmap(cdf_data, metric_columns):
    """Create heatmap showing performance across nodes and metrics."""
    
    # Pivot data for heatmap
    heatmap_data = cdf_data.groupby('group_name')[metric_columns].mean().reset_index()
    
    fig = go.Figure(data=go.Heatmap(
        z=heatmap_data[metric_columns].values,
        x=metric_columns,
        y=heatmap_data['group_name'],
        colorscale='RdYlBu_r',
        hoverongaps=False,
        hovertemplate='Node: %{y}<br>Metric: %{x}<br>Value: %{z:.2f}<extra></extra>'
    ))
    
    fig.update_layout(
        title='Node Performance Heatmap<br><sub>CDF metrics comparison across network nodes</sub>',
        xaxis_title='Metrics',
        yaxis_title='Nodes/Clients',
        height=400,
        title_font_size=16
    )
    
    return add_ethPandaOps_logo(fig)


def create_coverage_vs_speed_scatter(cdf_data):
    """Create scatter plot showing trade-off between coverage and speed."""
    
    fig = px.scatter(
        cdf_data,
        x='coverage_ratio',
        y='p50_propagation_time',
        color='group_name',
        size='received_attestations',
        title='Coverage vs Speed Trade-off<br><sub>Attestation coverage ratio vs propagation speed by node</sub>',
        labels={
            'coverage_ratio': 'Attestation Coverage Ratio',
            'p50_propagation_time': 'Median Propagation Time (ms)',
            'group_name': 'Client/Node',
            'received_attestations': 'Attestations Received'
        }
    )
    
    fig.update_layout(
        height=500,
        title_font_size=16
    )
    
    return add_ethPandaOps_logo(fig)


def create_missed_slots_by_proposer_entity_chart(missed_slots_with_proposers, entities, top_n=20):
    """Create bar chart showing count of missed slots by proposer entity.
    
    Args:
        missed_slots_with_proposers: DataFrame with columns 'slot' and 'proposer_validator_index'
        entities: Dict mapping validator index to entity name
        top_n: Number of top entities to show (default: 20)
    
    Returns:
        Plotly figure object
    """
    # Add entity information based on proposer validator index
    missed_slots_with_entity = missed_slots_with_proposers.copy()
    missed_slots_with_entity['entity'] = missed_slots_with_entity['proposer_validator_index'].map(
        lambda x: entities.get(x, 'unknown') if pd.notna(x) else 'unknown'
    )
    
    # Count missed slots per entity
    entity_slot_counts = missed_slots_with_entity['entity'].value_counts().reset_index()
    entity_slot_counts.columns = ['entity', 'missed_slot_count']
    
    # Get top N entities
    entity_slot_counts = entity_slot_counts.head(top_n)
    
    # Create bar chart
    fig = go.Figure(data=[
        go.Bar(
            x=entity_slot_counts['entity'],
            y=entity_slot_counts['missed_slot_count'],
            text=entity_slot_counts['missed_slot_count'],
            textposition='auto',
            marker_color='#d62728',
            hovertemplate='<b>Entity:</b> %{x}<br>' +
                         '<b>Missed Slots:</b> %{y}<br>' +
                         '<extra></extra>'
        )
    ])
    
    fig.update_layout(
        title=f'Top {top_n} Entities by Missed Block Proposals<br><sub>Entities who were assigned to propose blocks but didn\'t</sub>',
        xaxis_title='Entity',
        yaxis_title='Number of Missed Block Proposals',
        height=500,
        xaxis_tickangle=-45,
        title_font_size=16,
        showlegend=False
    )
    
    return add_ethPandaOps_logo(fig)