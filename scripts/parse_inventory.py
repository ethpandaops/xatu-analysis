#!/usr/bin/env python3
"""
Parse Ansible inventory.ini files to create network spec YAML files.

Usage:
    python parse_inventory.py <inventory_urls_or_paths> <network_name> [--output-dir ./networks]

Example (single inventory):
    python parse_inventory.py https://raw.githubusercontent.com/ethpandaops/fusaka-devnets/refs/heads/master/ansible/inventories/devnet-4/inventory.ini fusaka-devnet-4

Example (multiple inventories):
    python parse_inventory.py "https://url1.ini,https://url2.ini,/path/to/local.ini" fusaka-devnet-5
"""

import argparse
import copy
import re
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
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


def check_validator_overlaps(specs: List[Dict[str, Any]]) -> None:
    """
    Check for overlapping validator ranges across multiple inventory specs.

    Args:
        specs: List of parsed network specifications

    Raises:
        ValueError: If overlapping validator ranges are detected
    """
    # Collect all validator ranges with their source info
    validator_ranges = []

    for idx, spec in enumerate(specs):
        source = spec['metadata'].get('source', f'inventory_{idx}')
        for node_name, node_data in spec['nodes'].items():
            if node_data.get('validator_range'):
                vrange = node_data['validator_range']
                validator_ranges.append({
                    'start': vrange['start'],
                    'end': vrange['end'],
                    'node': node_name,
                    'source': source
                })

    # Check for overlaps
    for i, range1 in enumerate(validator_ranges):
        for j, range2 in enumerate(validator_ranges[i+1:], i+1):
            # Check if ranges overlap
            # Ranges overlap if one starts before the other ends
            if not (range1['end'] <= range2['start'] or range2['end'] <= range1['start']):
                overlap_start = max(range1['start'], range2['start'])
                overlap_end = min(range1['end'], range2['end'])
                raise ValueError(
                    f"Validator range overlap detected!\n"
                    f"  Node '{range1['node']}' from {range1['source']}: "
                    f"[{range1['start']}, {range1['end']})\n"
                    f"  Node '{range2['node']}' from {range2['source']}: "
                    f"[{range2['start']}, {range2['end']})\n"
                    f"  Overlapping range: [{overlap_start}, {overlap_end})"
                )


def analyze_validator_ranges(specs: List[Dict[str, Any]], source_list: List[str]) -> List[Dict[str, Any]]:
    """
    Analyze validator ranges across inventories and calculate offsets.

    Args:
        specs: List of parsed network specifications
        source_list: List of source paths/URLs

    Returns:
        List of inventory info with calculated offsets
    """
    inventory_info = []
    current_offset = 0

    for idx, spec in enumerate(specs):
        source = source_list[idx] if idx < len(source_list) else f'inventory_{idx}'

        # Find min and max validator indices in this inventory
        min_validator = float('inf')
        max_validator = -1
        validator_count = 0
        nodes_with_validators = []

        for node_name, node_data in spec['nodes'].items():
            if node_data.get('validator_range'):
                vrange = node_data['validator_range']
                min_validator = min(min_validator, vrange['start'])
                max_validator = max(max_validator, vrange['end'] - 1)  # end is exclusive
                validator_count += vrange['count']
                nodes_with_validators.append(node_name)

        if max_validator >= 0:
            info = {
                'index': idx,
                'source': source,
                'original_range': {
                    'start': min_validator,
                    'end': max_validator + 1  # Make it exclusive like the original
                },
                'offset': current_offset,
                'new_range': {
                    'start': min_validator + current_offset,
                    'end': (max_validator + 1) + current_offset
                },
                'validator_count': validator_count,
                'nodes_with_validators': len(nodes_with_validators)
            }
            inventory_info.append(info)

            # Update offset for next inventory
            current_offset = info['new_range']['end']
        else:
            # No validators in this inventory
            info = {
                'index': idx,
                'source': source,
                'original_range': None,
                'offset': 0,
                'new_range': None,
                'validator_count': 0,
                'nodes_with_validators': 0
            }
            inventory_info.append(info)

    return inventory_info


