"""
EthPandaOps Analysis Dashboard - Shared Utilities

This package provides reusable functionality for analysis pages:

Database & Infrastructure:
- database.py: ClickHouse connections
- filesystem.py: Cache and file management

Data Processing:
- parquet_utils.py: Xatu parquet file handling  
- data_utils.py: Generic data processing utilities

UI & Branding:
- ui_components.py: Common Streamlit components and styling

Ethereum:
- ethereum/: Ethereum beacon chain data utilities
"""

# Convenient imports for common functions
from .database import get_database_connection
from .filesystem import get_cache_dir
from .parquet_utils import calculate_parquet_urls, download_and_cache_parquet
from .data_utils import get_aggregate_function
from .ui_components import add_ethpandaops_logo, apply_ethpandaops_styling

# Ethereum-specific imports available as shared.ethereum.*
from . import ethereum

__all__ = [
    'get_database_connection',
    'get_cache_dir', 
    'calculate_parquet_urls',
    'download_and_cache_parquet',
    'get_aggregate_function',
    'add_ethpandaops_logo',
    'apply_ethpandaops_styling',
    'ethereum'
]
