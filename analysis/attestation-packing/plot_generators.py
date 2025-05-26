import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

def add_ethpandaops_logo(fig):
    """Add EthPandaOps logo to a plotly figure."""
    # Logo functionality disabled
    return fig

def create_before_after_comparison(data, metric, clients, event_date, group_column='client'):
    """Create a before/after comparison plot using Plotly."""
    temp_df = data.copy()
    
    if group_column is None:
        # No grouping - show aggregate data
        pass  # Use all data
    else:
        temp_df = temp_df[temp_df[group_column].isin(clients)]
    
    # Get metric info for better titles
    metric_info = get_metric_info(metric)
    
    # Add period information
    temp_df['datetime'] = pd.to_datetime(temp_df['block_slot_start_date_time'])
    event_date_naive = pd.Timestamp(event_date).tz_localize(None) if hasattr(event_date, 'tzinfo') and event_date.tzinfo is not None else event_date
    temp_df['period'] = np.where(temp_df['datetime'] < event_date_naive, 'Before', 'After')
    
    if group_column is None:
        # No grouping - calculate aggregate metrics by period only
        client_metrics = temp_df.groupby('period')[metric].mean().reset_index()
        client_metrics['group'] = 'All Data'
        
        fig = px.bar(
            client_metrics, 
            x='group', 
            y=metric, 
            color='period',
            barmode='group',
            title=f'{metric_info["title"]} - Before vs After Comparison (All Data)<br><sub>{metric_info["subtitle"]}</sub>',
            labels={'group': 'Data', metric: metric_info["title"]},
            color_discrete_map={'Before': '#1f77b4', 'After': '#2ca02c'},  # Blue and Green
            category_orders={'period': ['Before', 'After']}  # Ensure Before is left, After is right
        )
    else:
        # Calculate mean for each group and period
        client_metrics = temp_df.groupby([group_column, 'period'])[metric].mean().reset_index()
        
        # Create the plot with simple styling
        group_label = 'Entity' if group_column == 'entity' else 'Consensus Client'
        fig = px.bar(
            client_metrics, 
            x=group_column, 
            y=metric, 
            color='period',
            barmode='group',
            title=f'{metric_info["title"]} - Before vs After Comparison<br><sub>{metric_info["subtitle"]}</sub>',
            labels={group_column: group_label, metric: metric_info["title"]},
            color_discrete_map={'Before': '#1f77b4', 'After': '#2ca02c'},  # Blue and Green
            category_orders={'period': ['Before', 'After']}  # Ensure Before is left, After is right
        )
    
    # Minimal layout updates
    fig.update_layout(
        xaxis_tickangle=-45,
        height=500,
        showlegend=True,
        title={'font': {'size': 16}}
    )
    
    # Add EthPandaOps logo
    return add_ethpandaops_logo(fig)

def create_distribution_plot(data, metric, clients, event_date, group_column='client'):
    """Create a before/after distribution plot using Plotly."""
    if group_column is None:
        temp_df = data.copy()
    else:
        temp_df = data[data[group_column].isin(clients)].copy()
    
    # Get metric info for better titles
    metric_info = get_metric_info(metric)
    
    # Add period information
    temp_df['datetime'] = pd.to_datetime(temp_df['block_slot_start_date_time'])
    event_date_naive = pd.Timestamp(event_date).tz_localize(None) if hasattr(event_date, 'tzinfo') and event_date.tzinfo is not None else event_date
    temp_df['period'] = np.where(temp_df['datetime'] < event_date_naive, 'Before', 'After')
    
    if group_column is None:
        # No grouping - show distribution by period only
        temp_df['group'] = 'All Data'
        fig = px.box(
            temp_df, 
            x='group', 
            y=metric,
            color='period',
            title=f'{metric_info["title"]} - Distribution Analysis (All Data)<br><sub>{metric_info["subtitle"]}</sub>',
            labels={'group': 'Data', metric: metric_info["title"]},
            color_discrete_map={'Before': '#1f77b4', 'After': '#2ca02c'}  # Blue and Green
        )
    else:
        group_label = 'Entity' if group_column == 'entity' else 'Consensus Client'
        fig = px.box(
            temp_df, 
            x=group_column, 
            y=metric,
            color='period',
            title=f'{metric_info["title"]} - Distribution Analysis<br><sub>{metric_info["subtitle"]}</sub>',
            labels={group_column: group_label, metric: metric_info["title"]},
            color_discrete_map={'Before': '#1f77b4', 'After': '#2ca02c'}  # Blue and Green
        )
    
    # Minimal layout updates
    fig.update_layout(
        xaxis_tickangle=-45,
        height=500,
        title={'font': {'size': 16}}
    )
    
    # Add EthPandaOps logo
    return add_ethpandaops_logo(fig)

