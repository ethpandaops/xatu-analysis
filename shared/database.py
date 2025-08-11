"""
Database connection utilities for ethPandaOps Analysis Dashboard
"""
import streamlit as st
from sqlalchemy import create_engine
from typing import Optional
import dotenv
from .config_loader import config_loader

# Load environment variables
dotenv.load_dotenv()


def get_database_connection(cluster_name: Optional[str] = None):
    """
    Create database connection to specified ClickHouse cluster.
    
    Args:
        cluster_name: Name of the cluster to connect to. If None, uses default cluster.
        
    Returns:
        SQLAlchemy connection object or None if connection fails.
    """
    try:
        conn_string = config_loader.get_connection_string(cluster_name)
        engine = create_engine(conn_string)
        return engine.connect()
    except ValueError as e:
        st.error(f"Configuration error: {e}")
        return None
    except Exception as e:
        cluster = cluster_name or config_loader._config.get('clickhouse', {}).get('default_cluster', 'xatu')
        st.error(f"Failed to connect to ClickHouse cluster '{cluster}': {e}")
        return None


def get_available_clusters():
    """Get list of available ClickHouse clusters."""
    return list(config_loader.get_clickhouse_clusters().keys())
