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


def get_network_config() -> Dict[str, Dict[str, Any]]:
    """Get detailed configuration for each supported network"""
    return {
        'mainnet': {
            'name': 'Ethereum Mainnet',
            'chain_id': 1,
            'description': 'Ethereum production network',
            'has_gas_data': True,
            'has_blob_data': True
        },
        'holesky': {
            'name': 'Holesky Testnet',
            'chain_id': 17000,
            'description': 'Ethereum staking testnet',
            'has_gas_data': True,
            'has_blob_data': True
        },
        'sepolia': {
            'name': 'Sepolia Testnet', 
            'chain_id': 11155111,
            'description': 'Ethereum application testnet',
            'has_gas_data': True,
            'has_blob_data': True
        },
        'hoodi': {
            'name': 'Hoodi Network',
            'chain_id': None,  # Add chain_id when available
            'description': 'Hoodi development network',
            'has_gas_data': True,
            'has_blob_data': True
        }
    }