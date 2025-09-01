#!/usr/bin/env python3
"""
Parse Ansible inventory.ini files to create network spec YAML files.

Usage:
    python parse_inventory.py <inventory_url_or_path> <network_name> [--output-dir ./networks]

Example:
    python parse_inventory.py https://raw.githubusercontent.com/ethpandaops/fusaka-devnets/refs/heads/master/ansible/inventories/devnet-4/inventory.ini fusaka-devnet-4
"""

import argparse
import re
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from urllib.request import urlopen
from collections import OrderedDict


def parse_inventory(inventory_content: str) -> Dict[str, Any]:
    """
    Parse an Ansible inventory file and extract node and validator information.
    
    Args:
        inventory_content: Contents of the inventory.ini file
        
    Returns:
        Dictionary containing parsed network specification
    """
    network_spec = {
        'version': '1.0',
        'nodes': {},
        'validators': {
            'total_count': 0
        },
        'groups': {},
        'tags': {},
        'metadata': {}
    }
    
    max_validator_index = 0
    current_group = None
    
    # Parse line by line
    for line in inventory_content.splitlines():
        line = line.strip()
        
        # Skip empty lines and comments
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        
        # Skip standalone localhost
        if line == 'localhost':
            continue
        
        # Check if this is a group header
        if line.startswith('[') and line.endswith(']'):
            current_group = line[1:-1]
            
            # Handle special groups
            if current_group == 'all:vars':
                # This is a variables section
                current_group = 'all:vars'
            elif ':children' in current_group:
                # Skip parent group definitions
                current_group = None
            else:
                # Regular group
                if current_group not in network_spec['groups']:
                    network_spec['groups'][current_group] = []
            continue
        
        # Handle variable assignments in [all:vars]
        if current_group == 'all:vars':
            if '=' in line:
                key, value = line.split('=', 1)
                network_spec['metadata'][key.strip()] = value.strip()
            continue
        
        # Skip if we're not in a group
        if current_group is None or current_group == 'all:vars':
            continue
        
        # Parse host line
        parts = line.split()
        if not parts:
            continue
        
        host_name = parts[0]
        
        # Initialize node entry if not exists
        if host_name not in network_spec['nodes']:
            network_spec['nodes'][host_name] = {
                'groups': [],
                'tags': [],
                'attributes': {},
                'validator_range': None
            }
        
        # Add group to node
        if current_group not in network_spec['nodes'][host_name]['groups']:
            network_spec['nodes'][host_name]['groups'].append(current_group)
        
        # Add node to group
        if host_name not in network_spec['groups'][current_group]:
            network_spec['groups'][current_group].append(host_name)
        
        # Parse host variables from the rest of the line
        host_vars = ' '.join(parts[1:])
        
        # Extract ansible_host (IP address)
        ansible_host_match = re.search(r'ansible_host=(\S+)', host_vars)
        if ansible_host_match:
            network_spec['nodes'][host_name]['attributes']['ansible_host'] = ansible_host_match.group(1)
        
        # Extract IPv6
        ipv6_match = re.search(r'ipv6=(\S+)', host_vars)
        if ipv6_match:
            network_spec['nodes'][host_name]['attributes']['ipv6'] = ipv6_match.group(1)
        
        # Extract cloud provider
        cloud_match = re.search(r'cloud=(\S+)', host_vars)
        if cloud_match:
            network_spec['nodes'][host_name]['attributes']['cloud'] = cloud_match.group(1)
        
        # Extract cloud region
        region_match = re.search(r'cloud_region=(\S+)', host_vars)
        if region_match:
            network_spec['nodes'][host_name]['attributes']['cloud_region'] = region_match.group(1)
        
        # Extract supernode flag
        supernode_match = re.search(r'ethereum_node_cl_supernode_enabled=(\S+)', host_vars)
        if supernode_match:
            is_supernode = supernode_match.group(1).lower() == 'true'
            network_spec['nodes'][host_name]['attributes']['supernode'] = is_supernode
            
            # Add supernode tag
            if is_supernode and 'supernode' not in network_spec['nodes'][host_name]['tags']:
                network_spec['nodes'][host_name]['tags'].append('supernode')
                
                # Track supernode tag globally
                if 'supernode' not in network_spec['tags']:
                    network_spec['tags']['supernode'] = []
                if host_name not in network_spec['tags']['supernode']:
                    network_spec['tags']['supernode'].append(host_name)
        
        # Extract validator range
        start_match = re.search(r'validator_start=(\d+)', host_vars)
        end_match = re.search(r'validator_end=(\d+)', host_vars)
        
        if start_match and end_match:
            start = int(start_match.group(1))
            end = int(end_match.group(1))
            
            network_spec['nodes'][host_name]['validator_range'] = {
                'start': start,
                'end': end,
                'count': end - start
            }
            
            # Track max validator index (end is exclusive, so max index is end-1)
            max_validator_index = max(max_validator_index, end - 1)
    
    # Set total validator count
    network_spec['validators']['total_count'] = max_validator_index + 1 if max_validator_index > 0 else 0
    
    # Extract client types from group names and add as tags
    client_patterns = {
        'grandine': 'cl:grandine',
        'lighthouse': 'cl:lighthouse',
        'lodestar': 'cl:lodestar',
        'nimbus': 'cl:nimbus',
        'prysm': 'cl:prysm',
        'teku': 'cl:teku',
        'besu': 'el:besu',
        'erigon': 'el:erigon',
        'geth': 'el:geth',
        'nethermind': 'el:nethermind',
        'reth': 'el:reth',
        'nimbusel': 'el:nimbusel'
    }
    
    for section in network_spec['groups']:
        section_lower = section.lower()
        
        # Check for client patterns in underscore-separated group names
        for pattern, tag_prefix in client_patterns.items():
            # Match pattern either at start, after underscore, or as complete string
            # This avoids substring issues like "nimbus" matching "nimbusel"
            pattern_regex = rf'(^|_){re.escape(pattern)}(_|$)'
            if re.search(pattern_regex, section_lower):
                # Add tag to all nodes in this group
                for host_name in network_spec['groups'][section]:
                    tag = tag_prefix
                    if tag not in network_spec['nodes'][host_name]['tags']:
                        network_spec['nodes'][host_name]['tags'].append(tag)
                    
                    # Track tag globally
                    if tag not in network_spec['tags']:
                        network_spec['tags'][tag] = []
                    if host_name not in network_spec['tags'][tag]:
                        network_spec['tags'][tag].append(host_name)
        
        # Check for full/super designation
        if 'full' in section_lower:
            for host_name in network_spec['groups'][section]:
                if 'full' not in network_spec['nodes'][host_name]['tags']:
                    network_spec['nodes'][host_name]['tags'].append('full')
                    
                    if 'full' not in network_spec['tags']:
                        network_spec['tags']['full'] = []
                    if host_name not in network_spec['tags']['full']:
                        network_spec['tags']['full'].append(host_name)
        
        if 'super' in section_lower:
            for host_name in network_spec['groups'][section]:
                if 'super' not in network_spec['nodes'][host_name]['tags']:
                    network_spec['nodes'][host_name]['tags'].append('super')
                    
                    if 'super' not in network_spec['tags']:
                        network_spec['tags']['super'] = []
                    if host_name not in network_spec['tags']['super']:
                        network_spec['tags']['super'].append(host_name)
    
    return network_spec


