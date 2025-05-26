# Gas Usage Performance Analysis - Streamlit Implementation Plan

## Overview
> This plan details the conversion of the existing `gas_block_arrival.ipynb` Jupyter notebook into a comprehensive Streamlit dashboard within the xatu-analysis project. The implementation will provide interactive analysis of the relationship between gas usage and block arrival times in Ethereum networks, with support for multi-period comparisons and detailed consensus implementation analysis.

## Current State Assessment

### Existing Implementation Analysis
- **Source**: Jupyter notebook `gas_block_arrival.ipynb` analyzing gas usage vs block arrival times
- **Data Sources**: Three primary ClickHouse tables:
  - `beacon_api_eth_v1_events_block_gossip` (block propagation times)
  - `beacon_api_eth_v1_events_head`, `beacon_api_eth_v1_events_block`, `beacon_api_eth_v1_events_blob_sidecar` (head time calculations)
  - `canonical_beacon_block` (gas usage data)
- **Analysis Features**:
  - Multi-period comparison support (Period 1 vs Period 2)
  - Time bucketing (30 equal-duration windows)
  - Consensus implementation performance comparison
  - Geographic analysis by continent
  - Complex statistical calculations (correlations, trends, percentiles)
  - Multiple visualization types (scatter, time series, heatmaps, box plots)

### Technical Patterns Identified
- **Environment Configuration**: Uses python-dotenv for database credentials and analysis periods
- **Data Processing**: Complex multi-table joins with CTE-based queries
- **Visualization**: matplotlib/seaborn with custom branding functionality
- **Statistical Analysis**: scipy for linear regression, numpy for percentile calculations
- **Time Analysis**: Sophisticated bucketing algorithm for temporal analysis

### Limitations in Current Approach
- **Non-Interactive**: Static notebook requiring manual parameter changes
- **Limited Configurability**: Hard-coded analysis periods and parameters
- **No Real-time Updates**: Manual data refresh required
- **Visualization Constraints**: Static plots without interactivity
- **User Experience**: Technical notebook interface not user-friendly

### Integration Points with Existing Xatu-Analysis Project
- **Database Connection**: Leverages existing `shared/database.py` patterns
- **Styling**: Can utilize `shared/ui_components.py` for consistent branding
- **Configuration**: Aligns with existing environment variable patterns
- **Architecture**: Fits established page structure in `pages/analysis/`

## Goals

1. **Primary Goal**: Convert Jupyter notebook into interactive Streamlit dashboard maintaining all analytical capabilities
2. **Enhanced Interactivity**: 
   - Dynamic period selection via date pickers
   - Real-time metric configuration
   - Interactive plot filtering and zooming
   - Export capabilities for data and visualizations
3. **Improved User Experience**:
   - Intuitive configuration interface
   - Progressive disclosure of analysis complexity
   - Clear metric explanations and tooltips
   - Responsive layout for different screen sizes
4. **Performance Optimization**:
   - Efficient data caching strategies
   - Incremental data loading
   - Optimized query execution
5. **Extensibility**:
   - Modular component architecture
   - Easy addition of new metrics and visualizations
   - Support for additional data sources

## Gas Usage Performance Analysis Design Approach

### Architecture Overview
The implementation follows the established xatu-analysis modular pattern with clear separation of concerns. Data flows from ClickHouse through specialized loaders into metrics calculators, which feed visualization generators and the main interactive dashboard. The architecture supports both single-period and comparative multi-period analysis with sophisticated caching for performance optimization.

### Component Breakdown

1. **Config Utils (`config_utils.py`)**
   - Purpose: Define metric configurations and analysis parameters
   - Responsibilities: Metric metadata management, validation rules, default configurations
   - Interfaces: Provides metric info to all other components, validates user inputs

2. **Data Loaders (`data_loaders.py`)**
   - Purpose: Fetch and prepare data from ClickHouse databases
   - Responsibilities: Execute complex multi-table queries, handle data cleaning, manage caching
   - Interfaces: Provides cleaned DataFrames to metrics calculators

3. **Metrics Calculators (`metrics_calculators.py`)**
   - Purpose: Perform statistical calculations and analysis logic
   - Responsibilities: Time bucketing, correlation analysis, trend calculations, consensus implementation ranking
   - Interfaces: Receives raw data, outputs calculated metrics for visualization

