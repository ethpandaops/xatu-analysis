"""
Database connection utilities for ethPandaOps Analysis Dashboard
"""
import os
import streamlit as st
from sqlalchemy import create_engine
from typing import Optional
import dotenv
from .clickhouse_manager import get_clickhouse_client_for_network

# Load environment variables
dotenv.load_dotenv()


def get_database_connection(network: str):
    """
    Create database connection for the specified network.
    
    Args:
        network: Network name (e.g., 'mainnet', 'sepolia', 'experimental_network')
    
    Returns:
        SQLAlchemy connection object or None if connection fails
    """
    return get_clickhouse_client_for_network(network)
