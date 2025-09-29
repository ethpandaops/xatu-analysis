# Blob Mempool Analysis Dashboard

## Overview

The Blob Mempool Analysis dashboard tracks blob transactions in the mempool compared to blobs included in canonical beacon blocks, providing insights into mempool presence and inclusion rates across different Ethereum clients.

## Features

### 📊 Core Functionality
- **Slot-by-slot blob tracking**: Counts blobs in each canonical slot
- **Mempool correlation**: Matches mempool blob transactions with canonical blobs
- **Client comparison**: Analyzes performance across different sentry nodes
- **Match rate calculation**: Shows percentage of canonical blobs found in mempool beforehand

### 🎯 Key Metrics
- **Canonical Blob Count**: Number of blobs in canonical beacon blocks per slot
- **Mempool Blob Count**: Number of blob transactions observed in mempool (type 3 transactions)
- **Matching Blobs**: Blobs that were present in mempool before inclusion
- **Match Percentage**: Ratio of matching blobs to canonical blobs

### 📈 Visualizations
1. **Timeline Charts**: Show blob counts over time (canonical vs mempool)
2. **Match Percentage Charts**: Track inclusion efficiency over time
3. **Client Comparison**: Bar charts comparing client performance
4. **Correlation Scatter**: Relationship between canonical and mempool blobs
5. **Hourly Heatmaps**: Pattern analysis by client and time
6. **Dual-axis Charts**: Combined view of counts and percentages
7. **Blob Gas Analysis**: Track blob gas usage patterns across clients
8. **Blob Size Analysis**: Analyze blob sidecar size patterns and efficiency

### ⚙️ Configuration Options
- **Time Range Selection**: Predefined presets (1 hour to 1 week) or custom ranges
- **Client Selection**: Multi-select from available clients with blob transaction data
- **View Modes**: 
  - Overview: High-level summary charts
  - Detailed: Individual client breakdowns
  - Comparison: Side-by-side client analysis
- **Chart Types**: Line charts, bar charts, scatter plots, heatmaps
- **Filters**: Option to exclude slots with zero blobs

## How It Works

### Data Sources
1. **Canonical Data**: `beacon_api_eth_v2_beacon_block` + `beacon_api_eth_v1_events_blob_sidecar`
2. **Mempool Data**: `mempool_transaction` table (filtered for type 3 blob transactions)
   - Uses `blob_hashes` field for hash matching
   - Includes `blob_gas`, `blob_gas_fee_cap`, and `blob_sidecars_size` for additional analysis
   - Filters by `meta_client_name` for client-specific analysis

### Analysis Process
1. **Slot Identification**: Find all slots in the selected time range
2. **Blob Extraction**: Get blob hashes from canonical blocks
3. **Mempool Lookup**: Query mempool for blob transactions 24 seconds before each slot
4. **Hash Matching**: Compare blob hashes between canonical and mempool data
5. **Statistics Calculation**: Compute match rates and aggregated metrics

### Time Window Logic
- Mempool transactions are matched within a 24-second window before slot start time
- This accounts for network propagation delays and gives sufficient time for blob inclusion

## Technical Implementation

### Module Structure
```
blob_mempool_analysis/
├── __init__.py                 # Package initialization
├── page.py                     # Main entry point
├── interactive_dashboard.py    # Streamlit UI components
├── queries.py                  # ClickHouse SQL queries
├── loader.py                   # Data loading and caching
├── plot_generators.py          # Plotly visualization functions
├── config_utils.py             # Configuration and validation
└── README.md                   # Documentation
```

### Key Components
- **Queries**: Optimized ClickHouse SQL for blob and mempool data
- **Loader**: Cached data loading with error handling
- **Plot Generators**: Reusable Plotly chart functions
- **Interactive Dashboard**: Streamlit UI with sidebar controls
- **Config Utils**: Validation rules and default settings

### Performance Optimizations
- **Caching**: 5-minute TTL on data queries
- **Query Limits**: Maximum 10,000 slots per analysis
- **Chunked Loading**: Large datasets loaded in batches
- **Efficient Joins**: Optimized SQL with proper indexing hints

## Usage Examples

### Typical Use Cases
1. **Blob Propagation Analysis**: How quickly do blobs propagate through the mempool?
2. **Client Performance Comparison**: Which clients see blobs in mempool most effectively?
3. **Network Health Monitoring**: Are blob transactions being properly distributed?
4. **Inclusion Rate Tracking**: What percentage of included blobs were pre-announced in mempool?

### Recommended Workflows
1. Start with **Overview** mode for general trends
2. Use **Client Comparison** to identify performance differences
3. Switch to **Detailed** mode for specific client investigation
4. Apply filters to focus on blob-heavy periods

## Configuration

### Time Range Recommendations
- **Real-time Monitoring**: Last 1-6 hours
- **Daily Analysis**: Last 24 hours
- **Pattern Analysis**: Last 3-7 days
- **Historical Studies**: Custom ranges up to 1 week

### Client Selection
- Select multiple clients for comparison
- Focus on specific client types (consensus/execution layer combinations)
- Include diverse geographical locations for comprehensive analysis

## Limitations

### Data Availability
- Requires both beacon block data and mempool transaction data
- Mempool data availability varies by client and network
- Some clients may have incomplete mempool transaction logging

### Analysis Scope
- Limited to 24-second lookback window for mempool matching
- Does not track blob propagation beyond immediate inclusion
- Cannot analyze blobs that were never included in canonical blocks

### Performance Constraints
- Maximum 7-day analysis window
- Large time ranges may have reduced granularity
- Real-time data may have slight delays due to data pipeline processing

## Future Enhancements

### Potential Improvements
- **Real-time Streaming**: Live blob tracking dashboard
- **Geographic Analysis**: Client performance by region
- **Blob Size Metrics**: Analysis of blob transaction sizes
- **Advanced Filtering**: Filter by blob count, transaction size, etc.
- **Export Functionality**: CSV/JSON data export options
- **Alert System**: Notifications for anomalous blob patterns

### Additional Metrics
- **Propagation Delay**: Time from mempool to inclusion
- **Coverage Analysis**: Percentage of network that saw each blob
- **Redundancy Metrics**: How many clients saw the same blobs
- **Miss Rate Analysis**: Why some blobs weren't seen in mempool
- **Blob Gas Efficiency**: Analysis of blob gas usage patterns
- **Size Optimization**: Blob sidecar size analysis and efficiency metrics
- **Fee Analysis**: Blob gas fee cap patterns and market behavior