def confirm_processing_order(inventory_info: List[Dict[str, Any]]) -> bool:
    """
    Display processing order and offsets for confirmation.

    Args:
        inventory_info: List of inventory information with offsets

    Returns:
        True if user confirms, False otherwise
    """
    print("\n" + "="*80)
    print("📋 INVENTORY PROCESSING CONFIRMATION")
    print("="*80)

    print("\nInventories will be processed in the following order:\n")

    for info in inventory_info:
        print(f"  [{info['index'] + 1}] {info['source']}")
        if info['original_range']:
            print(f"      Original validator range: [{info['original_range']['start']:,}, {info['original_range']['end']:,})")
            print(f"      Validators: {info['validator_count']:,} across {info['nodes_with_validators']} nodes")
            if info['offset'] > 0:
                print(f"      ✨ Offset applied: +{info['offset']:,}")
                print(f"      New validator range: [{info['new_range']['start']:,}, {info['new_range']['end']:,})")
        else:
            print(f"      No validators in this inventory")
        print()

    # Summary
    total_validators = sum(info['validator_count'] for info in inventory_info)
    total_nodes = sum(info['nodes_with_validators'] for info in inventory_info)
    max_index = max((info['new_range']['end'] - 1 for info in inventory_info if info['new_range']), default=0)

    print("📊 Summary:")
    print(f"  - Total inventories: {len(inventory_info)}")
    print(f"  - Total validators: {total_validators:,}")
    print(f"  - Total nodes with validators: {total_nodes}")
    print(f"  - Final validator index range: [0, {max_index + 1:,})")

    print("\n" + "="*80)

    # Ask for confirmation
    while True:
        response = input("\n⚠️  Do you want to proceed with this configuration? (yes/no): ").strip().lower()
        if response in ['yes', 'y']:
            return True
        elif response in ['no', 'n']:
            return False
        else:
            print("Please enter 'yes' or 'no'")


