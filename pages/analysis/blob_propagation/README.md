# Blob Propagation Analysis Dashboard

## Overview

The Blob Propagation Analysis dashboard tracks how blob sidecar events propagate across the Ethereum network, analyzing the flow of blob data from proposer groups to attester groups. This analysis provides insights into network propagation patterns, client coverage, and the effectiveness of blob distribution mechanisms.

## Features

### 📊 Core Functionality
- **Proposer-Attester Analysis**: Tracks blob propagation from specific proposer groups to attester groups
- **Network Coverage Mapping**: Shows which attester groups receive blob data from which proposers
- **Propagation Pattern Analysis**: Identifies propagation delays and coverage gaps
- **Client Performance Comparison**: Analyzes blob propagation effectiveness across different client combinations

### 🎯 Key Metrics
- **Unique Blobs Seen**: Number of distinct blob sidecars observed by each attester group
- **Propagation Coverage**: Percentage of attester groups that received blob data from each proposer
- **Propagation Delay**: Time between blob proposal and reception by attester groups
- **Network Efficiency**: Overall blob distribution effectiveness across the network

### 📈 Visualizations
1. **Propagation Heatmap**: Shows blob propagation patterns between proposer and attester groups
2. **Timeline Charts**: Track blob propagation over time with coverage metrics
3. **Coverage Charts**: Display propagation coverage percentages and patterns
4. **Scatter Plots**: Relationship between proposer activity and attester coverage
5. **Box Plots**: Distribution analysis of propagation metrics
6. **Network Diagrams**: Visual representation of blob propagation paths
7. **Summary Dashboard**: High-level overview of propagation statistics
8. **Metrics Tables**: Detailed numerical breakdown of propagation data

### ⚙️ Configuration Options
- **Time Range Selection**: Predefined presets (1 hour to 1 week) or custom ranges
- **Proposer Group Selection**: Multi-select from available proposer groups
- **Attester Group Selection**: Multi-select from available attester groups
- **View Modes**: 
  - Overview: High-level summary charts
  - Detailed: Individual group breakdowns
  - Comparison: Side-by-side group analysis
- **Chart Types**: Heatmaps, line charts, scatter plots, box plots
- **Filters**: Option to focus on specific time periods or group combinations

## How It Works

### Data Sources
1. **Beacon Block Data**: `beacon_api_eth_v2_beacon_block` for slot and proposer information
2. **Blob Sidecar Events**: `beacon_api_eth_v1_events_blob_sidecar` for blob propagation tracking
3. **MEV Relay Data**: `int_block_mev_head` for identifying MEV-delivered blocks
4. **Node Classification**: Network configuration files for proposer/attester group mapping

### Analysis Process
1. **Slot Identification**: Find all eligible slots in the selected time range
2. **Proposer Group Mapping**: Map proposer indices to proposer groups using network configuration
3. **Blob Event Collection**: Gather blob sidecar events for each slot
4. **Attester Group Mapping**: Map attester nodes to attester groups
5. **Propagation Analysis**: Track which attester groups received blob data from which proposers
6. **Statistics Calculation**: Compute coverage rates and propagation metrics

### Group Classification Logic
- **Proposer Groups**: Classified based on client type, version, and network configuration
- **Attester Groups**: Grouped by similar criteria to analyze propagation patterns
- **MEV Detection**: Identifies slots delivered via MEV relays for separate analysis

## Technical Implementation

### Module Structure
```
blob_propagation/
├── __init__.py                 # Package initialization
├── page.py                     # Main entry point
├── interactive_dashboard.py    # Streamlit UI components
├── queries.py                  # ClickHouse SQL queries
├── loader.py                   # Data loading and caching
├── plot_generators.py          # Plotly visualization functions
└── README.md                   # Documentation
```

### Key Components
- **Queries**: Optimized ClickHouse SQL with CTE-based modular approach
- **Loader**: Cached data loading with network configuration integration
- **Plot Generators**: Reusable Plotly chart functions for various visualizations
- **Interactive Dashboard**: Streamlit UI with comprehensive sidebar controls
- **Network Mapping**: YAML-based configuration for node group classification

### Performance Optimizations
- **Caching**: 5-minute TTL on data queries
- **Query Limits**: Maximum 10,000 slots per analysis
- **Chunked Loading**: Large datasets loaded in batches
- **Efficient Joins**: Optimized SQL with proper indexing hints
- **CTE Structure**: Modular query components for better performance

## Usage Examples

### Typical Use Cases
1. **Network Health Monitoring**: How effectively are blobs propagating across the network?
2. **Client Performance Analysis**: Which proposer-attester combinations work best?
3. **Propagation Delay Analysis**: Are there systematic delays in blob distribution?
4. **Coverage Gap Identification**: Which parts of the network are missing blob data?

### Recommended Workflows
1. Start with **Overview** mode for general propagation trends
2. Use **Heatmap** visualization to identify propagation patterns
3. Switch to **Detailed** mode for specific group investigation
4. Apply filters to focus on specific time periods or group combinations

## Configuration

### Time Range Recommendations
- **Real-time Monitoring**: Last 1-6 hours
- **Daily Analysis**: Last 24 hours
- **Pattern Analysis**: Last 3-7 days
- **Historical Studies**: Custom ranges up to 1 week

### Group Selection
- Select multiple proposer groups for comparison
- Focus on specific attester groups for targeted analysis
- Include diverse client combinations for comprehensive coverage

### Network Configuration
- Proposer and attester groups are defined in network YAML files
- Groups are classified by client type, version, and other criteria
- MEV relay detection is automatically handled

## Limitations

### Data Availability
- Requires both beacon block data and blob sidecar event data
- Blob sidecar event data availability varies by client and network
- Some clients may have incomplete blob event logging

### Analysis Scope
- Limited to blob sidecar events (not blob transactions)
- Cannot track blob propagation beyond the beacon chain
- Does not analyze blob content or validity

### Performance Constraints
- Maximum 7-day analysis window
- Large time ranges may have reduced granularity
- Real-time data may have slight delays due to data pipeline processing

## Future Enhancements

### Potential Improvements
- **Real-time Streaming**: Live blob propagation monitoring
- **Geographic Analysis**: Propagation patterns by region
- **Blob Content Analysis**: Analysis of blob data itself
- **Advanced Filtering**: Filter by blob count, propagation delay, etc.
- **Export Functionality**: CSV/JSON data export options
- **Alert System**: Notifications for propagation anomalies

### Additional Metrics
- **Propagation Latency**: Detailed timing analysis
- **Redundancy Analysis**: How many paths each blob takes
- **Miss Rate Analysis**: Why some attester groups don't receive blobs
- **Network Topology**: Analysis of propagation paths
- **Client Version Impact**: How client versions affect propagation
- **MEV vs Non-MEV**: Comparison of propagation patterns for different block types

## Related Analysis

This dashboard complements other blob-related analyses in the Xatu Analysis suite:
- **Blob Mempool Analysis**: Tracks blob transactions in the mempool
- **PeerDAS Analysis**: Analyzes data availability sampling patterns
- **Block Producer Performance**: Overall block production metrics

## Technical Notes

### Query Architecture
- Uses modular CTE approach similar to PeerDAS Analysis V2
- Optimized for ClickHouse distributed queries
- Includes proper handling of reorged blocks and MEV relays

### Data Validation
- Validates blob data availability before analysis
- Handles edge cases like empty slots and missing data
- Provides clear error messages for data issues

### Caching Strategy
- 5-minute TTL for most queries
- Separate caching for network configuration
- Efficient cache invalidation on parameter changes