def create_time_series_plot(data, metric, clients, event_date, group_column='client'):
    """Create a time series plot using Plotly."""
    if group_column is None:
        temp_df = data.copy()
    else:
        temp_df = data[data[group_column].isin(clients)].copy()
    temp_df['datetime'] = pd.to_datetime(temp_df['block_slot_start_date_time'])
    
    # Get metric info for better titles
    metric_info = get_metric_info(metric)
    
    if group_column is None:
        # No grouping - show all data points without color grouping
        fig = px.scatter(
            temp_df, 
            x='datetime', 
            y=metric, 
            title=f'{metric_info["title"]} - Time Series Analysis (All Data)<br><sub>{metric_info["subtitle"]}</sub>',
            labels={'datetime': 'Date/Time', metric: metric_info["title"]}
        )
    else:
        group_label = 'Entity' if group_column == 'entity' else 'Consensus Client'
        fig = px.scatter(
            temp_df, 
            x='datetime', 
            y=metric, 
            color=group_column,
            title=f'{metric_info["title"]} - Time Series Analysis<br><sub>{metric_info["subtitle"]}</sub>',
            labels={'datetime': 'Date/Time', metric: metric_info["title"], group_column: group_label}
        )
    
    # Add vertical line for event date
    # Convert to datetime object that plotly can handle
    try:
        if hasattr(event_date, 'tzinfo') and event_date.tzinfo is not None:
            event_date_dt = event_date.replace(tzinfo=None)
        else:
            event_date_dt = pd.to_datetime(event_date)
            if hasattr(event_date_dt, 'tz_localize'):
                event_date_dt = event_date_dt.tz_localize(None)
        
        fig.add_vline(x=event_date_dt, line_dash="dash", line_color="red", 
                      annotation_text="Event Date")
    except Exception as e:
        # If datetime conversion fails, skip the vertical line
        st.warning(f"Could not add event date line: {e}")
    
    # Minimal layout updates
    fig.update_layout(
        height=500,
        title={'font': {'size': 16}}
    )
    
    # Add EthPandaOps logo
    return add_ethpandaops_logo(fig)

def create_inclusion_distance_distribution(data, clients, event_date, group_column='client'):
    """Create an inclusion distance distribution plot similar to the blog post."""
    if group_column is None:
        temp_df = data.copy()
    else:
        temp_df = data[data[group_column].isin(clients)].copy()
    
    # Add period information
    temp_df['datetime'] = pd.to_datetime(temp_df['block_slot_start_date_time'])
    event_date_naive = pd.Timestamp(event_date).tz_localize(None) if hasattr(event_date, 'tzinfo') and event_date.tzinfo is not None else event_date
    temp_df['period'] = np.where(temp_df['datetime'] < event_date_naive, 'Before', 'After')
    
    # Create histogram data for different inclusion delays
    delay_metrics = [col for col in temp_df.columns if col.startswith('delay_') and col.endswith('_count')]
    
    # Create description for inclusion delay distribution
    delay_description = "Shows the distribution of how many slots elapsed between when attestations should have been included (slot + 1) and when they actually appeared in blocks. Lower delays indicate better network performance."
    
    if not delay_metrics:
        # If we don't have delay count metrics, create a simple distribution
        fig = px.histogram(
            temp_df, 
            x='avg_attestation_inclusion_delay', 
            color='period',
            nbins=20,
            title=f'Attestation Inclusion Delay Distribution<br><sub>{delay_description}</sub>',
            labels={'avg_attestation_inclusion_delay': 'Average Inclusion Delay (slots)'},
            color_discrete_map={'Before': '#1f77b4', 'After': '#2ca02c'}  # Blue and Green
        )
    else:
        # Create a more detailed delay distribution
        delay_data = []
        for period in ['Before', 'After']:
            period_data = temp_df[temp_df['period'] == period]
            for delay_col in delay_metrics:
                delay_num = int(delay_col.split('_')[1])
                count = period_data[delay_col].sum()
                if count > 0:
                    delay_data.append({
                        'period': period,
                        'inclusion_delay': delay_num,
                        'count': count
                    })
        
        if delay_data:
            delay_df = pd.DataFrame(delay_data)
            fig = px.bar(
                delay_df,
                x='inclusion_delay',
                y='count',
                color='period',
                barmode='group',
                title=f'Attestation Inclusion Delay Distribution<br><sub>{delay_description}</sub>',
                labels={'inclusion_delay': 'Inclusion Delay (slots)', 'count': 'Number of Attestations'},
                color_discrete_map={'Before': '#1f77b4', 'After': '#2ca02c'}  # Blue and Green
            )
        else:
            # Fallback to simple histogram
            fig = px.histogram(
                temp_df, 
                x='avg_attestation_inclusion_delay', 
                color='period',
                nbins=20,
                title=f'Attestation Inclusion Delay Distribution<br><sub>{delay_description}</sub>',
                labels={'avg_attestation_inclusion_delay': 'Average Inclusion Delay (slots)'},
                color_discrete_map={'Before': '#1f77b4', 'After': '#2ca02c'}  # Blue and Green
            )
    
    # Minimal layout updates
    fig.update_layout(
        height=500,
        title={'font': {'size': 16}}
    )
    
    # Add EthPandaOps logo
    return add_ethpandaops_logo(fig)