4. **Plot Generators (`plot_generators.py`)**
   - Purpose: Create interactive visualizations using Plotly
   - Responsibilities: Generate scatter plots, time series, heatmaps, box plots with consistent styling
   - Interfaces: Receives metrics data, outputs Plotly figures with ethPandaOps branding

5. **Interactive Dashboard (`interactive_dashboard.py`)**
   - Purpose: Orchestrate the complete user interface and analysis workflow
   - Responsibilities: UI layout, user input handling, component coordination, session state management
   - Interfaces: Primary entry point integrating all other components

## Implementation Approach

### 1. Configuration and Data Foundation

#### Specific Changes
- Migrate environment variable patterns from notebook to shared config system
- Create comprehensive metric definitions with human-readable descriptions
- Implement validation for analysis periods and network selection
- Add support for dynamic time bucket configuration (default 30, user configurable)

#### Sample Implementation
```python
# config_utils.py - Metric definitions
def get_metric_info(metric_name):
    metric_info = {
        "block_gossip_time": {
            "title": "Block Gossip Time",
            "subtitle": "Time for block gossip to propagate to client (milliseconds)",
            "unit": "ms",
            "format": ".2f"
        },
        "head_time": {
            "title": "Head Time", 
            "subtitle": "Maximum time across all event types (head, block, blob) to reach client",
            "unit": "ms",
            "format": ".2f"
        },
        "gas_used": {
            "title": "Gas Used",
            "subtitle": "Total gas consumed in execution payload",
            "unit": "gas",
            "format": ".2e"
        },
        "time_difference": {
            "title": "Head vs Gossip Time Difference",
            "subtitle": "Difference between head time and block gossip time",
            "unit": "ms", 
            "format": ".2f"
        }
    }
    return metric_info.get(metric_name, {
        "title": metric_name.replace('_', ' ').title(),
        "subtitle": "No description available",
        "unit": "",
        "format": ".2f"
    })

def get_analysis_config():
    return {
        "default_time_buckets": 30,
        "max_propagation_time_ms": 12000,
        "default_gas_bin_size": 5_000_000,
        "min_samples_per_bin": 5,
        "supported_networks": ["mainnet", "holesky", "sepolia"],
        "visualization_themes": ["viridis", "plasma", "inferno"]
    }
```

### 2. Advanced Data Loading Implementation

#### Specific Changes
- Convert complex CTE queries into parameterized functions
- Implement intelligent caching with cache invalidation
- Add progress indicators for long-running queries
- Create data validation and quality checks

#### Sample Implementation
```python
# data_loaders.py - Complex query implementation
@st.cache_data(ttl=3600)  # 1 hour cache
def load_head_time_data(network, start_date, end_date):
    """
    Load head time data using complex CTE query from multiple event tables.
    This represents the maximum propagation time across all event types per client.
    """
    conn = get_database_connection()
    
    query = """
    WITH head_events AS (
        SELECT
            slot,
            slot_start_date_time,
            propagation_slot_start_diff as arrival_time,
            meta_client_name,
            meta_consensus_implementation,
            meta_client_geo_continent_code
        FROM beacon_api_eth_v1_events_head FINAL
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND meta_client_name != '' AND meta_client_name IS NOT NULL
            AND propagation_slot_start_diff < %(max_propagation)s
    ),
    block_events AS (
        SELECT
            slot,
            slot_start_date_time,
            propagation_slot_start_diff as arrival_time,
            meta_client_name,
            meta_consensus_implementation,
            meta_client_geo_continent_code
        FROM beacon_api_eth_v1_events_block FINAL
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND meta_client_name != '' AND meta_client_name IS NOT NULL
            AND propagation_slot_start_diff < %(max_propagation)s
    ),
    blob_events AS (
        SELECT
            slot,
            slot_start_date_time,
            MAX(propagation_slot_start_diff) as arrival_time,
            meta_client_name,
            meta_consensus_implementation,
            meta_client_geo_continent_code
        FROM beacon_api_eth_v1_events_blob_sidecar FINAL
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND meta_client_name != '' AND meta_client_name IS NOT NULL
            AND propagation_slot_start_diff < %(max_propagation)s
        GROUP BY slot, slot_start_date_time, meta_client_name, 
                 meta_consensus_implementation, meta_client_geo_continent_code
    ),
    all_events AS (
        SELECT * FROM head_events
        UNION ALL
        SELECT * FROM block_events  
        UNION ALL
        SELECT * FROM blob_events
    )
    SELECT
        slot,
        slot_start_date_time,
        MAX(arrival_time) as head_time,
        meta_client_name,
        meta_consensus_implementation,
        meta_client_geo_continent_code
    FROM all_events
    GROUP BY slot, slot_start_date_time, meta_client_name,
             meta_consensus_implementation, meta_client_geo_continent_code
    ORDER BY slot_start_date_time
    """
    
    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
        'max_propagation': get_analysis_config()['max_propagation_time_ms']
    }
    
    return pd.read_sql(query, conn, params=params)
```