def setup_yaml():
    """Configure YAML for pretty output."""
    # Configure representers for better formatting
    def represent_dict(dumper, data):
        return dumper.represent_mapping('tag:yaml.org,2002:map', data.items())
    
    def represent_list(dumper, data):
        return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=False)
    
    yaml.add_representer(dict, represent_dict)
    yaml.add_representer(list, represent_list)
    yaml.add_representer(OrderedDict, represent_dict)


def fetch_inventory(source: str) -> str:
    """
    Fetch inventory content from URL or local file.
    
    Args:
        source: URL or file path to inventory.ini
        
    Returns:
        Contents of the inventory file
    """
    if source.startswith('http://') or source.startswith('https://'):
        # Fetch from URL
        with urlopen(source) as response:
            return response.read().decode('utf-8')
    else:
        # Read from local file
        with open(source, 'r') as f:
            return f.read()


def main():
    parser = argparse.ArgumentParser(
        description='Parse Ansible inventory to create network spec YAML'
    )
    parser.add_argument(
        'source',
        help='URL or path to inventory.ini file'
    )
    parser.add_argument(
        'network',
        help='Network name (e.g., fusaka-devnet-4)'
    )
    parser.add_argument(
        '--output-dir',
        default='./networks',
        help='Output directory for YAML spec (default: ./networks)'
    )
    parser.add_argument(
        '--pretty',
        action='store_true',
        help='Pretty print the YAML output'
    )
    
    args = parser.parse_args()
    
    try:
        # Setup YAML for pretty output
        if args.pretty:
            setup_yaml()
        
        # Fetch inventory content
        print(f"Fetching inventory from: {args.source}")
        inventory_content = fetch_inventory(args.source)
        
        # Parse inventory
        print("Parsing inventory...")
        network_spec = parse_inventory(inventory_content)
        
        # Add source metadata
        network_spec['metadata']['source'] = args.source
        network_spec['metadata']['network_name'] = args.network
        
        # Ensure output directory exists
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Write YAML spec
        output_file = output_dir / f"{args.network}.yaml"
        
        with open(output_file, 'w') as f:
            if args.pretty:
                yaml.dump(network_spec, f, 
                         default_flow_style=False, 
                         sort_keys=False, 
                         width=120,
                         indent=2,
                         allow_unicode=True)
            else:
                yaml.dump(network_spec, f, default_flow_style=None, sort_keys=False)
        
        print(f"✅ Network spec written to: {output_file}")
        
        # Print summary
        print("\n📊 Summary:")
        print(f"  - Nodes: {len(network_spec['nodes'])}")
        print(f"  - Groups: {len(network_spec['groups'])}")
        print(f"  - Tags: {len(network_spec['tags'])}")
        print(f"  - Total validators: {network_spec['validators']['total_count']}")
        
        if network_spec['tags']:
            print("\n🏷️  Available tags:")
            for tag, nodes in network_spec['tags'].items():
                print(f"    - {tag}: {len(nodes)} nodes")
        
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()