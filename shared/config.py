"""
Shared configuration utilities for EthPandaOps Analysis Dashboard
"""
import os
from typing import Dict, Any


def load_env_config() -> Dict[str, Any]:
    """Load environment configuration for analysis modules"""
    return {
        'clickhouse_host': os.getenv('CLICKHOUSE_HOST'),
        'clickhouse_port': os.getenv('CLICKHOUSE_PORT'),
        'clickhouse_user': os.getenv('CLICKHOUSE_USER'),
        'clickhouse_password': os.getenv('CLICKHOUSE_PASSWORD'),
        'clickhouse_database': os.getenv('CLICKHOUSE_DATABASE', 'default'),
    }


def get_data_cache_dir() -> str:
    """Get the data cache directory for analysis modules"""
    return os.getenv('DATA_CACHE_DIR', './data_cache')