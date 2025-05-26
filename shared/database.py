"""
Database connection utilities for EthPandaOps Analysis Dashboard
"""
import os
import streamlit as st
from sqlalchemy import create_engine
import dotenv

# Load environment variables
dotenv.load_dotenv()


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
