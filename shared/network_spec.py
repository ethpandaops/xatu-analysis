"""
Network specification loader for ethPandaOps Analysis Dashboard.
Provides utilities to load and query network specifications including validator-to-node mappings.
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from functools import lru_cache

logger = logging.getLogger(__name__)


class NetworkSpec:
    """
    Handles loading and querying of network specification files.
    """
    
    def __init__(self, spec_path: Optional[str] = None, spec_data: Optional[Dict[str, Any]] = None):
        """
        Initialize NetworkSpec from either a file path or data dictionary.
        
        Args:
            spec_path: Path to the network spec YAML file
            spec_data: Pre-loaded spec data dictionary
        """
        if spec_path:
            self.spec_path = Path(spec_path)
            self._load_from_file()
        elif spec_data:
            self.spec_data = spec_data
            self.spec_path = None
        else:
            raise ValueError("Either spec_path or spec_data must be provided")
        
        # Cache frequently accessed data
        self._validator_lookup = None
        self._build_caches()
    
    def _load_from_file(self):
        """Load network spec from YAML file."""
        if not self.spec_path.exists():
            raise FileNotFoundError(f"Network spec file not found: {self.spec_path}")
        
        with open(self.spec_path, 'r') as f:
            self.spec_data = yaml.safe_load(f)
        
        logger.info(f"Loaded network spec from {self.spec_path}")
    
    def _build_caches(self):
        """Build internal caches for efficient lookups."""
        # Build validator lookup cache from node validator ranges
        self._validator_lookup = {}
        
        # Iterate through all nodes and build the lookup from their ranges
        for node_name, node_data in self.spec_data.get('nodes', {}).items():
            if node_data.get('validator_range'):
                start = node_data['validator_range']['start']
                end = node_data['validator_range']['end']
                # Assign all validators in range to this node
                for idx in range(start, end):
                    self._validator_lookup[idx] = node_name
    
    def get_validator_node(self, validator_index: int) -> Optional[str]:
        """
        Get the node name assigned to a specific validator index.
        
        Args:
            validator_index: The validator index
            
        Returns:
            Node name or None if validator is not assigned
        """
        if self._validator_lookup is None:
            return None
        return self._validator_lookup.get(validator_index)
    
    def get_validators(self, node_name: str) -> List[int]:
        """
        Get all validator indices assigned to a specific node.
        
        Args:
            node_name: Name of the node
            
        Returns:
            List of validator indices
        """
        validators = []
        
        if node_name in self.spec_data.get('nodes', {}):
            node = self.spec_data['nodes'][node_name]
            if node.get('validator_range'):
                start = node['validator_range']['start']
                end = node['validator_range']['end']
                validators = list(range(start, end))
        
        return validators
    
    def get_validator_range(self, node_name: str) -> Optional[Tuple[int, int]]:
        """
        Get the validator range for a node as a tuple.
        
        Args:
            node_name: Name of the node
            
        Returns:
            Tuple of (start, end) or None if no validators assigned
        """
        if node_name in self.spec_data.get('nodes', {}):
            node = self.spec_data['nodes'][node_name]
            if node.get('validator_range'):
                return (node['validator_range']['start'], node['validator_range']['end'])
        return None
    
    def get_nodes_by_tag(self, tag: str) -> List[str]:
        """
        Get all nodes that have a specific tag.
        
        Args:
            tag: Tag to filter by (e.g., 'supernode', 'cl:lighthouse', 'el:geth')
            
        Returns:
            List of node names
        """
        return self.spec_data.get('tags', {}).get(tag, [])
    
    def get_nodes_by_group(self, group: str) -> List[str]:
        """
        Get all nodes in a specific group.
        
        Args:
            group: Group name
            
        Returns:
            List of node names
        """
        return self.spec_data.get('groups', {}).get(group, [])
    
    def get_node_info(self, node_name: str) -> Optional[Dict[str, Any]]:
        """
        Get full information about a specific node.
        
        Args:
            node_name: Name of the node
            
        Returns:
            Dictionary with node information or None if not found
        """
        return self.spec_data.get('nodes', {}).get(node_name)
    
    def get_node_attributes(self, node_name: str) -> Dict[str, Any]:
        """
        Get attributes of a specific node.
        
        Args:
            node_name: Name of the node
            
        Returns:
            Dictionary of attributes
        """
        node = self.spec_data.get('nodes', {}).get(node_name, {})
        return node.get('attributes', {})
    
    def get_node_tags(self, node_name: str) -> List[str]:
        """
        Get tags assigned to a specific node.
        
        Args:
            node_name: Name of the node
            
        Returns:
            List of tags
        """
        node = self.spec_data.get('nodes', {}).get(node_name, {})
        return node.get('tags', [])
    
    def is_supernode(self, node_name: str) -> bool:
        """
        Check if a node is a supernode.
        
        Args:
            node_name: Name of the node
            
        Returns:
            True if node is a supernode
        """
        node = self.spec_data.get('nodes', {}).get(node_name, {})
        return node.get('attributes', {}).get('supernode', False)
    
    def get_all_nodes(self) -> List[str]:
        """Get list of all node names."""
        return list(self.spec_data.get('nodes', {}).keys())
    
    def get_all_tags(self) -> List[str]:
        """Get list of all available tags."""
        return list(self.spec_data.get('tags', {}).keys())
    
    def get_all_groups(self) -> List[str]:
        """Get list of all group names."""
        return list(self.spec_data.get('groups', {}).keys())
    
    def get_total_validator_count(self) -> int:
        """Get total number of validators in the network."""
        return self.spec_data.get('validators', {}).get('total_count', 0)
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get network metadata."""
        return self.spec_data.get('metadata', {})
    
    def get_nodes_by_client(self, client_type: str, client_name: str) -> List[str]:
        """
        Get nodes running a specific client.
        
        Args:
            client_type: Either 'cl' (consensus layer) or 'el' (execution layer)
            client_name: Client name (e.g., 'lighthouse', 'geth')
            
        Returns:
            List of node names
        """
        tag = f"{client_type}:{client_name}"
        return self.get_nodes_by_tag(tag)
    
    def get_node_clients(self, node_name: str) -> Dict[str, str]:
        """
        Get the consensus and execution layer clients for a node.
        
        Args:
            node_name: Name of the node
            
        Returns:
            Dictionary with 'cl' and 'el' keys
        """
        tags = self.get_node_tags(node_name)
        clients = {'cl': None, 'el': None}
        
        for tag in tags:
            if tag.startswith('cl:'):
                clients['cl'] = tag.split(':')[1]
            elif tag.startswith('el:'):
                clients['el'] = tag.split(':')[1]
        
        return clients
    
    def get_validators_by_tag(self, tag: str) -> List[int]:
        """
        Get all validator indices for nodes with a specific tag.
        
        Args:
            tag: Tag to filter by
            
        Returns:
            List of validator indices
        """
        validators = []
        nodes = self.get_nodes_by_tag(tag)
        for node in nodes:
            validators.extend(self.get_validators(node))
        return sorted(validators)
    
    def get_validators_by_client(self, client_type: str, client_name: str) -> List[int]:
        """
        Get all validator indices running on a specific client.
        
        Args:
            client_type: Either 'cl' or 'el'
            client_name: Client name
            
        Returns:
            List of validator indices
        """
        tag = f"{client_type}:{client_name}"
        return self.get_validators_by_tag(tag)
    
    def get_cloud_distribution(self) -> Dict[str, Dict[str, int]]:
        """
        Get distribution of nodes across cloud providers and regions.
        
        Returns:
            Dictionary with cloud providers and their region counts
        """
        distribution = {}
        
        for node_name, node_data in self.spec_data.get('nodes', {}).items():
            attrs = node_data.get('attributes', {})
            cloud = attrs.get('cloud', 'unknown')
            region = attrs.get('cloud_region', 'unknown')
            
            if cloud not in distribution:
                distribution[cloud] = {}
            
            if region not in distribution[cloud]:
                distribution[cloud][region] = 0
            
            distribution[cloud][region] += 1
        
        return distribution
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the network specification.
        
        Returns:
            Dictionary with summary statistics
        """
        summary = {
            'total_nodes': len(self.get_all_nodes()),
            'total_validators': self.get_total_validator_count(),
            'total_groups': len(self.get_all_groups()),
            'total_tags': len(self.get_all_tags()),
            'supernodes': len(self.get_nodes_by_tag('supernode')),
            'cloud_distribution': self.get_cloud_distribution(),
            'client_distribution': {}
        }
        
        # Count client distribution
        for tag in self.get_all_tags():
            if tag.startswith('cl:') or tag.startswith('el:'):
                summary['client_distribution'][tag] = len(self.get_nodes_by_tag(tag))
        
        return summary


class NetworkSpecManager:
    """
    Manages multiple network specifications.
    """
    
    def __init__(self, spec_dir: Optional[str] = None):
        """
        Initialize NetworkSpecManager.
        
        Args:
            spec_dir: Directory containing network spec YAML files
        """
        self.spec_dir = Path(spec_dir) if spec_dir else Path('./networks')
        self._specs: Dict[str, NetworkSpec] = {}
        self._load_available_specs()
    
    def _load_available_specs(self):
        """Discover available network spec files."""
        if not self.spec_dir.exists():
            logger.warning(f"Network spec directory does not exist: {self.spec_dir}")
            return
        
        for yaml_file in self.spec_dir.glob("*.yaml"):
            network_name = yaml_file.stem
            logger.debug(f"Found network spec: {network_name}")
    
    @lru_cache(maxsize=10)
    def get_spec(self, network_name: str) -> Optional[NetworkSpec]:
        """
        Get network specification for a specific network.
        
        Args:
            network_name: Name of the network
            
        Returns:
            NetworkSpec instance or None if not found
        """
        if network_name in self._specs:
            return self._specs[network_name]
        
        spec_path = self.spec_dir / f"{network_name}.yaml"
        if spec_path.exists():
            try:
                spec = NetworkSpec(spec_path=str(spec_path))
                self._specs[network_name] = spec
                return spec
            except Exception as e:
                logger.error(f"Failed to load network spec for {network_name}: {e}")
                return None
        
        return None
    
    def list_available_networks(self) -> List[str]:
        """
        List all available network specifications.
        
        Returns:
            List of network names
        """
        if not self.spec_dir.exists():
            return []
        
        networks = []
        for yaml_file in self.spec_dir.glob("*.yaml"):
            networks.append(yaml_file.stem)
        
        return sorted(networks)
    
    def has_spec(self, network_name: str) -> bool:
        """
        Check if a network specification exists.
        
        Args:
            network_name: Name of the network
            
        Returns:
            True if spec exists
        """
        spec_path = self.spec_dir / f"{network_name}.yaml"
        return spec_path.exists()


# Singleton instance for convenience
_manager_instance = None

def get_network_spec_manager() -> NetworkSpecManager:
    """Get the singleton NetworkSpecManager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = NetworkSpecManager()
    return _manager_instance


# Convenience functions
def get_network_spec(network_name: str) -> Optional[NetworkSpec]:
    """
    Get network specification for a specific network.
    
    Args:
        network_name: Name of the network
        
    Returns:
        NetworkSpec instance or None if not found
    """
    manager = get_network_spec_manager()
    return manager.get_spec(network_name)


def has_network_spec(network_name: str) -> bool:
    """
    Check if a network specification exists.
    
    Args:
        network_name: Name of the network
        
    Returns:
        True if spec exists
    """
    manager = get_network_spec_manager()
    return manager.has_spec(network_name)


def list_network_specs() -> List[str]:
    """
    List all available network specifications.
    
    Returns:
        List of network names
    """
    manager = get_network_spec_manager()
    return manager.list_available_networks()