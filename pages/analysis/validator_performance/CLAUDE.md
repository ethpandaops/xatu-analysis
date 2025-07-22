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

## Current Implementation Status

### Data Sources and Integrations
1. **ClickHouse Integration** ✅
   - Queries validator indices from `canonical_beacon_validators_pubkeys` table
   - Supports bulk validator lookups with efficient IN clause queries
   - Network-aware queries (though currently limited to mainnet)

2. **Beaconcha.in API Integration** ✅
   - Implemented via BeaconchainClient
   - Fetches comprehensive validator daily stats
   - Provides historical performance data

3. **Rated.network API Integration** ✅
   - Three endpoints implemented:
     - Effectiveness metrics endpoint for validator performance percentages
     - Attestations endpoint for detailed attestation data
     - Proposals endpoint for block proposal information
   - Currently limited to mainnet due to API constraints

### Implemented Metrics
- **Effectiveness Metrics**: Validator, attester, and proposer effectiveness percentages
- **Performance Tracking**: Uptime, correctness, inclusion delay
- **Block Production**: Proposed blocks, missed blocks, orphaned blocks
- **Attestations**: Missed attestations, orphaned attestations
- **Sync Committee**: Participation tracking
- **Slashing Events**: Both attester and proposer slashings
- **Financial Metrics**: Balance tracking, deposits, withdrawals (in ETH)
- **Data Export**: CSV download functionality for aggregated stats

### Additional Features
- **Date Exclusion**: Users can exclude specific date ranges from analysis
- **UTC Time Handling**: All timestamps properly converted to UTC
- **Bulk Operations**: Efficient handling of 100+ validators
- **Aggregated Statistics**: Daily summaries and per-validator breakdowns
- **Session State Management**: Proper configuration change detection

## Limitations and Future Work

### Current Limitations
1. **Network Support**: Currently limited to mainnet only (Rated API constraint)
2. **Visualizations**: No charts or plots implemented yet (plot_generators.py is empty)
3. **API Performance**: Sequential API calls instead of parallel fetching
4. **Caching**: No caching mechanism for API responses

### Future Enhancements
- Implement visualization layer with performance charts
- Add support for other networks when APIs become available
- Implement parallel API fetching for improved performance
- Add response caching to reduce API calls
- Enhance metrics_calculators.py with complex calculations

## Development Guidelines
- Always validate pubkey format before processing
- Handle bulk operations efficiently (100+ validators)
- Provide clear feedback for invalid inputs
- Maintain responsive UI during data loading
- Follow established patterns from other dashboards