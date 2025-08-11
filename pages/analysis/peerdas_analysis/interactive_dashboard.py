"""
Interactive dashboard for PeerDAS analysis.

Simplified single-chart dashboard matching multi-metric analysis styling.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import shared components
from shared.header import render_global_header, get_global_cluster, get_global_network

# Import local modules
from config_utils import (
    get_analysis_config,
    get_data_source_options
)
from loader import (
    load_peerdas_aggregated_data,
    load_node_classification_raw_data,
    validate_data_availability,
    get_max_blob_count
)
from plot_generators import (
    create_peerdas_performance_chart,
    create_node_classification_boxplot
)
from gap_analysis import create_node_performance_gap_analysis


def initialize_session_state():
    """Initialize session state variables."""
    if 'data_loaded' not in st.session_state:
        st.session_state.data_loaded = False
    if 'analysis_data' not in st.session_state:
        st.session_state.analysis_data = {}
    if 'last_config' not in st.session_state:
        st.session_state.last_config = None


def render_sidebar_configuration() -> Dict[str, Any]:
    """
    Render sidebar configuration for PeerDAS analysis.
    
    Returns:
        Configuration dictionary
    """
    cluster = get_global_cluster()
    network = get_global_network()
    
    if not cluster or not network:
        st.error("Please select a cluster and network from the header")
        return None
    
    # Check if cluster or network changed
    prev_cluster = st.session_state.get('previous_cluster', None)
    prev_network = st.session_state.get('previous_network', None)
    
    if (prev_cluster and prev_cluster != cluster) or (prev_network and prev_network != network):
        logger.info(f"Cluster/Network changed from {prev_cluster}/{prev_network} to {cluster}/{network}, clearing cache")
        st.cache_data.clear()
        st.session_state.analysis_data = {}
        st.session_state.data_loaded = False
    
    st.session_state.previous_cluster = cluster
    st.session_state.previous_network = network
    
    st.sidebar.header("⚙️ PeerDAS Configuration")
    
    # Time range selection
    st.sidebar.subheader("📅 Time Range")
    
    # Quick period selection
    time_options = {
        "Last 1 Hour": timedelta(hours=1),
        "Last 6 Hours": timedelta(hours=6),
        "Last 12 Hours": timedelta(hours=12),
        "Last 24 Hours": timedelta(hours=24),
        "Last 3 Days": timedelta(days=3),
        "Last 7 Days": timedelta(days=7),
        "Custom": None
    }
    
    selected_period = st.sidebar.selectbox(
        "Quick Period Selection",
        options=list(time_options.keys()),
        index=1,  # Default to "Last 6 Hours"
        help="Select a predefined period or choose Custom for manual selection"
    )
    
    # Set dates based on selection
    if selected_period != "Custom":
        time_delta = time_options[selected_period]
        end_date = datetime.now().date()
        start_date = (datetime.now() - time_delta).date()
        
        # Show the selected range (read-only)
        col1, col2 = st.sidebar.columns(2)
        with col1:
            st.date_input(
                "Start Date",
                value=start_date,
                disabled=True,
                key="start_date_display"
            )
        with col2:
            st.date_input(
                "End Date",
                value=end_date,
                disabled=True,
                key="end_date_display"
            )
    else:
        # Custom date selection
        col1, col2 = st.sidebar.columns(2)
        with col1:
            start_date = st.date_input(
                "Start Date",
                value=(datetime.now() - timedelta(hours=6)).date(),
                max_value=datetime.now().date(),
                key="start_date_custom"
            )
        
        with col2:
            end_date = st.date_input(
                "End Date",
                value=datetime.now().date(),
                max_value=datetime.now().date(),
                key="end_date_custom"
            )
    
    # Data source - default to libp2p
    st.sidebar.subheader("📊 Data Source")
    data_sources = get_data_source_options()
    
    # Default to libp2p (P2P Gossip Network)
    default_source = "libp2p"
    source_names = {k: v["name"] for k, v in data_sources.items()}
    
    # Track previous data source to clear cache on change
    previous_source = st.session_state.get('previous_data_source', None)
    
    selected_source = st.sidebar.radio(
        "Select Data Source",
        options=list(source_names.keys()),
        format_func=lambda x: source_names[x],
        index=list(source_names.keys()).index(default_source),
        help="P2P Gossip provides network-wide view, Beacon API provides node-specific data"
    )
    
    # Clear cache if data source changed
    if previous_source and previous_source != selected_source:
        logger.info(f"Data source changed from {previous_source} to {selected_source}, clearing cache")
        st.cache_data.clear()
        st.session_state.analysis_data = {}
        st.session_state.data_loaded = False
    
    st.session_state.previous_data_source = selected_source
    
    # Client filtering
    st.sidebar.subheader("🖥️ Client Selection")
    
    # Custody count filter
    config = get_analysis_config()
    custody_filter = st.sidebar.slider(
        "Maximum Custody Count",
        min_value=config['min_custody_count'],
        max_value=config['max_columns'],
        value=config['default_custody_filter'],
        step=4,
        help="Filter nodes by number of columns they custody (lower = lighter nodes)"
    )
    
    # Analysis type selection
    st.sidebar.subheader("📊 Analysis Type")
    analysis_type = st.sidebar.radio(
        "Visualization Type",
        options=['scatter', 'boxplot', 'gap'],
        format_func=lambda x: {
            'scatter': 'Scatter Plot (Aggregated)',
            'boxplot': 'Box Plot by Node Class',
            'gap': 'Performance Gap Analysis'
        }.get(x, x),
        index=0,
        help="Choose visualization type: Scatter for trends, Box plot for distributions, Gap for node performance differences"
    )
    
    # X-axis metric selection (only for scatter plot)
    if analysis_type == 'scatter':
        x_axis_metric = st.sidebar.radio(
            "X-Axis Metric",
            options=['blob_count', 'custody_count'],
            format_func=lambda x: {
                'blob_count': 'Blob Count (# of blobs)',
                'custody_count': 'Custody Count (# of columns)'
            }.get(x, x),
            index=0,  # Default to blob_count
            help="Choose whether to analyze by blob count or custody count"
        )
    else:
        x_axis_metric = 'blob_count'  # Box plots always use blob_count
    
    # Blob count bucketing (for box plot and gap analysis)
    if analysis_type in ['boxplot', 'gap']:
        st.sidebar.subheader("🗂️ Blob Count Bucketing")
        use_bucketing = st.sidebar.checkbox(
            "Enable Blob Count Bucketing",
            value=False,
            help="Group blob counts into buckets for cleaner visualization"
        )
        
        if use_bucketing:
            # Auto-detect max blob count from the dataset
            with st.spinner("Detecting max blob count..."):
                max_blobs = get_max_blob_count(
                    network=network,
                    start_date=datetime.combine(start_date, datetime.min.time()),
                    end_date=datetime.combine(end_date, datetime.max.time()),
                    data_source=selected_source,
                    cluster_name=cluster
                )
            
            # Show detected max
            st.sidebar.info(f"Max blob count in data: {max_blobs}")
            
            # Calculate default bucket size
            default_bucket_size = max(1, max_blobs // 12)
            
            bucket_size = st.sidebar.slider(
                "Bucket Size",
                min_value=1,
                max_value=max(20, max_blobs // 3),
                value=default_bucket_size,
                help=f"Group blob counts into buckets of this size (default: {default_bucket_size})"
            )
        else:
            bucket_size = None
    else:
        bucket_size = None
    
    # Load data button in sidebar
    st.sidebar.markdown("---")
    
    col1, col2 = st.sidebar.columns([2, 1])
    with col1:
        load_data = st.sidebar.button("🚀 Load and Analyze Data", type="primary", use_container_width=True)
    with col2:
        if st.sidebar.button("🗑️ Clear Cache", use_container_width=True, help="Clear all cached data"):
            st.cache_data.clear()
            st.session_state.analysis_data = {}
            st.session_state.data_loaded = False
            st.sidebar.success("Cache cleared!")
    
    return {
        'cluster': cluster,
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
        'data_source': selected_source,
        'custody_filter': custody_filter,
        'x_axis_metric': x_axis_metric,
        'analysis_type': analysis_type,
        'bucket_size': bucket_size,
        'load_data': load_data
    }


def load_and_process_data(config: Dict[str, Any], agg_function: str = "p90") -> Optional[pd.DataFrame]:
    """
    Load pre-aggregated PeerDAS data using efficient queries.
    
    Args:
        config: Configuration dictionary
        agg_function: Aggregation function to use
        
    Returns:
        Aggregated DataFrame or None if loading fails
    """
    with st.spinner("🔄 Loading PeerDAS data..."):
        try:
            # First validate data availability
            validation = validate_data_availability(
                network=config['network'],
                start_date=datetime.combine(config['start_date'], datetime.min.time()),
                end_date=datetime.combine(config['end_date'], datetime.max.time()),
                data_source=config['data_source'],
                cluster_name=config['cluster']
            )
            
            if not validation.get('has_data', False):
                if 'error' in validation:
                    st.error(f"⚠️ {validation['error']}")
                else:
                    st.warning("No data found for the selected time range")
                return None
            
            # Show data stats
            st.info(f"Found {validation['unique_slots']:,} slots with {validation['unique_clients']} unique clients")
            
            # Load aggregated data directly from ClickHouse
            data = load_peerdas_aggregated_data(
                network=config['network'],
                start_date=datetime.combine(config['start_date'], datetime.min.time()),
                end_date=datetime.combine(config['end_date'], datetime.max.time()),
                data_source=config['data_source'],
                aggregation=agg_function,
                custody_filter=config['custody_filter'],
                cluster_name=config['cluster'],
                group_by=config['x_axis_metric']
            )
            
            if data.empty:
                st.warning("No aggregated data returned")
                return None
            
            # Store metadata in session state
            st.session_state.analysis_data = {
                'aggregated_data': data,
                'unique_slots': validation['unique_slots'],
                'unique_clients': validation['unique_clients'],
                'total_rows': validation['total_rows']
            }
            st.session_state.data_loaded = True
            st.session_state.last_config = config
            
            return data
            
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            st.error(f"Failed to load data: {str(e)}")
            return None


def render_peerdas_dashboard():
    """Main dashboard rendering function."""
    st.title("🔮 PeerDAS Analysis")
    
    # Initialize session state
    initialize_session_state()
    
    # Render header for cluster/network selection
    cluster, network = render_global_header()
    
    if not cluster or not network:
        st.warning("Please select a cluster and network to begin analysis")
        return
    
    # Check if network supports PeerDAS
    if network and network.lower() == 'mainnet':
        st.error("⚠️ PeerDAS is not yet available on mainnet")
        st.info("""
        PeerDAS (Peer Data Availability Sampling) is currently only available on testnets and devnets.
        
        **Available networks with PeerDAS:**
        - fusaka-devnet-4
        - pectra-devnet-5
        - Other PeerDAS-enabled testnets
        
        Please select one of these networks from the header to analyze PeerDAS performance.
        """)
        return
    
    # Get configuration from sidebar
    config = render_sidebar_configuration()
    
    if not config:
        return
    
    # Main content area
    st.markdown("---")
    
    # Chart configuration checkboxes (matching multi-metric style)
    # Only show relevant options for each chart type
    if config.get('analysis_type') == 'boxplot':
        # Box plot configuration
        col1, col2 = st.columns(2)
        
        with col1:
            show_attestation_deadline = st.checkbox(
                "Show 4s attestation deadline",
                value=True,
                help="Display a reference line at 4 seconds for attestation timing"
            )
        
        with col2:
            # Grouping dimension selector
            grouping_options = st.multiselect(
                "Group By",
                options=['node_class', 'consensus_client'],
                default=['node_class'],
                format_func=lambda x: {
                    'node_class': 'Node Class (Non-validating/Standard/Supernode)',
                    'consensus_client': 'Consensus Client Implementation'
                }.get(x, x),
                help="Select one or more dimensions to group data. Selecting both creates combined groups."
            )
            
            # Ensure at least one grouping is selected
            if not grouping_options:
                grouping_options = ['node_class']
                st.warning("At least one grouping dimension must be selected. Using Node Class.")
        
        extrapolate_to_deadline = False
        show_trend_line = False
        show_relative = False
        agg_function = None  # Not used for box plots
    elif config.get('analysis_type') == 'gap':
        # Gap analysis options
        show_relative = st.checkbox(
            "Show Relative Differences (%)",
            value=True,
            help="Display both absolute (seconds) and relative (percentage) differences"
        )
        show_attestation_deadline = False
        extrapolate_to_deadline = False
        show_trend_line = False
        grouping_options = ['node_class']  # Default for gap analysis
        agg_function = None  # Not used for gap analysis
    else:
        # Scatter plot gets all options
        col1, col2 = st.columns(2)
        
        with col1:
            # Aggregation function selector for scatter plot
            agg_function = st.selectbox(
                "📈 Aggregation Method",
                options=['mean', 'p50', 'p90', 'p95', 'p99'],
                index=2,  # Default to p90
                format_func=lambda x: {
                    'mean': 'Mean (Average)',
                    'p50': 'Median (p50)',
                    'p90': '90th Percentile',
                    'p95': '95th Percentile',
                    'p99': '99th Percentile'
                }.get(x, x),
                help="How to aggregate data across multiple observations for each blob count"
            )
        
        with col2:
            show_attestation_deadline = st.checkbox(
                "Show 4s attestation deadline",
                value=True,
                help="Display a reference line at 4000ms for attestation timing"
            )
        
        col3, col4 = st.columns(2)
        
        with col3:
            show_trend_line = st.checkbox(
                "Show trend lines",
                value=True,
                help="Display linear regression trend lines"
            )
        
        with col4:
            extrapolate_to_deadline = st.checkbox(
                "Extrapolate trends to 4s line",
                value=False,
                help="Extend trend lines to show blob capacity at 4s deadline",
                disabled=not show_trend_line  # Only enable if trend lines are shown
            )
        
        grouping_options = None  # Not used for scatter plots
    
    # Process data if button clicked
    if config.get('load_data', False):
        if config['analysis_type'] in ['boxplot', 'gap']:
            # Load raw data for box plots or gap analysis
            with st.spinner("🔄 Loading raw PeerDAS data..."):
                try:
                    # First validate data availability
                    validation = validate_data_availability(
                        network=config['network'],
                        start_date=datetime.combine(config['start_date'], datetime.min.time()),
                        end_date=datetime.combine(config['end_date'], datetime.max.time()),
                        data_source=config['data_source'],
                        cluster_name=config['cluster']
                    )
                    
                    if not validation.get('has_data', False):
                        if 'error' in validation:
                            st.error(f"⚠️ {validation['error']}")
                        else:
                            st.warning("No data found for the selected time range")
                        return
                    
                    # Show data stats
                    st.info(f"Found {validation['unique_slots']:,} slots with {validation['unique_clients']} unique clients")
                    
                    # Load raw data
                    data = load_node_classification_raw_data(
                        network=config['network'],
                        start_date=datetime.combine(config['start_date'], datetime.min.time()),
                        end_date=datetime.combine(config['end_date'], datetime.max.time()),
                        data_source=config['data_source'],
                        custody_filter=config['custody_filter'],
                        cluster_name=config['cluster']
                    )
                    
                    if data is not None and not data.empty:
                        # Create time range string for display
                        time_range = f"{config['start_date']} to {config['end_date']}"
                        
                        # Prepare metadata
                        metadata = {
                            'total_blocks': validation['unique_slots'],
                            'unique_nodes': validation['unique_clients']
                        }
                        
                        # Create the appropriate chart based on analysis type
                        if config['analysis_type'] == 'boxplot':
                            fig = create_node_classification_boxplot(
                                data=data,
                                bucket_size=config.get('bucket_size'),
                                network=config['network'],
                                time_range=time_range,
                                metadata=metadata,
                                show_attestation_deadline=show_attestation_deadline,
                                grouping_dimensions=grouping_options
                            )
                        else:  # gap analysis
                            fig = create_node_performance_gap_analysis(
                                data=data,
                                bucket_size=config.get('bucket_size'),
                                network=config['network'],
                                time_range=time_range,
                                metadata=metadata,
                                show_relative=show_relative
                            )
                        
                        # Display the chart
                        st.plotly_chart(fig, use_container_width=True)
                        
                        # Store metadata in session state
                        st.session_state.analysis_data = {
                            'raw_data': data,
                            'unique_slots': validation['unique_slots'],
                            'unique_clients': validation['unique_clients'],
                            'total_rows': validation['total_rows']
                        }
                        st.session_state.data_loaded = True
                        st.session_state.last_config = config
                        
                except Exception as e:
                    logger.error(f"Error loading box plot data: {e}")
                    st.error(f"Failed to load data: {str(e)}")
        else:
            # Original scatter plot logic
            data = load_and_process_data(config, agg_function=agg_function)
            
            if data is not None and not data.empty:
                # Create time range string for display
                time_range = f"{config['start_date']} to {config['end_date']}"
                
                # Prepare metadata
                metadata = {
                    'total_blocks': st.session_state.analysis_data.get('unique_slots', 0),
                    'unique_nodes': st.session_state.analysis_data.get('unique_clients', 0)
                }
                
                # Create the chart
                fig = create_peerdas_performance_chart(
                    data=data,
                    x_metric=config['x_axis_metric'],  # Use the selected metric
                    y_metric='data_available_time',
                    agg_function=agg_function,
                    network=config['network'],
                    time_range=time_range,
                    metadata=metadata,
                    show_attestation_deadline=show_attestation_deadline,
                    extrapolate_to_deadline=extrapolate_to_deadline,
                    show_trend_line=show_trend_line
                )
                
                # Display the chart
                st.plotly_chart(fig, use_container_width=True)
            
            # Show data summary
            with st.expander("📊 Data Summary", expanded=False):
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric(
                        "Total Slots Analyzed",
                        f"{st.session_state.analysis_data.get('unique_slots', 0):,}"
                    )
                
                with col2:
                    st.metric(
                        "Unique Clients",
                        f"{st.session_state.analysis_data.get('unique_clients', 0)}"
                    )
                
                with col3:
                    st.metric(
                        "Data Source",
                        get_data_source_options()[config['data_source']]['name']
                    )
                
                with col4:
                    st.metric(
                        "Custody Filter",
                        f"≤ {config['custody_filter']} columns"
                    )
                
                # Show raw data table
                if config['analysis_type'] in ['boxplot', 'gap']:
                    st.subheader("Node Classification Summary")
                    # Show summary stats by node class
                    if 'raw_data' in st.session_state.analysis_data:
                        raw_data = st.session_state.analysis_data['raw_data']
                        summary = raw_data.groupby('node_class')['data_available_time'].agg([
                            ('Count', 'count'),
                            ('Mean (ms)', 'mean'),
                            ('Median (ms)', 'median'),
                            ('Std Dev (ms)', 'std'),
                            ('Min (ms)', 'min'),
                            ('Max (ms)', 'max')
                        ]).round(0)
                        st.dataframe(summary, use_container_width=True)
                else:
                    st.subheader("Raw Aggregated Data")
                    # Determine which metric column to show
                    metric_col = config['x_axis_metric']  # Will be 'blob_count' or 'custody_count'
                    display_cols = [metric_col, 'data_available_time', 'sample_count']
                    # Only show columns that exist
                    available_cols = [col for col in display_cols if col in data.columns]
                    if 'aggregated_data' in st.session_state.analysis_data:
                        agg_data = st.session_state.analysis_data['aggregated_data']
                        st.dataframe(
                            agg_data[available_cols],
                            use_container_width=True
                        )
    
    # Show help information
    with st.expander("ℹ️ About PeerDAS Analysis", expanded=False):
        st.markdown("""
        ### What is PeerDAS?
        PeerDAS (Peer Data Availability Sampling) is Ethereum's approach to scaling data availability
        through distributed storage of blob data across the network.
        
        ### Key Metrics:
        - **Data Available Time**: Time when a node has received both the block and all required data columns
        - **Blob Count**: Number of blobs in a slot (affects data size)
        - **Custody Count**: Number of data columns a node is responsible for storing (affects node load)
        
        ### Understanding the Charts:
        - **Scatter Plot**: Shows how data availability time changes with your selected metric
        - **Box Plot**: Displays performance distribution for each node class at different blob counts
        - **Gap Analysis**: Reveals how performance differences between node types scale with blob count
          - Positive gap = faster/better performance
          - Linear trend = consistent advantage
          - Non-linear = advantage changes with load
        - The 4s attestation deadline is a critical threshold for validator performance
        - Trend lines help predict network capacity at different performance levels
        """)


# Export the main function
def main():
    """Entry point for the dashboard."""
    render_peerdas_dashboard()