### 3. Statistical Analysis and Metrics

#### Specific Changes
- Implement time bucketing algorithm as reusable function
- Create correlation analysis with statistical significance testing
- Add trend line calculations with confidence intervals
- Implement consensus implementation ranking system

#### Sample Implementation
```python
# metrics_calculators.py - Core analysis functions
def create_time_buckets(df, num_buckets=30):
    """
    Create equal-duration time buckets for temporal analysis.
    Follows the established algorithm from the Jupyter notebook.
    """
    min_time = df['slot_start_date_time'].min()
    max_time = df['slot_start_date_time'].max()
    time_range = max_time - min_time
    bucket_size = time_range / num_buckets
    
    bucket_edges = [min_time + i * bucket_size for i in range(num_buckets + 1)]
    
    df = df.copy()
    df['time_bucket'] = pd.cut(
        df['slot_start_date_time'],
        bins=bucket_edges,
        labels=[f"Bucket {i+1}" for i in range(num_buckets)]
    )
    
    # Add bucket metadata for visualization
    bucket_start_times = {f"Bucket {i+1}": bucket_edges[i] for i in range(num_buckets)}
    df['bucket_start_time'] = df['time_bucket'].map(bucket_start_times)
    
    return df

def calculate_correlation_analysis(df, x_col, y_col):
    """Calculate correlation with statistical significance."""
    from scipy.stats import pearsonr, linregress
    
    # Remove NaN values
    mask = df[[x_col, y_col]].notna().all(axis=1)
    clean_df = df.loc[mask]
    
    if len(clean_df) < 10:
        return None
    
    # Correlation analysis
    corr_coef, p_value = pearsonr(clean_df[x_col], clean_df[y_col])
    
    # Linear regression
    slope, intercept, r_value, reg_p_value, std_err = linregress(
        clean_df[x_col], clean_df[y_col]
    )
    
    return {
        'correlation': corr_coef,
        'p_value': p_value,
        'slope': slope,
        'intercept': intercept,
        'r_squared': r_value ** 2,
        'std_error': std_err,
        'sample_size': len(clean_df)
    }
```

### 4. Interactive Visualization System

#### Specific Changes
- Convert matplotlib plots to interactive Plotly visualizations
- Implement consistent ethPandaOps branding across all plots
- Add interactive features (zoom, pan, hover, selection)
- Create responsive layout for different screen sizes

#### Sample Implementation
```python
# plot_generators.py - Interactive visualizations
def create_gas_vs_arrival_scatter(data, x_metric, y_metric, color_by='slot_start_date_time'):
    """
    Create interactive scatter plot of gas usage vs arrival times.
    Includes trend line, correlation info, and time-based coloring.
    """
    from shared.ui_components import add_ethPandaOps_logo
    from config_utils import get_metric_info
    
    x_info = get_metric_info(x_metric)
    y_info = get_metric_info(y_metric)
    
    # Calculate correlation
    correlation_data = calculate_correlation_analysis(data, x_metric, y_metric)
    
    fig = px.scatter(
        data,
        x=x_metric,
        y=y_metric,
        color=color_by,
        title=f'{x_info["title"]} vs {y_info["title"]}<br><sub>Correlation: {correlation_data["correlation"]:.4f}, R²: {correlation_data["r_squared"]:.4f}</sub>',
        labels={
            x_metric: f'{x_info["title"]} ({x_info["unit"]})',
            y_metric: f'{y_info["title"]} ({y_info["unit"]})',
            color_by: 'Time'
        },
        hover_data=['meta_consensus_implementation', 'meta_client_geo_continent_code']
    )
    
    # Add trend line
    if correlation_data:
        x_range = np.linspace(data[x_metric].min(), data[x_metric].max(), 100)
        y_trend = correlation_data['slope'] * x_range + correlation_data['intercept']
        
        fig.add_trace(go.Scatter(
            x=x_range,
            y=y_trend,
            mode='lines',
            name=f'Trend Line (slope: {correlation_data["slope"]:.2e})',
            line=dict(dash='dash', color='red')
        ))
    
    # Styling
    fig.update_layout(
        height=600,
        showlegend=True,
        title={'font': {'size': 16}},
        xaxis_title_font_size=14,
        yaxis_title_font_size=14
    )
    
    return add_ethPandaOps_logo(fig)

def create_time_series_comparison(time_metrics, metrics_to_plot):
    """Create multi-axis time series plot for temporal analysis."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Primary axis: Gas metrics
    if 'gas_used' in metrics_to_plot:
        fig.add_trace(
            go.Scatter(
                x=time_metrics.index,
                y=time_metrics[('gas_used', 'mean')],
                name='Mean Gas Used',
                line=dict(color='#1f77b4'),
                mode='lines+markers'
            ),
            secondary_y=False
        )
    
    # Secondary axis: Timing metrics  
    if 'block_gossip_time' in metrics_to_plot:
        fig.add_trace(
            go.Scatter(
                x=time_metrics.index,
                y=time_metrics[('block_gossip_time', 'mean')],
                name='Mean Block Gossip Time',
                line=dict(color='#ff7f0e'),
                mode='lines+markers'
            ),
            secondary_y=True
        )
    
    # Axis labels
    fig.update_yaxes(title_text="Gas Used", secondary_y=False)
    fig.update_yaxes(title_text="Arrival Time (ms)", secondary_y=True)
    fig.update_xaxes(title_text="Time Bucket")
    
    fig.update_layout(
        title="Gas Usage and Arrival Times Over Time",
        height=500
    )
    
    return add_ethPandaOps_logo(fig)
```

