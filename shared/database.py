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


def get_database_connection(network: Optional[str] = None):
    """
    Create database connection.
    
    Args:
        network: Optional network name. If provided, will use the appropriate cluster for that network.
                If not provided, uses the default cluster (backward compatibility).
    
    Returns:
        SQLAlchemy connection object or None if connection fails
    """
    # If network is specified, use the new multi-cluster manager
    if network:
        return get_clickhouse_client_for_network(network)
    
    # Otherwise, fall back to default behavior for backward compatibility
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