def get_metric_info(metric_name):
    """Get human-readable title and description for metrics."""
    metric_info = {
        "unique_validator_indexes": {
            "title": "Unique Validators Per Block",
            "subtitle": "Total number of unique validators that submitted attestations included in each block. Higher values indicate better validator participation and network health."
        },
        "first_seen_attestations": {
            "title": "Fresh Attestations",
            "subtitle": "Number of attestations the client included in the block that had never been seen before. Measures how much 'new' attestation data each block contributes to the chain."
        },
        "avg_attestation_inclusion_delay": {
            "title": "Average Inclusion Delay",
            "subtitle": "Average number of slots between when an attestation was supposed to be included (slot + 1) and when it actually appeared in a block. Lower is better for network efficiency."
        },
        "optimal_inclusion_rate": {
            "title": "Optimal Inclusion Rate",
            "subtitle": "Percentage of validators whose attestations were included with just 1-slot delay (optimal timing). Higher rates indicate better network performance and proposer efficiency."
        },
        "min_attestation_inclusion_delay": {
            "title": "Minimum Inclusion Delay",
            "subtitle": "The shortest delay for any attestation in the block. Shows the best-case inclusion performance for that block."
        },
        "p50_attestation_inclusion_delay": {
            "title": "Median Inclusion Delay",
            "subtitle": "The middle value (50th percentile) of all inclusion delays in the block. Provides a robust measure of typical inclusion performance."
        },
        "p95_attestation_inclusion_delay": {
            "title": "95th Percentile Inclusion Delay",
            "subtitle": "The delay below which 95% of attestations fall. Helps identify outliers and worst-case inclusion scenarios."
        },
        "max_attestation_inclusion_delay": {
            "title": "Maximum Inclusion Delay",
            "subtitle": "The longest delay for any attestation in the block. Shows worst-case inclusion performance and potential network issues."
        },
        "aggregation_efficiency": {
            "title": "Aggregation Efficiency",
            "subtitle": "Ratio of unique validators to total attestations. Higher values mean better aggregation - fewer attestation objects needed to represent the same validator participation."
        },
        "total_attestations": {
            "title": "Total Attestations",
            "subtitle": "Total number of attestation objects included in each block. Lower numbers (with same validator participation) indicate better aggregation."
        },
        "avg_validators_per_attestation": {
            "title": "Average Validators Per Attestation",
            "subtitle": "Average number of validators represented by each attestation object. Higher values indicate better signature aggregation efficiency."
        },
        "optimal_inclusion_validators": {
            "title": "Optimal Inclusion Validators",
            "subtitle": "Number of validators whose attestations were included with optimal 1-slot delay. Measures absolute count (not percentage) of well-included validators."
        }
    }
    
    return metric_info.get(metric_name, {
        "title": metric_name.replace('_', ' ').title(),
        "subtitle": "No description available for this metric."
    })
