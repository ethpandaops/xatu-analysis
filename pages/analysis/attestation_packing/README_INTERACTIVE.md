# Interactive Attestation Packing Analysis Dashboard

This interactive dashboard provides a web-based interface for analyzing Ethereum attestation packing metrics without the need to run all chart generations in a Jupyter notebook.

## Features

- **Interactive Parameter Selection**: Choose networks, time ranges, clients, and metrics dynamically
- **Real-time Data Loading**: Connect to ClickHouse and load data on-demand
- **Multiple Visualization Types**: Before/after comparisons, distributions, and time series
- **Client-specific Analysis**: Filter by consensus client implementations
- **Statistics Summary**: Detailed stats tables for selected metrics

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Make sure your `.env` file contains the ClickHouse credentials:

```bash
XATU_CLICKHOUSE_USERNAME=your_username
XATU_CLICKHOUSE_PASSWORD=your_password
XATU_CLICKHOUSE_HOST=your_host
```

### 3. Run the Dashboard

```bash
streamlit run interactive_dashboard.py
```

The dashboard will open in your browser at `http://localhost:8501`

## Usage Guide

### 1. Configuration (Sidebar)
- **Network**: Select mainnet, holesky, or sepolia
- **Time Range**: Choose predefined ranges or set custom dates
- **Load Data**: Click to fetch data from ClickHouse

### 2. Analysis Configuration
- **Select Clients**: Choose which consensus clients to analyze
- **Select Metric**: Pick the metric you want to visualize

### 3. Visualizations
- **Before/After Comparison**: Compare metrics before and after an event
- **Distribution**: View the distribution of metrics across clients
- **Time Series**: See how metrics change over time

### 4. Data Exploration
- **Statistics Summary**: View detailed statistics by client
- **Raw Data Explorer**: Examine the underlying data

## Available Metrics

| Metric | Description |
|--------|-------------|
| `aggregation_efficiency` | Ratio of unique validators to total attestations (higher = better) |
| `optimal_inclusion_rate` | Percentage of validators included with 1-slot delay |
| `unique_validator_indexes` | Number of unique validators per block |
| `avg_attestation_inclusion_delay` | Average delay in slots between attestation and inclusion |
| `total_attestations` | Total number of attestations per block |
| `avg_validators_per_attestation` | Average number of validators per attestation |

## Example Use Cases

### 1. Electra Fork Analysis
- Select "Electra Fork Analysis (May 2025)" time range
- Choose multiple clients (lighthouse, prysm, teku, etc.)
- Compare `aggregation_efficiency` before/after the fork
- Use "Before/After Comparison" visualization

### 2. Client Performance Comparison
- Set custom time range for recent data
- Select all available clients
- Analyze `optimal_inclusion_rate` distribution
- Use "Distribution" visualization

### 3. Temporal Analysis
- Choose a longer time range
- Select specific clients of interest
- Track `unique_validator_indexes` over time
- Use "Time Series" visualization

## Performance Notes

- Data loading may take 30-60 seconds depending on time range size
- Use smaller time ranges for faster loading
- The dashboard caches data in session state for quick re-analysis
- Consider using predefined time ranges for optimal performance

## Troubleshooting

### Connection Issues
- Verify ClickHouse credentials in `.env` file
- Check network connectivity to ClickHouse host
- Ensure proper VPN connection if required

### Memory Issues
- Use smaller time ranges if encountering memory problems
- Restart the dashboard if performance degrades
- Consider analyzing fewer clients simultaneously

### Data Issues
- Ensure selected time range has available data
- Check that the network has attestation data for the period
- Some metrics may be NaN for blocks with unusual attestation patterns

## Technical Details

The dashboard is built using:
- **Streamlit**: Web interface framework
- **Plotly**: Interactive charting library
- **Pandas**: Data manipulation and analysis
- **ClickHouse**: Database connection via SQLAlchemy

The analysis logic is derived from the comprehensive Jupyter notebook but optimized for interactive use with caching and on-demand loading.