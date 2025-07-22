import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

from shared.database import get_database_connection
from shared.parquet_utils import calculate_parquet_urls, download_and_cache_parquet  
from shared.ethereum.validators import load_validators_from_ethseer
from shared.ethereum.blocks import fetch_proposer_indices
from config_utils import get_supported_networks, get_data_source_options
from _table_verification import verify_table_structures, get_verified_query_templates

# Import polars functions - REQUIRED
from polars_data_loaders import (
    load_attestation_timing_data_polars,
    load_combined_analysis_data_polars,
    load_raw_attestation_data_for_slow_analysis
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Legacy pandas functions removed - using Polars only
# All data loading now handled by polars_data_loaders.py


def load_combined_analysis_data(start_time, end_time, network="mainnet", data_source="beacon_api"):
    """Load and combine all data needed for CDF analysis using Polars."""
    
    logger.info("Using Polars-optimized data loading for attestation CDF analysis")
    return load_combined_analysis_data_polars(start_time, end_time, network, data_source)