def merge_network_specs(specs: List[Dict[str, Any]], inventory_info: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge multiple network specifications into one with automatic offset application.

    Args:
        specs: List of parsed network specifications
        inventory_info: List of inventory information with calculated offsets

    Returns:
        Merged network specification
    """
    if not specs:
        raise ValueError("No specifications to merge")

    if len(specs) == 1:
        return specs[0]

    # Start with empty merged spec
    merged = {
        'version': '1.0',
        'nodes': {},
        'validators': {
            'total_count': 0
        },
        'groups': {},
        'tags': {},
        'metadata': {
            'sources': [],  # Track all source files
            'validator_offsets': {}  # Track offsets applied
        }
    }

    max_validator_index = 0

    # Merge each spec with offset application
    for idx, spec in enumerate(specs):
        info = inventory_info[idx]
        offset = info['offset']
        # Track sources and offsets
        if 'source' in spec['metadata']:
            merged['metadata']['sources'].append(spec['metadata']['source'])
            if offset > 0:
                merged['metadata']['validator_offsets'][spec['metadata']['source']] = offset

        # Merge metadata (excluding source)
        for key, value in spec['metadata'].items():
            if key != 'source' and key not in merged['metadata']:
                merged['metadata'][key] = value

        # Merge nodes
        for node_name, node_data in spec['nodes'].items():
            # Deep copy node data to avoid modifying original
            node_copy = copy.deepcopy(node_data)

            # Apply offset to validator range if present
            if node_copy.get('validator_range') and offset > 0:
                node_copy['validator_range']['start'] += offset
                node_copy['validator_range']['end'] += offset

            if node_name in merged['nodes']:
                # Node exists in multiple inventories - merge the data
                # Merge groups (union)
                existing_groups = set(merged['nodes'][node_name]['groups'])
                new_groups = set(node_copy['groups'])
                merged['nodes'][node_name]['groups'] = list(existing_groups | new_groups)

                # Merge tags (union)
                existing_tags = set(merged['nodes'][node_name]['tags'])
                new_tags = set(node_copy['tags'])
                merged['nodes'][node_name]['tags'] = list(existing_tags | new_tags)

                # Merge attributes (new overwrites old)
                merged['nodes'][node_name]['attributes'].update(node_copy['attributes'])

                # Handle validator range
                if node_copy.get('validator_range'):
                    if merged['nodes'][node_name].get('validator_range'):
                        # Node has validators in multiple inventories - this is unusual but allowed
                        # Combine the ranges
                        print(f"⚠️  Warning: Node {node_name} has validator ranges in multiple inventories")
                        existing_range = merged['nodes'][node_name]['validator_range']
                        new_range = node_copy['validator_range']
                        print(f"    Existing: [{existing_range['start']}, {existing_range['end']})")
                        print(f"    New: [{new_range['start']}, {new_range['end']})")
                    merged['nodes'][node_name]['validator_range'] = node_copy['validator_range']
            else:
                # New node, add it
                merged['nodes'][node_name] = node_copy

            # Track max validator index
            if node_copy.get('validator_range'):
                max_validator_index = max(max_validator_index, node_copy['validator_range']['end'] - 1)

        # Merge groups
        for group_name, group_nodes in spec['groups'].items():
            if group_name not in merged['groups']:
                merged['groups'][group_name] = []
            # Add unique nodes to group
            existing = set(merged['groups'][group_name])
            for node in group_nodes:
                if node not in existing:
                    merged['groups'][group_name].append(node)

        # Merge tags
        for tag_name, tag_nodes in spec['tags'].items():
            if tag_name not in merged['tags']:
                merged['tags'][tag_name] = []
            # Add unique nodes to tag
            existing = set(merged['tags'][tag_name])
            for node in tag_nodes:
                if node not in existing:
                    merged['tags'][tag_name].append(node)

    # Set total validator count
    merged['validators']['total_count'] = max_validator_index + 1 if max_validator_index > 0 else 0

    return merged


def main():
    parser = argparse.ArgumentParser(
        description='Parse Ansible inventory to create network spec YAML',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Single inventory:
    %(prog)s https://example.com/inventory.ini network-name

  Multiple inventories (comma-separated):
    %(prog)s "https://url1.ini,https://url2.ini,/local/path.ini" network-name
        """
    )
    parser.add_argument(
        'sources',
        help='URL(s) or path(s) to inventory.ini file(s). Multiple files should be comma-separated.'
    )
    parser.add_argument(
        'network',
        help='Network name (e.g., fusaka-devnet-5)'
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

        # Parse sources (handle comma-separated list)
        source_list = [s.strip() for s in args.sources.split(',')]

        # Process each inventory
        specs = []
        for source in source_list:
            # Fetch inventory content
            print(f"Fetching inventory from: {source}")
            inventory_content = fetch_inventory(source)

            # Parse inventory
            print(f"  Parsing inventory...")
            spec = parse_inventory(inventory_content)

            # Add source metadata
            spec['metadata']['source'] = source
            spec['metadata']['network_name'] = args.network

            specs.append(spec)
            print(f"  ✓ Parsed {len(spec['nodes'])} nodes")

        # Merge specifications if multiple
        if len(specs) > 1:
            print(f"\nAnalyzing {len(specs)} inventory files...")

            # Analyze validator ranges and calculate offsets
            inventory_info = analyze_validator_ranges(specs, source_list)

            # Show confirmation dialog
            if not confirm_processing_order(inventory_info):
                print("\n❌ Operation cancelled by user")
                sys.exit(0)

            print(f"\n✅ Proceeding with merge...")
            network_spec = merge_network_specs(specs, inventory_info)
            print("  ✓ Merge complete with automatic offset application")
        else:
            network_spec = specs[0]

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

        print(f"\n✅ Network spec written to: {output_file}")

        # Print summary
        print("\n📊 Summary:")
        print(f"  - Nodes: {len(network_spec['nodes'])}")
        print(f"  - Groups: {len(network_spec['groups'])}")
        print(f"  - Tags: {len(network_spec['tags'])}")
        print(f"  - Total validators: {network_spec['validators']['total_count']}")

        if len(source_list) > 1:
            print(f"  - Merged from {len(source_list)} inventory files")

            # Show offset information if any were applied
            if 'validator_offsets' in network_spec['metadata'] and network_spec['metadata']['validator_offsets']:
                print("\n🔧 Validator offsets applied:")
                for source, offset in network_spec['metadata']['validator_offsets'].items():
                    # Extract filename from path/URL
                    source_name = source.split('/')[-1]
                    print(f"    - {source_name}: +{offset:,}")

        if network_spec['tags']:
            print("\n🏷️  Available tags:")
            for tag, nodes in network_spec['tags'].items():
                print(f"    - {tag}: {len(nodes)} nodes")

    except ValueError as e:
        print(f"\n❌ Validation Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()