### 5. Main Dashboard Integration

#### Specific Changes
- Create comprehensive UI with sidebar configuration
- Implement session state management for analysis parameters
- Add progress indicators and error handling
- Integrate all components with proper data flow

#### Sample Implementation
```python
# interactive_dashboard.py - Main orchestration
def main():
    apply_ethPandaOps_styling()
    
    # Initialize session state
    if 'analysis_data' not in st.session_state:
        st.session_state.analysis_data = {}
    if 'data_loaded' not in st.session_state:
        st.session_state.data_loaded = False
    
    st.markdown('<h1 class="main-header">⛽ Gas Usage Performance Analysis</h1>', unsafe_allow_html=True)
    
    # Sidebar Configuration
    st.sidebar.header("⚙️ Analysis Configuration")
    
    # Network selection
    network = st.sidebar.selectbox(
        "Select Network",
        get_analysis_config()['supported_networks'],
        index=0
    )
    
    # Period configuration
    st.sidebar.subheader("Analysis Periods")
    period1_col1, period1_col2 = st.sidebar.columns(2)
    with period1_col1:
        period1_start = st.date_input("Period 1 Start", value=datetime.now() - timedelta(days=14))
    with period1_col2:
        period1_end = st.date_input("Period 1 End", value=datetime.now() - timedelta(days=7))
    
    enable_comparison = st.sidebar.checkbox("Enable Period Comparison")
    
    if enable_comparison:
        period2_col1, period2_col2 = st.sidebar.columns(2)
        with period2_col1:
            period2_start = st.date_input("Period 2 Start", value=datetime.now() - timedelta(days=7))
        with period2_col2:
            period2_end = st.date_input("Period 2 End", value=datetime.now())
    
    # Advanced settings
    with st.sidebar.expander("Advanced Settings"):
        time_buckets = st.number_input("Number of Time Buckets", min_value=10, max_value=50, value=30)
        min_samples = st.number_input("Minimum Samples per Analysis", min_value=100, value=1000)
    
    # Data Loading
    if st.sidebar.button("🔄 Load Analysis Data", type="primary"):
        with st.spinner("Loading gas usage and performance data..."):
            try:
                # Load Period 1 data
                period1_data = load_complete_analysis_data(
                    network, period1_start, period1_end, "Period 1"
                )
                
                st.session_state.analysis_data['period1'] = period1_data
                
                if enable_comparison:
                    # Load Period 2 data
                    period2_data = load_complete_analysis_data(
                        network, period2_start, period2_end, "Period 2"
                    )
                    st.session_state.analysis_data['period2'] = period2_data
                
                st.session_state.data_loaded = True
                st.success("✅ Data loaded successfully!")
                
            except Exception as e:
                st.error(f"❌ Error loading data: {str(e)}")
                st.session_state.data_loaded = False
    
    # Main Analysis Display
    if st.session_state.data_loaded:
        display_analysis_dashboard()
    else:
        st.info("👆 Configure analysis parameters and click 'Load Analysis Data' to begin.")
        
        # Show example visualizations or data info
        st.markdown("### 📊 What This Analysis Provides")
        st.markdown("""
        - **Gas Usage vs Performance Correlation**: Understand how gas consumption affects block propagation
        - **Consensus Implementation Comparison**: Compare performance across different client implementations
        - **Temporal Analysis**: Track performance changes over time with configurable bucketing
        - **Geographic Insights**: Analyze performance variations by continent
        - **Statistical Analysis**: Correlation coefficients, trend lines, and percentile analysis
        """)
```

