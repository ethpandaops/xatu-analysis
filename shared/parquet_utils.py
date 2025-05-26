"""
Parquet file utilities for Xatu data
"""
import streamlit as st
import pandas as pd
import requests
import hashlib
from datetime import datetime, timedelta
from .filesystem import get_cache_dir


def calculate_parquet_urls(start_date_str, end_date_str, network, table_name):
    """Calculate the parquet file URLs needed for a date range."""
    start_date = datetime.strptime(start_date_str.replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
    end_date = datetime.strptime(end_date_str.replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
    
    urls = []
    current_date = start_date.date()
    end_date_only = end_date.date()
    
    # Show what dates will be downloaded for user awareness
    date_count = (end_date_only - current_date).days + 1
    st.info(f"📅 Will download {date_count} day(s) from {current_date} to {end_date_only}")
    
    while current_date <= end_date_only:
        # Format: https://data.ethpandaops.io/xatu/NETWORK/databases/DATABASE/TABLE/YYYY/M/D.parquet
        url = f"https://data.ethpandaops.io/xatu/{network}/databases/default/{table_name}/{current_date.year}/{current_date.month}/{current_date.day}.parquet"
        urls.append((url, current_date))
        current_date += timedelta(days=1)
    
    return urls


def download_and_cache_parquet(url, cache_dir):
    """Download and cache a parquet file locally."""
    # Create a hash of the URL for the filename
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_file = cache_dir / f"{url_hash}.parquet"
    
    # Check if file exists and is recent (less than 1 day old)
    if cache_file.exists():
        file_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        if file_age < timedelta(days=1):
            try:
                return pd.read_parquet(cache_file)
            except Exception:
                # If file is corrupted, delete and re-download
                cache_file.unlink()
    
    # Download the file
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Save to cache
        with open(cache_file, 'wb') as f:
            f.write(response.content)
        
        # Read and return
        return pd.read_parquet(cache_file)
    except requests.exceptions.RequestException as e:
        st.warning(f"Could not download {url}: {e}")
        return pd.DataFrame()
