"""
Shared configuration utilities for ethPandaOps Analysis Dashboard
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


def get_supported_networks() -> list:
    """Get list of supported Ethereum networks across all analysis modules"""
    return [
        'mainnet',
        'holesky', 
        'sepolia',
        'hoodi'
    ]


def get_network_genesis_timestamp(network: str) -> int:
    """Get the genesis timestamp for a specific network.
    
    Args:
        network: Network name (mainnet, holesky, sepolia, etc.)
        
    Returns:
        Genesis timestamp in seconds since epoch, or mainnet genesis if network not found
    """
    config = get_network_config()
    if network in config and config[network].get('genesis_timestamp'):
        return config[network]['genesis_timestamp']
    # Default to mainnet genesis if not found
    return 1606824023


def get_network_config() -> Dict[str, Dict[str, Any]]:
    """Get detailed configuration for each supported network"""
    return {
        'mainnet': {
            'name': 'Ethereum Mainnet',
            'chain_id': 1,
            'description': 'Ethereum production network',
            'genesis_timestamp': 1606824023,  # December 1, 2020, 12:00:23 PM UTC
            'has_gas_data': True,
            'has_blob_data': True
        },
        'holesky': {
            'name': 'Holesky Testnet',
            'chain_id': 17000,
            'description': 'Ethereum staking testnet',
            'genesis_timestamp': 1695902400,  # September 28, 2023, 12:00:00 PM UTC
            'has_gas_data': True,
            'has_blob_data': True
        },
        'sepolia': {
            'name': 'Sepolia Testnet', 
            'chain_id': 11155111,
            'description': 'Ethereum application testnet',
            'genesis_timestamp': 1655733600,  # June 20, 2022, 12:00:00 PM UTC
            'has_gas_data': True,
            'has_blob_data': True
        },
        'hoodi': {
            'name': 'Hoodi Network',
            'chain_id': None,  # Add chain_id when available
            'description': 'Hoodi development network',
            'genesis_timestamp': 1742213400,  # January 18, 2025, 11:30:00 AM UTC
            'has_gas_data': True,
            'has_blob_data': True
        }
    }