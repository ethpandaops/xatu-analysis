# Multi-Cluster Configuration System

This document describes the new multi-cluster ClickHouse support and centralized configuration system for the Xatu Analysis Dashboard.

## Overview

The application now supports:
- Multiple ClickHouse clusters
- Centralized configuration via YAML files
- Dynamic network discovery from ClickHouse tables
- Environment variable-based credentials management
- Local configuration overrides

## Configuration Files

### config.yaml
The main configuration file containing:
- Default ClickHouse cluster definitions
- Network configurations with genesis timestamps
- Application settings
- API integration endpoints

### config.local.yaml
User-specific overrides (gitignored):
- Additional ClickHouse clusters
- Custom networks
- Modified settings
- Copy `config.local.yaml.example` to `config.local.yaml` to get started

## ClickHouse Clusters

### Defining Clusters
Clusters are defined in the `clickhouse.clusters` section:

```yaml
clickhouse:
  clusters:
    xatu:
      host: clickhouse.xatu.ethPandaOps.io
      port: 443
      database: default
      protocol: https
      description: "Main Xatu ClickHouse cluster"
```

### Credentials
Credentials are pulled from environment variables:
- Pattern: `{CLUSTER_NAME}_CLICKHOUSE_USERNAME` and `{CLUSTER_NAME}_CLICKHOUSE_PASSWORD`
- Example: `XATU_CLICKHOUSE_USERNAME` and `XATU_CLICKHOUSE_PASSWORD`

### Using Multiple Clusters
```python
from shared.database import get_database_connection

# Connect to default cluster
conn = get_database_connection()

# Connect to specific cluster
conn = get_database_connection("my_cluster")
```

## Network Discovery

### Automatic Discovery
The system automatically discovers available networks by querying ClickHouse tables:
- Queries `canonical_beacon_block`, `libp2p_gossipsub_beacon_block`, and `beacon_api_eth_v1_events_block`
- Looks back 7 days by default
- Caches results for 60 minutes

### Configuration
```yaml
clickhouse:
  network_discovery:
    enabled: true
    tables:
      - canonical_beacon_block
      - libp2p_gossipsub_beacon_block
      - beacon_api_eth_v1_events_block
    lookback_days: 7
    cache_duration: 60  # minutes
```

### Static Networks
Define static networks in the `networks` section:
```yaml
networks:
  mainnet:
    name: "Ethereum Mainnet"
    chain_id: 1
    genesis_timestamp: 1606824023
    has_gas_data: true
    has_blob_data: true
    enabled: true
```

## Usage in Dashboards

### UI Components
Use the provided UI utilities for cluster and network selection:

```python
from shared.ui_utils import render_cluster_selector, render_network_selector

# In your Streamlit app
selected_cluster = render_cluster_selector("my_dashboard")
selected_network = render_network_selector("my_dashboard", selected_cluster)
```

### Data Queries
Query data from specific clusters:

```python
from shared.database import get_database_connection
import pandas as pd

# Get connection to selected cluster
conn = get_database_connection(selected_cluster)

# Query data
query = f"""
    SELECT * FROM canonical_beacon_block
    WHERE meta_network_name = '{selected_network}'
    LIMIT 100
"""
df = pd.read_sql(query, conn)
conn.close()
```

## API Integration

The configuration system is backward compatible with existing code:
- `shared.config.get_supported_networks()` now returns both static and discovered networks
- `shared.config.get_network_config()` includes all network configurations
- `shared.database.get_database_connection()` uses the new cluster system

## Environment Variables

Required environment variables:
```bash
# Default cluster (xatu)
XATU_CLICKHOUSE_USERNAME=your_username
XATU_CLICKHOUSE_PASSWORD=your_password

# Additional clusters (if defined in config.local.yaml)
MY_CLUSTER_CLICKHOUSE_USERNAME=username
MY_CLUSTER_CLICKHOUSE_PASSWORD=password

# API keys
BEACONCHAIN_API_KEY=your_key
RATED_API_KEY=your_key
```

## Testing

A test page is available at `/cluster_test` to:
- View all configured clusters
- Test cluster connections
- See discovered networks
- Execute sample queries

## Migration Guide

### For Existing Code
1. Replace hardcoded ClickHouse connections with `get_database_connection()`
2. Use `config_loader` for network configurations instead of hardcoded lists
3. Add cluster selector to dashboards for multi-cluster support

### For New Dashboards
1. Import UI utilities: `from shared.ui_utils import render_cluster_selector, render_network_selector`
2. Add selectors to sidebar
3. Pass selected cluster to `get_database_connection()`
4. Use selected network in queries

## Troubleshooting

### Missing Credentials
If you see "Missing credentials" errors:
1. Check environment variables are set correctly
2. Verify cluster name matches config (case-sensitive)
3. Ensure `.env` file is loaded

### Network Discovery Issues
If networks aren't discovered:
1. Check cluster connection is working
2. Verify tables exist and have recent data
3. Check `network_discovery.enabled` is true
4. Clear cache by restarting the app

### Configuration Not Loading
If changes to config files aren't reflected:
1. Restart the Streamlit app
2. Check YAML syntax is valid
3. Verify file permissions
4. Use the "Reload Config" button in the test page