# Validator Performance Dashboard

## Overview
The Validator Performance Dashboard enables users to analyze the performance of one or more Ethereum validators by their public keys (pubkeys). This dashboard supports bulk input of 100+ validators and provides comprehensive performance metrics and visualizations.

## Purpose
- Analyze validator performance metrics across different time periods
- Support bulk analysis of multiple validators simultaneously
- Provide insights into validator effectiveness and consistency
- Enable comparative analysis between validators

## Component Structure

### Core Modules
1. **page.py** - Entry point that imports and runs the interactive dashboard
2. **interactive_dashboard.py** - Main UI orchestration with configuration interface
3. **config_utils.py** - Validator pubkey parsing and validation utilities
4. **data_loaders.py** - Data loading functionality (future: ClickHouse queries)
5. **metrics_calculators.py** - Performance metric calculations
6. **plot_generators.py** - Visualization generation functions

### Architecture Pattern
This dashboard follows the established modular pattern used in other analysis dashboards:
- Separation of concerns between UI, data loading, calculations, and visualizations
- Session state management with component-specific prefixes
- Configuration-driven data loading and visualization

## Configuration Patterns

### Validator Input
- Multi-line text area supporting bulk paste operations
- One validator pubkey per line
- Automatic validation and cleaning of input
- Support for 0x-prefixed and non-prefixed pubkeys

### Network Selection
- Supports all configured networks (mainnet, holesky, sepolia, hoodi)
- Network selection affects available data and validator sets

### Time Range Configuration
- Predefined ranges (Last 24 hours, 7 days, 30 days, etc.)
- Custom date range selection
- Before/After specific date options

### Session State Keys
All session state keys are prefixed with `validator_performance_` to avoid conflicts:
- `validator_performance_network` - Selected network
- `validator_performance_time_range` - Selected time range configuration
- `validator_performance_validator_pubkeys` - List of validated pubkeys
- `validator_performance_last_config` - Previous configuration for change detection
- `validator_performance_data_loaded` - Boolean flag for data loading status

## Future Integration Points

### ClickHouse Integration
- Query validator attestations and block proposals
- Aggregate performance metrics over time ranges
- Support for efficient bulk validator queries

### Beaconcha.in API Integration
- Fetch additional validator metadata
- Cross-reference performance data
- Provide validator status and history

### Planned Metrics
- Attestation effectiveness rate
- Block proposal success rate
- Sync committee participation
- Validator uptime and consistency
- Rewards and penalties tracking

## Development Guidelines
- Always validate pubkey format before processing
- Handle bulk operations efficiently (100+ validators)
- Provide clear feedback for invalid inputs
- Maintain responsive UI during data loading
- Follow established patterns from other dashboards