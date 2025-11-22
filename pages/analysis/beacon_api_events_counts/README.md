# Beacon API Events Timing Analysis

An interactive Streamlit dashboard for analyzing timing metrics of Beacon API events and LibP2P gossipsub messages in Ethereum networks.

## Overview

This analysis page provides comprehensive timing analysis of events from two primary data sources:

### Data Sources
- **Beacon API Events**: block, head, blob_sidecar, attestation, sync_committee
- **LibP2P Gossipsub**: beacon_block, beacon_attestation, data_column_sidecar, blob_sidecar

The dashboard tracks event propagation delays by measuring time differences between when events occur and when they are received by various consensus clients.

## Features

### Grouping & Filtering
- **Proposer Grouping**: Analyze timing by proposer characteristics (node type, CL/EL client, architecture, operator, region, datacenter, or combinations)
- **Receiver Grouping**: Analyze timing by event receiver (CL client type or specific client instances)
- **Multi-dimensional Filtering**: Filter by proposer metadata, receiver client types, and time ranges

### Visualization Types
- **Time Series**: Event timing trends over time with percentile bands
- **Boxplots**: Distribution analysis grouped by proposer/receiver characteristics
- **Histograms**: Timing distribution with detailed statistics
- **Statistical Summary**: Comprehensive statistical breakdowns by grouping

### Advanced Controls
- **Blob Count Bucketing**: Group analysis by number of blobs per slot
- **Outlier Handling**: Multiple methods (IQR, percentile capping, z-score)
- **Data Sampling**: Configurable sampling rates for large datasets
- **Unlimited Mode**: Query complete datasets with safety confirmations
- **Performance Thresholds**: Cap extreme outliers for focused analysis

## Architecture

### Module Structure
```
beacon_api_events_timing/
├── __init__.py                 # Package initialization
├── page.py                     # Streamlit page entry point
├── interactive_dashboard.py    # Main dashboard UI and configuration
├── loader.py                   # Data loading and caching logic
├── queries.py                  # SQL query builders
├── plot_generators.py          # Visualization rendering functions
└── chart_functions.py          # Additional chart utilities
```

### Data Flow
1. **Configuration** (`interactive_dashboard.py`): User selects data source, event type, groupings, filters, and visualization options
2. **Query Building** (`queries.py`): Constructs SQL queries based on configuration, with dynamic grouping expressions
3. **Data Loading** (`loader.py`): Fetches data from ClickHouse with caching, applies sampling and limits
4. **Visualization** (`plot_generators.py`, `chart_functions.py`): Renders charts based on selected visualization type

### Key Components

#### Grouping Expressions (`loader.py`)
- **Proposer Groups**: Maps grouping options to SQL expressions using validator metadata (vm table)
- **Receiver Groups**: Maps receiver grouping to CL client metadata fields

#### Query Builders (`queries.py`)
- **Time Series**: Aggregates timing metrics over time windows
- **Grouped Samples**: Fetches individual samples with proposer/receiver metadata
- **Simple Samples**: Fetches raw timing data without grouping

#### Plot Generators (`plot_generators.py`)
- Time series with percentile bands (P50, P75, P95)
- Grouped boxplots with outlier handling
- Data summary metrics
- Histogram distributions

## Usage

### Basic Analysis
1. Select data source (Beacon API or LibP2P)
2. Choose event type
3. Configure time range
4. Select grouping dimensions
5. Click "Analyze Now"

### Advanced Features

#### Blob Bucketing
Enable to analyze how timing varies with blob count. Useful for identifying performance degradation with higher blob counts.

#### Unlimited Mode
For comprehensive analysis across large time ranges:
1. Enable "Unlimited Mode"
2. Confirm safety check (queries may take 5-15 minutes)
3. Optionally enable server-side aggregation for better performance

#### Outlier Control
- **IQR Method**: Filters values beyond 1.5×IQR from quartiles
- **Percentile**: Caps at specified percentile (e.g., 95th)
- **Z-Score**: Removes values beyond N standard deviations

## Dependencies

### Shared Utilities
- `shared.database`: ClickHouse connection management
- `shared.header`: Global UI header and network selection
- `shared.ethereum.validator_filters`: Validator metadata filtering

### Data Requirements
- Beacon API event tables or LibP2P gossipsub tables in ClickHouse
- Validator metadata (vm) table for proposer grouping
- Client metadata fields (meta_client_*) for receiver grouping

## Performance Considerations

- **Sampling**: Auto-adjusts based on time range to prevent query timeouts
- **Caching**: 5-minute TTL on data queries
- **Record Limits**: Configurable max records (default: 500k, max: 5M)
- **Threshold Capping**: Performance threshold removes extreme outliers before visualization

## Example Queries

### Timing by CL Client (Proposer)
- Grouping: "CL Client"
- Shows which consensus clients propose blocks with better/worse event timing

### Timing by Receiver Client
- Receiver Grouping: "CL Client Type"
- Shows which clients receive and report events faster

### Regional Performance
- Proposer Grouping: "Region"
- Identifies geographic latency patterns

### Architecture Impact
- Proposer Grouping: "Architecture"
- Compares timing across different hardware configurations
