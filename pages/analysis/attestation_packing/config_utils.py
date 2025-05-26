#!/usr/bin/env python3
"""
Interactive Attestation Packing Analysis Dashboard

This Streamlit app provides an interactive interface for analyzing attestation packing metrics
from the Ethereum beacon chain. Users can select different parameters and view metrics dynamically.

Run with: streamlit run interactive_dashboard.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import os
import requests
import hashlib
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from pathlib import Path
import dotenv

# Load environment variables
dotenv.load_dotenv()

# Page configuration is handled by the main app.py
# Removed st.set_page_config() to avoid conflict with main app navigation

# Custom CSS for minimal branding (working with Streamlit's default light theme)
st.markdown("""
<style>
    
    /* Main header styling */
    .main-header {
        text-align: center;
        color: #1e40af;
        border-bottom: 3px solid #3b82f6;
        padding-bottom: 1rem;
        margin-bottom: 2rem;
    }
    
    /* Metric cards */
    .metric-card {
        background: #f8fafc;
        padding: 1.5rem;
        border-radius: 10px;
        border: 1px solid #e2e8f0;
        margin: 0.5rem 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    /* Metric description box */
    .metric-description {
        background: #eff6ff;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
        border-left: 4px solid #3b82f6;
    }
    
    .metric-title {
        font-size: 1.2rem;
        font-weight: 600;
        color: #1e40af;
        margin-bottom: 0.5rem;
    }
    
    .metric-subtitle {
        color: #475569;
        line-height: 1.5;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False
if 'slot_metrics_df' not in st.session_state:
    st.session_state.slot_metrics_df = None
if 'validators' not in st.session_state:
    st.session_state.validators = {}
if 'last_config' not in st.session_state:
    st.session_state.last_config = None

def get_cache_dir():
    """Get the cache directory for parquet files."""
    cache_dir = Path(".cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
def get_metric_info(metric_name):
    """Get human-readable title and description for metrics."""
    metric_info = {
        "unique_validator_indexes": {
            "title": "Unique Validators Per Block",
            "subtitle": "Total number of unique validators that submitted attestations included in each block. Higher values indicate better validator participation and network health."
        },
        "first_seen_attestations": {
            "title": "Fresh Attestations",
            "subtitle": "Number of attestations the client included in the block that had never been seen before. Measures how much 'new' attestation data each block contributes to the chain."
        },
        "avg_attestation_inclusion_delay": {
            "title": "Average Inclusion Delay",
            "subtitle": "Average number of slots between when an attestation was supposed to be included (slot + 1) and when it actually appeared in a block. Lower is better for network efficiency."
        },
        "optimal_inclusion_rate": {
            "title": "Optimal Inclusion Rate",
            "subtitle": "Percentage of validators whose attestations were included with just 1-slot delay (optimal timing). Higher rates indicate better network performance and proposer efficiency."
        },
        "min_attestation_inclusion_delay": {
            "title": "Minimum Inclusion Delay",
            "subtitle": "The shortest delay for any attestation in the block. Shows the best-case inclusion performance for that block."
        },
        "p50_attestation_inclusion_delay": {
            "title": "Median Inclusion Delay",
            "subtitle": "The middle value (50th percentile) of all inclusion delays in the block. Provides a robust measure of typical inclusion performance."
        },
        "p95_attestation_inclusion_delay": {
            "title": "95th Percentile Inclusion Delay",
            "subtitle": "The delay below which 95% of attestations fall. Helps identify outliers and worst-case inclusion scenarios."
        },
        "max_attestation_inclusion_delay": {
            "title": "Maximum Inclusion Delay",
            "subtitle": "The longest delay for any attestation in the block. Shows worst-case inclusion performance and potential network issues."
        },
        "aggregation_efficiency": {
            "title": "Aggregation Efficiency",
            "subtitle": "Ratio of unique validators to total attestations. Higher values mean better aggregation - fewer attestation objects needed to represent the same validator participation."
        },
        "total_attestations": {
            "title": "Total Attestations",
            "subtitle": "Total number of attestation objects included in each block. Lower numbers (with same validator participation) indicate better aggregation."
        },
        "avg_validators_per_attestation": {
            "title": "Average Validators Per Attestation",
            "subtitle": "Average number of validators represented by each attestation object. Higher values indicate better signature aggregation efficiency."
        },
        "optimal_inclusion_validators": {
            "title": "Optimal Inclusion Validators",
            "subtitle": "Number of validators whose attestations were included with optimal 1-slot delay. Measures absolute count (not percentage) of well-included validators."
        }
    }
    
    return metric_info.get(metric_name, {
        "title": metric_name.replace('_', ' ').title(),
        "subtitle": "No description available for this metric."
    })

def get_database_connection():
    """Create database connection."""
    try:
        username = os.getenv('XATU_CLICKHOUSE_USERNAME')
        password = os.getenv('XATU_CLICKHOUSE_PASSWORD')
        host = os.getenv('XATU_CLICKHOUSE_HOST')
        
        if not all([username, password, host]):
            st.error("Missing database credentials. Please check your .env file.")
            return None
            
        db_url = f"clickhouse+http://{username}:{password}@{host}:443/default?protocol=https"
        engine = create_engine(db_url)
        return engine.connect()
    except Exception as e:
        st.error(f"Failed to connect to database: {e}")
        return None