## Testing Strategy

### Unit Testing
- **Data Loading Functions**: Test query execution, data cleaning, and caching mechanisms
- **Metrics Calculators**: Validate statistical calculations, time bucketing accuracy, correlation analysis
- **Plot Generators**: Test Plotly figure generation, branding application, data formatting
- **Configuration Utilities**: Validate metric definitions, parameter validation, error handling

### Integration Testing
- **End-to-End Data Flow**: Test complete pipeline from database query to visualization display
- **Multi-Period Analysis**: Validate comparison functionality with different time periods
- **Interactive Features**: Test plot interactivity, filtering, zoom functionality
- **Session State Management**: Ensure proper state persistence across user interactions

### Validation Criteria
- **Data Accuracy**: Results match original Jupyter notebook calculations within 0.1% tolerance
- **Performance Benchmarks**: Page load time < 3 seconds, data loading < 30 seconds for typical queries
- **Visual Consistency**: All plots include ethPandaOps branding and follow design guidelines
- **Error Handling**: Graceful degradation for invalid inputs, network issues, empty datasets
- **Cross-Browser Compatibility**: Functionality verified in Chrome, Firefox, Safari

## Implementation Dependencies

### Phase 1: Foundation Setup
- [ ] Create directory structure and base files
- [ ] Implement configuration utilities with metric definitions
- [ ] Set up basic data loading framework
- Dependencies: Access to existing shared modules, ClickHouse database credentials

### Phase 2: Core Data Pipeline
- [ ] Implement complex multi-table data loading functions
- [ ] Create time bucketing and statistical calculation functions  
- [ ] Add data validation and quality checks
- Dependencies: Phase 1 completion, database schema understanding

### Phase 3: Visualization System
- [ ] Convert matplotlib plots to interactive Plotly visualizations
- [ ] Implement consistent branding and styling
- [ ] Add interactive features and responsive design
- Dependencies: Phase 2 completion, shared UI components

### Phase 4: Dashboard Integration
- [ ] Build comprehensive user interface
- [ ] Implement session state management
- [ ] Add configuration options and error handling
- Dependencies: Phase 3 completion, UX testing feedback

### Phase 5: Testing and Optimization
- [ ] Comprehensive testing across all components
- [ ] Performance optimization and caching improvements
- [ ] Documentation and user guidance
- Dependencies: Phase 4 completion, test data availability

## Risks and Considerations

### Implementation Risks
- **Query Complexity**: Complex CTE queries may have performance issues → Implement query optimization and caching strategies
- **Data Volume**: Large datasets may cause memory issues → Add pagination and streaming capabilities
- **Browser Performance**: Interactive plots with large datasets → Implement data sampling and progressive loading

### Performance Considerations
- **Database Load**: Multiple complex queries may impact database performance → Implement intelligent caching and query batching
- **Memory Usage**: Large DataFrames in session state → Add data cleanup and memory monitoring

### Security Considerations  
- **Database Credentials**: Ensure secure credential management → Use existing shared database utilities
- **Data Exposure**: Prevent exposure of sensitive network data → Implement proper access controls

## Expected Outcomes

- **Interactive Dashboard**: Fully functional Streamlit page replacing Jupyter notebook with enhanced user experience
- **Enhanced Analytics**: Additional interactive features not possible in static notebook format
- **User Adoption**: Accessible interface enabling broader team usage of gas performance analysis
- **Maintainability**: Modular architecture facilitating future enhancements and extensions

### Success Metrics
- **Functionality**: 100% feature parity with original notebook analysis
- **Performance**: < 30 seconds data loading time for typical 7-day analysis periods  
- **User Experience**: 90%+ user satisfaction score for interface usability
- **Code Quality**: 100% unit test coverage for core calculation functions
- **Documentation**: Complete inline help and metric explanations for all analysis components