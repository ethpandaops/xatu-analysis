"""
Interactive dashboard for PeerDAS Analysis V2 - Head correctness analysis.

Analyzes head correctness (voting for the correct block_root) with bucketing 
by blob count and filtering by proposer and attester characteristics.
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
    
    # Set default time range for fusaka-devnet-4
    if network == 'fusaka-devnet-4':
        default_start = datetime(2025, 8, 14, 0, 0, 0)
        default_end = datetime(2025, 8, 14, 2, 0, 0)
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
    
    bucket_size = st.sidebar.slider(
        "Bucket Size",
        min_value=1,
        max_value=12,
        value=6,
        help="Group blob counts into buckets (e.g., 0-5, 6-11, 12-17)"
    )
    
    auto_scale_buckets = st.sidebar.checkbox(
        "Auto-scale buckets",
        value=True,
        help="Automatically adjust bucket size based on maximum blob count in data"
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
        options=["lighthouse", "prysm", "teku", "nimbus", "lodestar"],
        default=["lighthouse", "prysm", "teku", "nimbus", "lodestar"],
        help="Filter by proposer consensus layer client"
    )
    
    proposer_el = st.sidebar.multiselect(
        "Proposer EL Clients",
        options=["geth", "nethermind", "besu", "erigon", "reth"],
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
        options=["lighthouse", "prysm", "teku", "nimbus", "lodestar"],
        default=["lighthouse", "prysm", "teku", "nimbus", "lodestar"],
        help="Filter by attester consensus layer client"
    )
    
    attester_el = st.sidebar.multiselect(
        "Attester EL Clients",
        options=["geth", "nethermind", "besu", "erigon", "reth"],
        default=["geth", "nethermind", "besu", "erigon", "reth"],
        help="Filter by attester execution layer client"
    )
    
    # Load data button
    st.sidebar.markdown("---")
    
    col1, col2 = st.sidebar.columns([2, 1])
    with col1:
        load_data = st.sidebar.button("🚀 Load Data", type="primary", use_container_width=True)
    with col2:
        if st.sidebar.button("🗑️ Clear", use_container_width=True):
            st.cache_data.clear()
            st.session_state.analysis_data = {}
            st.session_state.data_loaded = False
            st.sidebar.success("Cache cleared!")
    
    # If all clients are selected, treat as no filter (None)
    all_cl_clients = ["lighthouse", "prysm", "teku", "nimbus", "lodestar"]
    all_el_clients = ["geth", "nethermind", "besu", "erigon", "reth"]
    
    return {
        'cluster': cluster,
        'network': network,
        'start_datetime': start_datetime,
        'end_datetime': end_datetime,
        'bucket_size': bucket_size,
        'auto_scale_buckets': auto_scale_buckets,
        'proposer_type': proposer_type if proposer_type != "all" else None,
        'proposer_cl': proposer_cl if proposer_cl and set(proposer_cl) != set(all_cl_clients) else None,
        'proposer_el': proposer_el if proposer_el and set(proposer_el) != set(all_el_clients) else None,
        'attester_type': attester_type if attester_type != "all" else None,
        'attester_cl': attester_cl if attester_cl and set(attester_cl) != set(all_cl_clients) else None,
        'attester_el': attester_el if attester_el and set(attester_el) != set(all_el_clients) else None,
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
            eligible_slots, slot_to_block = load_eligible_slots(
                network=config['network'],
                start_date=config['start_datetime'],
                end_date=config['end_datetime'],
                proposer_type=config.get('proposer_type'),
                cl_filter=config.get('proposer_cl'),
                el_filter=config.get('proposer_el'),
                cluster_name=config['cluster']
            )
            
            if not eligible_slots:
                st.warning("No eligible slots found for the selected proposer filters")
                return None
            
            st.info(f"Found {len(eligible_slots)} eligible slots")
            
            # Load head correctness data
            data = load_head_correctness_data(
                network=config['network'],
                start_date=config['start_datetime'],
                end_date=config['end_datetime'],
                eligible_slots=eligible_slots,
                slot_to_block=slot_to_block,
                attester_type=config.get('attester_type'),
                cl_filter=config.get('attester_cl'),
                el_filter=config.get('attester_el'),
                cluster_name=config['cluster']
            )
            
            if data.empty:
                st.warning("""
                No head correctness data found for the selected filters.
                
                **Possible causes:**
                - No data_column_sidecar data available for the selected time range
                - No committee data available (check beacon_api_eth_v1_beacon_committee)
                - No attestation data found for the eligible slots
                
                **Note:** PeerDAS analysis requires data_column_sidecar data to determine blob counts.
                Try selecting a different time range where data_column_sidecar data is available.
                """)
                return None
            
            st.success(f"Loaded head correctness data for {len(data):,} slots")
            
            # Display blob count distribution
            if 'blob_count' in data.columns:
                st.info(f"Blob count distribution: {data['blob_count'].value_counts().sort_index().to_dict()}")
            
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
    
    # Page title
    st.title("🎯 PeerDAS Analysis V2: Head Correctness Analysis")
    st.markdown("Analyze attestation head correctness (voting for correct block_root) with advanced grouping by blob count, node type, and client implementations")
    
    # Render sidebar configuration
    config = render_sidebar_config(cluster, network)
    
    # Load and display data if requested
    if config['load_data']:
        data = load_and_process_head_correctness_data(config)
        
        if data is not None and not data.empty:
            # Chart configuration options
            st.markdown("---")
            with st.expander("📊 Chart Options", expanded=True):
                col1, col2 = st.columns(2)
                
                with col1:
                    chart_type = st.selectbox(
                        "Chart Type",
                        options=['boxplot', 'scatter'],
                        format_func=lambda x: {
                            'boxplot': 'Box Plot Distribution',
                            'scatter': 'Scatter Plot with Trend'
                        }[x]
                    )
                
                with col2:
                    if chart_type == 'boxplot':
                        grouping_dimension = st.selectbox(
                            "Group by",
                            options=['node_type', 'cl_client', 'el_client', 'cl_el_combined', 'region'],
                            index=0,
                            format_func=lambda x: {
                                'node_type': 'Node Type (Supernode/Regular)',
                                'cl_client': 'CL Client Type',
                                'el_client': 'EL Client Type',
                                'cl_el_combined': 'CL+EL Client Combination',
                                'region': 'Network Region'
                            }[x],
                            help="Dimension to group box plots by"
                        )
                    else:
                        show_trend_line = st.checkbox(
                            "Show trend line",
                            value=True,
                            help="Display trend line on scatter plot"
                        )
                        grouping_dimension = None
            
            # Create the visualization
            st.markdown("---")
            
            # Prepare metadata
            metadata = {
                'total_slots': st.session_state.analysis_data.get('unique_slots', 0),
                'total_slots_analyzed': st.session_state.analysis_data.get('total_slots_analyzed', 0)
            }
            
            time_range = f"{config['start_datetime'].strftime('%Y-%m-%d %H:%M')} to {config['end_datetime'].strftime('%Y-%m-%d %H:%M')}"
            
            # Create chart based on selected type
            if chart_type == 'boxplot':
                # Use advanced grouped boxplot for client-based grouping
                if grouping_dimension in ['cl_client', 'el_client', 'cl_el_combined']:
                    try:
                        network_mapping = load_network_mapping(config['network'])
                        fig = create_advanced_grouped_boxplot(
                            data=data,
                            network_spec_data=network_mapping,
                            bucket_size=config.get('bucket_size'),
                            network=config['network'],
                            time_range=time_range,
                            metadata=metadata,
                            grouping_dimension=grouping_dimension or 'node_type',
                            auto_scale_buckets=config.get('auto_scale_buckets', True)
                        )
                    except Exception as e:
                        logger.warning(f"Failed to create advanced grouped boxplot: {e}")
                        # Fallback to standard boxplot
                        fig = create_head_correctness_boxplot(
                            data=data,
                            bucket_size=config.get('bucket_size'),
                            network=config['network'],
                            time_range=time_range,
                            metadata=metadata,
                            grouping_dimension=grouping_dimension or 'node_type',
                            auto_scale_buckets=config.get('auto_scale_buckets', True)
                        )
                else:
                    fig = create_head_correctness_boxplot(
                        data=data,
                        bucket_size=config.get('bucket_size'),
                        network=config['network'],
                        time_range=time_range,
                        metadata=metadata,
                        grouping_dimension=grouping_dimension or 'node_type',
                        auto_scale_buckets=config.get('auto_scale_buckets', True)
                    )
            else:
                fig = create_head_correctness_chart(
                    data=data,
                    bucket_size=config.get('bucket_size') or 6,
                    network=config['network'],
                    time_range=time_range,
                    metadata=metadata,
                    show_trend_line=show_trend_line if 'show_trend_line' in locals() else True
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
                if chart_type == 'boxplot' and 'grouping_dimension' in locals() and grouping_dimension != 'node_type':
                    st.info(f"""
                    **Grouping by {grouping_dimension.replace('_', ' ').title()}**: 
                    Data is grouped for comparative analysis. Note that for client-based grouping, 
                    performance variations are simulated based on typical client characteristics.
                    """)
                
                # Show auto-scaling information
                if config.get('auto_scale_buckets') and config.get('bucket_size'):
                    max_blobs = data['blob_count'].max() if 'blob_count' in data.columns else 0
                    st.info(f"""
                    **Auto-scaling enabled**: Bucket size may be automatically adjusted based on the maximum blob count 
                    ({max_blobs}) to create approximately 8 buckets for optimal visualization.
                    """)
                
                # Show raw data preview
                if st.checkbox("Show raw data preview"):
                    st.dataframe(
                        data.head(100),
                        use_container_width=True
                    )
    
    # Show instructions if no data loaded
    if not st.session_state.data_loaded:
        st.info("""
        👈 **Configure the head correctness analysis parameters in the sidebar:**
        1. **Time Range**: Select the analysis period
        2. **Blob Count Bucketing**: Configure bucket sizes for grouping blob counts
           - Use auto-scaling to automatically adjust bucket sizes based on data
           - Default bucket size is 6 (creates groups like 0-5, 6-11, 12-17)
        3. **Proposer/Attester Filters**: Focus on specific node types or clients
        4. Click "**Load Data**" to begin analysis
        
        **After loading data**, choose your visualization:
        - **Box Plot Distribution**: Shows head correctness distribution with advanced grouping options:
          - Group by **Node Type** (supernode vs regular nodes)
          - Group by **CL Client** (lighthouse, prysm, teku, nimbus, lodestar)
          - Group by **EL Client** (geth, nethermind, besu, erigon, reth)
          - Group by **CL+EL combinations** for detailed client pair analysis
        - **Scatter Plot**: Shows trends with optional trend lines
        
        **Head correctness** measures the percentage of attestations that voted for the canonical block_root in each slot.
        Higher blob counts may impact head correctness due to increased network and processing load.
        """)


if __name__ == "__main__":
    main()