# Gas Usage Performance Analysis

Interactive Streamlit dashboard for analyzing the relationship between gas usage and block arrival times in Ethereum networks, with support for multi-period comparisons and detailed consensus implementation analysis.

## Architecture  
Claude MUST read the `./CURSOR.mdc` file before making any changes to this component.

## Component Overview

This analysis module provides comprehensive gas usage vs performance correlation analysis through:

- **Multi-source Data Integration**: Complex ClickHouse queries combining block gossip, head events, and canonical block data
- **Statistical Analysis**: Time bucketing, correlation analysis, trend calculations, and consensus implementation ranking
- **Interactive Visualizations**: Plotly-based charts with ethPandaOps branding including scatter plots, time series, heatmaps, and geographic analysis
- **Comparative Analysis**: Support for period-over-period comparisons with statistical significance testing

## Key Features

- Real-time correlation analysis between gas usage and block propagation times
- Consensus implementation performance ranking and comparison
- Geographic performance analysis by continent
- Time bucket-based temporal analysis with configurable granularity
- Gas utilization binned analysis for performance impact assessment
- Statistical validation with significance testing

## Data Sources

- `beacon_api_eth_v1_events_block_gossip`: Block propagation timing data
- `beacon_api_eth_v1_events_head`, `beacon_api_eth_v1_events_block`, `beacon_api_eth_v1_events_blob_sidecar`: Head time calculations
- `canonical_beacon_block`: Gas usage and execution payload data

## Implementation Notes

- Follows xatu-analysis modular architecture with clear separation of concerns
- Implements sophisticated caching strategies for performance optimization
- Provides comprehensive data validation and quality checks
- Supports multiple visualization themes and interactive features