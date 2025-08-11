"""
Shared configuration utilities for ethPandaOps Analysis Dashboard
"""
import os
from typing import Dict, Any
from .config_loader import config_loader


def load_env_config() -> Dict[str, Any]:
    """Load environment configuration for analysis modules (deprecated - use config_loader)"""
    # This function is kept for backward compatibility
    # Returns a minimal config based on the default cluster
    try:
        cluster = config_loader.get_clickhouse_cluster()
        return {
            'clickhouse_host': cluster.get('host'),
            'clickhouse_port': cluster.get('port'),
            'clickhouse_user': cluster.get('username'),
            'clickhouse_password': cluster.get('password'),
            'clickhouse_database': cluster.get('database', 'default'),
        }
    except:
        return {
            'clickhouse_host': os.getenv('XATU_CLICKHOUSE_HOST'),
            'clickhouse_port': os.getenv('XATU_CLICKHOUSE_PORT', '443'),
            'clickhouse_user': os.getenv('XATU_CLICKHOUSE_USERNAME'),
            'clickhouse_password': os.getenv('XATU_CLICKHOUSE_PASSWORD'),
            'clickhouse_database': os.getenv('XATU_CLICKHOUSE_DATABASE', 'default'),
        }


def get_data_cache_dir() -> str:
    """Get the data cache directory for analysis modules"""
    app_config = config_loader.get_app_config()
    return app_config.get('data_cache_dir', os.getenv('DATA_CACHE_DIR', './data_cache'))


def get_supported_networks() -> list:
    """Get list of supported Ethereum networks across all analysis modules"""
    return config_loader.get_supported_networks()


def get_network_genesis_timestamp(network: str) -> int:
    """Get the genesis timestamp for a specific network.
    
    Args:
        network: Network name (mainnet, holesky, sepolia, etc.)
        
    Returns:
        Genesis timestamp in seconds since epoch, or mainnet genesis if network not found
    """
    return config_loader.get_network_genesis_timestamp(network)


def get_network_config() -> Dict[str, Dict[str, Any]]:
    """Get detailed configuration for each supported network"""
    return config_loader.get_networks()