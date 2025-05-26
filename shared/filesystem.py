"""
File system utilities for ethPandaOps Analysis Dashboard
"""
from pathlib import Path


def get_cache_dir():
    """Get the cache directory for parquet files."""
    cache_dir = Path(".cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
