"""
Configuration loader for Xatu Analysis Dashboard.
Handles loading and merging of config.yaml and config.local.yaml files.
"""
import os
import yaml
from typing import Dict, Any, Optional, List
from pathlib import Path
import streamlit as st
from datetime import datetime, timedelta
import logging
from .network_spec import get_network_spec, has_network_spec, list_network_specs

logger = logging.getLogger(__name__)

class ConfigLoader:
    """Handles loading and merging of configuration files."""
    
    _instance = None
    _config = None
    _discovered_networks = None
    _network_cache_time = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigLoader, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._config is None:
            self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load and merge configuration from YAML files."""
        # Get the project root directory
        project_root = Path(__file__).parent.parent
        
        # Load default config
        default_config_path = project_root / "config.yaml"
        if not default_config_path.exists():
            raise FileNotFoundError(f"Default config not found: {default_config_path}")
        
        with open(default_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Load local config if it exists
        local_config_path = project_root / "config.local.yaml"
        if local_config_path.exists():
            try:
                with open(local_config_path, 'r') as f:
                    local_config = yaml.safe_load(f)
                    if local_config:
                        config = self._deep_merge(config, local_config)
                        logger.info("Loaded local configuration overrides")
            except Exception as e:
                logger.warning(f"Failed to load local config: {e}")
        
        return config
    
    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries, with override taking precedence."""
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def get_clickhouse_clusters(self) -> Dict[str, Dict[str, Any]]:
        """Get all configured ClickHouse clusters."""
        return self._config.get('clickhouse', {}).get('clusters', {})
    
    def get_clickhouse_cluster(self, cluster_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get configuration for a specific ClickHouse cluster.
        
        Args:
            cluster_name: Name of the cluster. If None, uses default cluster.
            
        Returns:
            Dictionary with cluster configuration including credentials from env vars.
        """
        clusters = self.get_clickhouse_clusters()
        
        if cluster_name is None:
            cluster_name = self._config.get('clickhouse', {}).get('default_cluster', 'xatu')
        
        if cluster_name not in clusters:
            raise ValueError(f"Cluster '{cluster_name}' not found in configuration")
        
        cluster_config = clusters[cluster_name].copy()
        
        # Get credentials from environment variables
        env_prefix = cluster_name.upper()
        username = os.getenv(f'{env_prefix}_CLICKHOUSE_USERNAME')
        password = os.getenv(f'{env_prefix}_CLICKHOUSE_PASSWORD')
        
        if not username or not password:
            logger.warning(f"Missing credentials for cluster '{cluster_name}'. "
                         f"Please set {env_prefix}_CLICKHOUSE_USERNAME and "
                         f"{env_prefix}_CLICKHOUSE_PASSWORD environment variables.")
        
        cluster_config['username'] = username
        cluster_config['password'] = password
        cluster_config['name'] = cluster_name
        
        return cluster_config
    
    def get_connection_string(self, cluster_name: Optional[str] = None) -> str:
        """
        Get SQLAlchemy connection string for a ClickHouse cluster.
        
        Args:
            cluster_name: Name of the cluster. If None, uses default cluster.
            
        Returns:
            SQLAlchemy connection string.
        """
        cluster = self.get_clickhouse_cluster(cluster_name)
        
        username = cluster.get('username')
        password = cluster.get('password')
        host = cluster.get('host')
        port = cluster.get('port', 443)
        database = cluster.get('database', 'default')
        protocol = cluster.get('protocol', 'https')
        
        if not all([username, password, host]):
            raise ValueError(f"Missing required connection parameters for cluster '{cluster_name}'")
        
        if protocol == 'https':
            return f"clickhouse+http://{username}:{password}@{host}:{port}/{database}?protocol=https"
        else:
            return f"clickhouse+http://{username}:{password}@{host}:{port}/{database}"
    
    def get_networks(self) -> Dict[str, Dict[str, Any]]:
        """Get all configured networks (static + discovered)."""
        static_networks = self._config.get('networks', {})
        
        # Filter out disabled networks
        enabled_networks = {
            name: config 
            for name, config in static_networks.items() 
            if config.get('enabled', True)
        }
        
        # Add discovered networks if enabled
        if self._config.get('clickhouse', {}).get('network_discovery', {}).get('enabled', True):
            discovered = self.get_discovered_networks()
            for network_name in discovered:
                if network_name not in enabled_networks:
                    # Add discovered network with minimal config
                    enabled_networks[network_name] = {
                        'name': network_name.title(),
                        'description': f'Discovered network: {network_name}',
                        'enabled': True,
                        'discovered': True
                    }
        
        return enabled_networks
    
    def get_discovered_networks(self) -> List[str]:
        """
        Get list of networks discovered from ClickHouse.
        Results are cached based on cache_duration setting.
        """
        cache_duration = self._config.get('clickhouse', {}).get('network_discovery', {}).get('cache_duration', 60)
        
        # Check if cache is still valid
        if self._discovered_networks is not None and self._network_cache_time is not None:
            if datetime.now() - self._network_cache_time < timedelta(minutes=cache_duration):
                return self._discovered_networks
        
        # Discover networks from ClickHouse
        try:
            discovered = self._discover_networks_from_clickhouse()
            self._discovered_networks = discovered
            self._network_cache_time = datetime.now()
            return discovered
        except Exception as e:
            logger.error(f"Failed to discover networks: {e}")
            # Return empty list on error, will fall back to static config
            return []
    
    def _discover_networks_from_clickhouse(self) -> List[str]:
        """Query ClickHouse to discover available networks."""
        from sqlalchemy import create_engine, text
        
        discovery_config = self._config.get('clickhouse', {}).get('network_discovery', {})
        tables = discovery_config.get('tables', [])
        lookback_days = discovery_config.get('lookback_days', 7)
        
        if not tables:
            return []
        
        discovered_networks = set()
        
        try:
            # Get connection to default cluster
            conn_string = self.get_connection_string()
            engine = create_engine(conn_string)
            
            with engine.connect() as conn:
                for table in tables:
                    try:
                        # Query for distinct network names in the last N days
                        query = text(f"""
                            SELECT DISTINCT meta_network_name
                            FROM {table} FINAL
                            WHERE slot_start_date_time >= now() - INTERVAL {lookback_days} DAY
                            AND meta_network_name != ''
                            AND meta_network_name IS NOT NULL
                        """)
                        
                        result = conn.execute(query)
                        for row in result:
                            discovered_networks.add(row[0])
                    except Exception as e:
                        logger.warning(f"Failed to query table {table}: {e}")
                        continue
            
            logger.info(f"Discovered networks: {discovered_networks}")
            return sorted(list(discovered_networks))
            
        except Exception as e:
            logger.error(f"Failed to connect to ClickHouse for network discovery: {e}")
            return []
    
    def get_network_config(self, network_name: str) -> Dict[str, Any]:
        """Get configuration for a specific network."""
        networks = self.get_networks()
        if network_name not in networks:
            # Return minimal config for unknown networks
            return {
                'name': network_name.title(),
                'description': f'Unknown network: {network_name}',
                'enabled': True
            }
        return networks[network_name]
    
    def get_network_spec(self, network_name: str):
        """
        Get network specification for a network if available.
        
        Args:
            network_name: Name of the network
            
        Returns:
            NetworkSpec instance or None if not available
        """
        return get_network_spec(network_name)
    
    def has_network_spec(self, network_name: str) -> bool:
        """
        Check if a network has a detailed specification available.
        
        Args:
            network_name: Name of the network
            
        Returns:
            True if network spec is available
        """
        return has_network_spec(network_name)
    
    def list_network_specs(self) -> List[str]:
        """
        List all available network specifications.
        
        Returns:
            List of network names with specs available
        """
        return list_network_specs()
    
    def get_network_genesis_timestamp(self, network: str) -> int:
        """Get the genesis timestamp for a specific network."""
        config = self.get_network_config(network)
        return config.get('genesis_timestamp', 1606824023)  # Default to mainnet genesis
    
    def get_supported_networks(self) -> List[str]:
        """Get list of all supported network names."""
        return sorted(list(self.get_networks().keys()))
    
    def get_app_config(self) -> Dict[str, Any]:
        """Get application configuration."""
        return self._config.get('app', {})
    
    def get_integration_config(self, integration_name: str) -> Dict[str, Any]:
        """Get configuration for a specific integration."""
        integrations = self._config.get('integrations', {})
        return integrations.get(integration_name, {})
    
    def reload_config(self):
        """Force reload of configuration from files."""
        self._config = self._load_config()
        self._discovered_networks = None
        self._network_cache_time = None
        logger.info("Configuration reloaded")

# Singleton instance
config_loader = ConfigLoader()

# Convenience functions for backward compatibility
def get_clickhouse_cluster(cluster_name: Optional[str] = None) -> Dict[str, Any]:
    """Get ClickHouse cluster configuration."""
    return config_loader.get_clickhouse_cluster(cluster_name)

def get_connection_string(cluster_name: Optional[str] = None) -> str:
    """Get SQLAlchemy connection string for a ClickHouse cluster."""
    return config_loader.get_connection_string(cluster_name)

def get_supported_networks() -> List[str]:
    """Get list of supported networks."""
    return config_loader.get_supported_networks()

def get_network_config() -> Dict[str, Dict[str, Any]]:
    """Get all network configurations."""
    return config_loader.get_networks()

def get_network_genesis_timestamp(network: str) -> int:
    """Get genesis timestamp for a network."""
    return config_loader.get_network_genesis_timestamp(network)

def get_network_spec(network_name: str):
    """Get network specification for a network."""
    return config_loader.get_network_spec(network_name)

def has_network_spec(network_name: str) -> bool:
    """Check if a network has a specification available."""
    return config_loader.has_network_spec(network_name)

def list_network_specs() -> List[str]:
    """List all available network specifications."""
    return config_loader.list_network_specs()