"""
ClickHouse connection manager for multi-cluster support
"""
import os
from typing import Dict, Optional, Any
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, Connection
import streamlit as st
import dotenv

# Load environment variables
dotenv.load_dotenv()


class ClickHouseClusterConfig:
    """Configuration for a ClickHouse cluster"""
    def __init__(self, name: str, username_env: str, password_env: str, host_env: str):
        self.name = name
        self.username_env = username_env
        self.password_env = password_env
        self.host_env = host_env
    
    def get_connection_url(self) -> Optional[str]:
        """Get connection URL for this cluster"""
        username = os.getenv(self.username_env)
        password = os.getenv(self.password_env)
        host = os.getenv(self.host_env)
        
        if not all([username, password, host]):
            return None
            
        return f"clickhouse+http://{username}:{password}@{host}:443/default?protocol=https"


class ClickHouseConnectionManager:
    """Manages connections to multiple ClickHouse clusters"""
    
    def __init__(self):
        # Define cluster configurations
        self.clusters: Dict[str, ClickHouseClusterConfig] = {
            'default': ClickHouseClusterConfig(
                name='default',
                username_env='XATU_CLICKHOUSE_USERNAME',
                password_env='XATU_CLICKHOUSE_PASSWORD',
                host_env='XATU_CLICKHOUSE_HOST'
            ),
            'experimental': ClickHouseClusterConfig(
                name='experimental',
                username_env='XATU_CLICKHOUSE_EXPERIMENTAL_USERNAME',
                password_env='XATU_CLICKHOUSE_EXPERIMENTAL_PASSWORD',
                host_env='XATU_CLICKHOUSE_EXPERIMENTAL_HOST'
            )
        }
        
        # Define network to cluster routing
        self.network_routing: Dict[str, str] = {
            'mainnet': 'default',
            'sepolia': 'default',
            'holesky': 'default',
            'hoodi': 'default',
            # All other networks will route to 'experimental'
        }
        
        # Cache for database engines
        self._engines: Dict[str, Engine] = {}
    
    def get_cluster_for_network(self, network: str) -> str:
        """Get the cluster name for a given network"""
        return self.network_routing.get(network, 'experimental')
    
    def get_engine_for_cluster(self, cluster_name: str) -> Optional[Engine]:
        """Get or create SQLAlchemy engine for a cluster"""
        if cluster_name in self._engines:
            return self._engines[cluster_name]
        
        if cluster_name not in self.clusters:
            st.error(f"Unknown cluster: {cluster_name}")
            return None
        
        cluster_config = self.clusters[cluster_name]
        connection_url = cluster_config.get_connection_url()
        
        if not connection_url:
            st.error(f"Missing credentials for {cluster_name} cluster. Please check your .env file.")
            return None
        
        try:
            engine = create_engine(connection_url)
            self._engines[cluster_name] = engine
            return engine
        except Exception as e:
            st.error(f"Failed to create engine for {cluster_name} cluster: {e}")
            return None
    
    def get_connection_for_network(self, network: str) -> Optional[Connection]:
        """Get database connection for a specific network"""
        cluster_name = self.get_cluster_for_network(network)
        engine = self.get_engine_for_cluster(cluster_name)
        
        if not engine:
            return None
        
        try:
            return engine.connect()
        except Exception as e:
            st.error(f"Failed to connect to {cluster_name} cluster for network {network}: {e}")
            return None
    
    def add_cluster(self, name: str, config: ClickHouseClusterConfig):
        """Add a new cluster configuration"""
        self.clusters[name] = config
    
    def update_network_routing(self, network_routing: Dict[str, str]):
        """Update network routing configuration"""
        self.network_routing.update(network_routing)


# Singleton instance
@st.cache_resource
def get_clickhouse_manager() -> ClickHouseConnectionManager:
    """Get singleton ClickHouseConnectionManager instance"""
    return ClickHouseConnectionManager()


def get_clickhouse_client_for_network(network: str) -> Optional[Connection]:
    """
    Get ClickHouse connection for a specific network.
    
    This is the main entry point for getting network-specific database connections.
    
    Args:
        network: The network name (e.g., 'mainnet', 'sepolia', 'experimental_network')
    
    Returns:
        SQLAlchemy Connection object or None if connection fails
    """
    manager = get_clickhouse_manager()
    return manager.get_connection_for_network(network)