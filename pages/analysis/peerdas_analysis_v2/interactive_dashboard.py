"""
Interactive dashboard for PeerDAS Analysis V2 - Head correctness analysis.

Analyzes head correctness (voting for proposed block_roots, including those
that may have been reorged) with bucketing by blob count and filtering by 
proposer and attester characteristics.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import shared components
from shared.header import render_global_header, get_global_cluster, get_global_network
from shared.database import get_database_connection

# Import local modules
from loader import (
    load_eligible_slots,
    load_head_correctness_data,
    get_node_classifications,
    validate_data_availability,
    get_unique_clients,
    load_network_mapping
)
from plot_generators import (
    create_head_correctness_boxplot,
    create_head_correctness_chart,
    create_head_correctness_violin,
    create_advanced_grouped_boxplot
)


def initialize_session_state():
    """Initialize session state variables."""
    if 'data_loaded' not in st.session_state:
        st.session_state.data_loaded = False
    if 'analysis_data' not in st.session_state:
        st.session_state.analysis_data = {}
    if 'last_config' not in st.session_state:
        st.session_state.last_config = None


def render_sidebar_config(cluster: str, network: str) -> Dict[str, Any]:
    """
    Render sidebar configuration options.
    
    Returns:
        Configuration dictionary
    """
    st.sidebar.header("⚙️ Configuration")
    
    # Check if network changed to clear cache
    if 'last_network' not in st.session_state:
        st.session_state.last_network = network
    elif st.session_state.last_network != network:
        st.session_state.last_network = network
        st.session_state.data_loaded = False
        st.session_state.analysis_data = {}
        logger.info(f"Network changed to {network}, clearing cache")
    
    # Check if cluster changed
    if 'last_cluster' not in st.session_state:
        st.session_state.last_cluster = cluster
    elif st.session_state.last_cluster != cluster:
        st.session_state.last_cluster = cluster
        st.session_state.data_loaded = False
        st.session_state.analysis_data = {}
        logger.info(f"Cluster changed to {cluster}, clearing cache")
    
    # Auto-select experimental cluster for fusaka networks
    if 'fusaka' in network.lower() and cluster != 'experimental':
        cluster = 'experimental'
        logger.info(f"Using experimental cluster for {network}")
        st.sidebar.info(f"Auto-selected experimental cluster for {network}")
    
    # Time range selection
    st.sidebar.subheader("📅 Time Range")
    
    # Set default time range for fusaka-devnet-4 (window with rich sidecar data)
    if network == 'fusaka-devnet-4':
        default_start = datetime(2025, 8, 12, 0, 0, 0)
        default_end = datetime(2025, 8, 12, 2, 0, 0)
    else:
        # Default to last 24 hours for other networks
        default_end = datetime.now()
        default_start = default_end - timedelta(hours=24)
    
    start_date = st.sidebar.date_input(
        "Start Date",
        value=default_start.date(),
        key="start_date"
    )
    
    start_time = st.sidebar.time_input(
        "Start Time",
        value=default_start.time(),
        key="start_time"
    )
    
    end_date = st.sidebar.date_input(
        "End Date",
        value=default_end.date(),
        key="end_date"
    )
    
    end_time = st.sidebar.time_input(
        "End Time",
        value=default_end.time(),
        key="end_time"
    )
    
    start_datetime = datetime.combine(start_date, start_time)
    end_datetime = datetime.combine(end_date, end_time)
    
    # Bucketing options for blob count
    st.sidebar.subheader("🗂️ Blob Count Bucketing")
    
    num_buckets = st.sidebar.slider(
        "Number of Buckets",
        min_value=1,
        max_value=12,
        value=6,
        help="Number of buckets to divide blob counts into (automatically calculates bucket size based on data range)"
    )

    # Grouping selection (used server-side)
    st.sidebar.subheader("🧩 Grouping")
    grouping_dimension = st.sidebar.selectbox(
        "Grouping Dimension",
        options=['node_type', 'cl_client', 'el_client', 'cl_el_combined', 'cl_node_type'],
        format_func=lambda x: {
            'node_type': 'Node Type',
            'cl_client': 'CL Client',
            'el_client': 'EL Client',
            'cl_el_combined': 'CL+EL Combination',
            'cl_node_type': 'CL+Node Type'
        }[x],
        help="Compute head-correctness per slot per group directly in ClickHouse"
    )
    
    # Proposer filtering
    st.sidebar.subheader("🎯 Proposer Filters")
    
    proposer_type = st.sidebar.selectbox(
        "Proposer Node Type",
        options=["all", "supernode", "regular"],
        format_func=lambda x: {
            "all": "All Node Types",
            "supernode": "Supernodes Only",
            "regular": "Regular Nodes Only"
        }[x],
        help="Filter by proposer node type"
    )
    
    proposer_cl = st.sidebar.multiselect(
        "Proposer CL Clients",
        options=["lighthouse", "prysm", "teku", "nimbus", "lodestar", "grandine"],
        default=["lighthouse", "prysm", "teku", "nimbus", "lodestar", "grandine"],
        help="Filter by proposer consensus layer client"
    )
    
    proposer_el = st.sidebar.multiselect(
        "Proposer EL Clients",
        options=["geth", "nethermind", "besu", "erigon", "reth", "nimbusel"],
        default=["geth", "nethermind", "besu", "erigon", "reth"],
        help="Filter by proposer execution layer client"
    )
    
    # Attester filtering
    st.sidebar.subheader("👥 Attester Filters")
    
    attester_type = st.sidebar.selectbox(
        "Attester Node Type",
        options=["all", "supernode", "regular"],
        format_func=lambda x: {
            "all": "All Node Types",
            "supernode": "Supernodes Only",
            "regular": "Regular Nodes Only"
        }[x],
        help="Filter by attester node type"
    )
    
    attester_cl = st.sidebar.multiselect(
        "Attester CL Clients",
        options=["lighthouse", "prysm", "teku", "nimbus", "lodestar", "grandine"],
        default=["lighthouse", "prysm", "teku", "nimbus", "lodestar", "grandine"],
        help="Filter by attester consensus layer client"
    )
    
    attester_el = st.sidebar.multiselect(
        "Attester EL Clients",
        options=["geth", "nethermind", "besu", "erigon", "reth", "nimbusel"],
        default=["geth", "nethermind", "besu", "erigon", "reth"],
        help="Filter by attester execution layer client"
    )
    
    # Load data button
    st.sidebar.markdown("---")
    
    # Chart Options
    st.sidebar.subheader("📊 Chart Options")
    
    chart_type = st.sidebar.selectbox(
        "Chart Type",
        options=['boxplot', 'violin', 'scatter'],
        format_func=lambda x: {
            'boxplot': 'Box Plot Distribution',
            'violin': 'Violin Plot Distribution',
            'scatter': 'Scatter Plot with Trend'
        }[x]
    )
    
    show_trend_line = False
    if chart_type == 'scatter':
        show_trend_line = st.sidebar.checkbox(
            "Show trend line",
            value=True,
            help="Display trend line on scatter plot"
        )
    
    # Stake weighting option (important for MaxEB networks)
    use_stake_weighting = st.sidebar.checkbox(
        "Use Stake Weighting",
        value=False,
        help="Weight validators by their effective balance (important for MaxEB validators with >32 ETH). When disabled, each validator counts equally."
    )
    
    st.sidebar.markdown("---")
    
    col1, col2 = st.sidebar.columns([2, 1])
    with col1:
        load_data = st.sidebar.button("🚀 Load Data", type="primary", use_container_width=True)
    with col2:
        if st.sidebar.button("🗑️ Clear", use_container_width=True):
            st.cache_data.clear()
            st.session_state.analysis_data = {}
            st.session_state.data_loaded = False
            # Force clear all caches
            st.rerun()
            st.sidebar.success("Cache cleared and page refreshed!")
    
    # If all clients are selected, treat as no filter (None)
    all_cl_clients = ["lighthouse", "prysm", "teku", "nimbus", "lodestar", "grandine"]
    all_el_clients = ["geth", "nethermind", "besu", "erigon", "reth", "nimbusel"]
    
    return {
        'cluster': cluster,
        'network': network,
        'start_datetime': start_datetime,
        'end_datetime': end_datetime,
        'num_buckets': num_buckets,
        'grouping_dimension': grouping_dimension,
        'proposer_type': proposer_type if proposer_type != "all" else None,
        'proposer_cl': proposer_cl if proposer_cl and set(proposer_cl) != set(all_cl_clients) else None,
        'proposer_el': proposer_el if proposer_el and set(proposer_el) != set(all_el_clients) else None,
        'attester_type': attester_type if attester_type != "all" else None,
        'attester_cl': attester_cl if attester_cl and set(attester_cl) != set(all_cl_clients) else None,
        'attester_el': attester_el if attester_el and set(attester_el) != set(all_el_clients) else None,
        'chart_type': chart_type,
        'show_trend_line': show_trend_line,
        'use_stake_weighting': use_stake_weighting,
        'load_data': load_data
    }


def load_and_process_head_correctness_data(config: Dict[str, Any]) -> Optional[pd.DataFrame]:
    """
    Load and process head correctness data.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Processed DataFrame with head correctness data or None if loading fails
    """
    with st.spinner("🔄 Loading head correctness data..."):
        try:
            # Load eligible slots (filtered by proposer)
            eligible_slots, slot_to_block, slot_to_proposer = load_eligible_slots(
                network=config['network'],
                start_date=config['start_datetime'],
                end_date=config['end_datetime'],
                proposer_type=config.get('proposer_type'),
                cl_filter=config.get('proposer_cl'),
                el_filter=config.get('proposer_el'),
                cluster_name=config['cluster']
            )
            
            if not eligible_slots:
                st.error("No eligible slots found for the selected proposer filters and time range")
                st.cache_data.clear()
                return None
            
            # Load head correctness data (against proposed blocks, including reorged)
            data = load_head_correctness_data(
                network=config['network'],
                start_date=config['start_datetime'],
                end_date=config['end_datetime'],
                eligible_slots=eligible_slots,
                slot_to_block=slot_to_block,
                slot_to_proposer=slot_to_proposer,
                attester_type=config.get('attester_type'),
                cl_filter=config.get('attester_cl'),
                el_filter=config.get('attester_el'),
                grouping_dimension=config.get('grouping_dimension'),
                use_stake_weighting=config.get('use_stake_weighting', False),
                cluster_name=config['cluster']
            )
            
            if data.empty:
                st.error("No head correctness data returned!")
                st.warning("""
                No head correctness data found for the selected filters.
                
                **Possible causes:**
                - No data_column_sidecar data available for the selected time range
                - No committee data available
                - No attestation data found for the eligible slots
                
                **Note:** PeerDAS analysis requires data_column_sidecar data to determine blob counts.
                Try selecting a different time range where data_column_sidecar data is available.
                """)
                # Clear cache to avoid bad data persistence
                st.cache_data.clear()
                st.session_state.analysis_data = {}
                st.session_state.data_loaded = False
                return None
            
            # Store in session state
            st.session_state.analysis_data = {
                'raw_data': data,
                'unique_slots': len(eligible_slots),
                'total_slots_analyzed': len(data),
                'avg_head_correctness': data['head_correctness_pct'].mean() if 'head_correctness_pct' in data.columns else 0
            }
            st.session_state.data_loaded = True
            
            return data
            
        except Exception as e:
            logger.error(f"Error loading attestation data: {e}")
            st.error(f"Failed to load data: {str(e)}")
            return None


def main():
    """Main dashboard function."""
    initialize_session_state()
    
    # Render header and get cluster/network
    render_global_header()
    cluster = get_global_cluster()
    network = get_global_network()
    # Render sidebar configuration
    config = render_sidebar_config(cluster, network)
    
    # Load and display data if requested
    if config['load_data']:
        data = load_and_process_head_correctness_data(config)
        
        if data is not None and not data.empty:
            # Create the visualization
            st.markdown("---")
            
            # Prepare metadata
            metadata = {
                'total_slots': st.session_state.analysis_data.get('unique_slots', 0),
                'total_slots_analyzed': st.session_state.analysis_data.get('total_slots_analyzed', 0)
            }
            
            time_range = f"{config['start_datetime'].strftime('%Y-%m-%d %H:%M')} to {config['end_datetime'].strftime('%Y-%m-%d %H:%M')}"
            
            # Prepare filter information for chart annotations
            proposer_filters = {
                'node_type': config.get('proposer_type'),
                'cl_filter': config.get('proposer_cl'),
                'el_filter': config.get('proposer_el')
            }
            
            attester_filters = {
                'node_type': config.get('attester_type'),
                'cl_filter': config.get('attester_cl'),
                'el_filter': config.get('attester_el')
            }
            
            # Create chart based on selected type
            if config['chart_type'] == 'boxplot':
                fig = create_head_correctness_boxplot(
                    data=data,
                    num_buckets=config.get('num_buckets'),
                    network=config['network'],
                    time_range=time_range,
                    metadata=metadata,
                    grouping_dimension=config.get('grouping_dimension') or 'node_type',
                    proposer_filters=proposer_filters,
                    attester_filters=attester_filters
                )
            elif config['chart_type'] == 'violin':
                fig = create_head_correctness_violin(
                    data=data,
                    num_buckets=config.get('num_buckets'),
                    network=config['network'],
                    time_range=time_range,
                    metadata=metadata,
                    grouping_dimension=config.get('grouping_dimension') or 'node_type',
                    proposer_filters=proposer_filters,
                    attester_filters=attester_filters
                )
            else:
                fig = create_head_correctness_chart(
                    data=data,
                    num_buckets=config.get('num_buckets') or 6,
                    network=config['network'],
                    time_range=time_range,
                    metadata=metadata,
                    show_trend_line=config.get('show_trend_line', True),
                    grouping_dimension=config.get('grouping_dimension') or 'node_type',
                    proposer_filters=proposer_filters,
                    attester_filters=attester_filters
                )
            
            # Display the chart
            st.plotly_chart(fig, use_container_width=True)
            
            # Show data summary
            with st.expander("📊 Data Summary", expanded=False):
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric(
                        "Eligible Slots",
                        f"{metadata['total_slots']:,}",
                        help="Total slots that match the proposer filters"
                    )
                
                with col2:
                    st.metric(
                        "Analyzed Slots",
                        f"{metadata['total_slots_analyzed']:,}",
                        help="Slots with head correctness data calculated"
                    )
                
                with col3:
                    avg_correctness = st.session_state.analysis_data.get('avg_head_correctness', 0)
                    st.metric(
                        "Avg Head Correctness",
                        f"{avg_correctness:.1f}%",
                        help="Mean head correctness across all analyzed slots"
                    )
                
                with col4:
                    if 'blob_count' in data.columns:
                        max_blobs = data['blob_count'].max()
                        min_blobs = data['blob_count'].min()
                        st.metric(
                            "Blob Count Range",
                            f"{min_blobs}-{max_blobs}",
                            help=f"Range of blob counts in the analyzed data"
                        )
                
                # Show grouping information if applicable
                if config.get('grouping_dimension'):
                    grouping_info = f"Grouping by: {config['grouping_dimension'].replace('_', ' ').title()}"
                    if config['chart_type'] == 'scatter':
                        grouping_info += " (showing p95 percentile)"
                    st.info(grouping_info)
                
                # Show raw data preview
                if st.checkbox("Show raw data preview"):
                    st.dataframe(
                        data.head(100),
                        use_container_width=True
                    )
    


if __name__ == "__main__":
    main()
