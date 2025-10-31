"""
Database connection utilities for ethPandaOps Analysis Dashboard
"""
import streamlit as st
from sqlalchemy import create_engine
from typing import Optional
import dotenv
import re
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


def get_routed_connection(sql: str, cluster_name: Optional[str] = None):
    """
    Get database connection routed based on the SQL query.

    Routing logic:
    - If the SQL query contains network-specific database references (e.g., `network`.table),
      route to the 'cbt' cluster
    - Otherwise, use the specified cluster or default cluster

    Args:
        sql: SQL query to analyze for routing
        cluster_name: Name of the cluster to connect to if no routing is needed.
                     If None, uses default cluster.

    Returns:
        SQLAlchemy connection object or None if connection fails.
    """
    # Pattern to detect network-specific database references: `something`.table or `something`.schema.table
    # This matches backtick-quoted identifiers that appear before a dot and table/column name
    network_db_pattern = r'`[^`]+`\.'

    if re.search(network_db_pattern, sql):
        # Query uses network-specific database, route to cbt cluster
        return get_database_connection('cbt')
    else:
        # Query uses default database, use the specified cluster
        return get_database_connection(cluster_name)


def get_available_clusters():
    """Get list of available ClickHouse clusters."""
    return list(config_loader.get_clickhouse_clusters().keys())
