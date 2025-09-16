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
import json
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


def check_validator_overlaps(merged_spec: Dict[str, Any]) -> List[Tuple[int, int]]:
    """
    Check for overlapping validator ranges in the merged spec.

    Args:
        merged_spec: Merged network specification

    Returns:
        List of overlapping ranges as tuples (start, end)

    Raises:
        ValueError: If overlapping validator ranges are detected
    """
    # Collect all validator ranges
    validator_ranges = []

    for node_name, node_data in merged_spec['nodes'].items():
        if node_data.get('validator_range'):
            vrange = node_data['validator_range']
            validator_ranges.append({
                'start': vrange['start'],
                'end': vrange['end'],
                'node': node_name
            })

    # Check for overlaps
    overlaps = []
    for i, range1 in enumerate(validator_ranges):
        for j, range2 in enumerate(validator_ranges[i+1:], i+1):
            # Check if ranges overlap
            if not (range1['end'] <= range2['start'] or range2['end'] <= range1['start']):
                overlap_start = max(range1['start'], range2['start'])
                overlap_end = min(range1['end'], range2['end'])
                overlaps.append((overlap_start, overlap_end))
                print(f"\n⚠️  Validator range overlap detected:")
                print(f"    Node '{range1['node']}': [{range1['start']:,}, {range1['end']:,})")
                print(f"    Node '{range2['node']}': [{range2['start']:,}, {range2['end']:,})")
                print(f"    Overlapping range: [{overlap_start:,}, {overlap_end:,})")

    return overlaps


def detect_validator_gaps(merged_spec: Dict[str, Any]) -> List[Tuple[int, int]]:
    """
    Detect gaps in validator ranges.

    Args:
        merged_spec: Merged network specification

    Returns:
        List of gaps as tuples (start, end)
    """
    # Collect all validator ranges and sort them
    ranges = []
    for node_name, node_data in merged_spec['nodes'].items():
        if node_data.get('validator_range'):
            vrange = node_data['validator_range']
            ranges.append((vrange['start'], vrange['end']))

    if not ranges:
        return []

    # Sort ranges by start index
    ranges.sort(key=lambda x: x[0])

    # Find gaps
    gaps = []

    # Check for gap at the beginning (if first range doesn't start at 0)
    if ranges[0][0] > 0:
        gaps.append((0, ranges[0][0]))

    # Check for gaps between consecutive ranges
    for i in range(len(ranges) - 1):
        current_end = ranges[i][1]
        next_start = ranges[i + 1][0]
        if current_end < next_start:
            gaps.append((current_end, next_start))

    return gaps


def analyze_validator_ranges(specs: List[Dict[str, Any]], source_list: List[str],
                            merge_strategy: str = 'preserve-indices',
                            validator_mapping: Optional[Dict[str, Dict[str, int]]] = None) -> List[Dict[str, Any]]:
    """
    Analyze validator ranges across inventories and calculate offsets.

    Args:
        specs: List of parsed network specifications
        source_list: List of source paths/URLs
        merge_strategy: 'auto-offset' or 'preserve-indices'
        validator_mapping: Optional mapping of inventory to offset

    Returns:
        List of inventory info with calculated offsets
    """
    inventory_info = []
    current_offset = 0

    for idx, spec in enumerate(specs):
        source = source_list[idx] if idx < len(source_list) else f'inventory_{idx}'

        # Extract inventory identifier for mapping
        # Try to extract a meaningful identifier from the source
        source_identifier = None
        if '/' in source:
            # Extract from URL path
            parts = source.split('/')
            # Look for patterns like 'testinprod-io' or similar
            for part in parts:
                if 'testinprod' in part.lower():
                    source_identifier = 'testinprod-io'
                    break
                elif 'ethpandaops' in part.lower():
                    source_identifier = 'ethpandaops'
                    break
                elif 'hetzner' in part.lower():
                    source_identifier = 'hetzner'
                    break

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
            # Determine offset based on strategy
            if merge_strategy == 'preserve-indices':
                # Check if there's a custom mapping for this inventory
                if validator_mapping and source_identifier and source_identifier in validator_mapping:
                    offset = validator_mapping[source_identifier].get('offset', 0)
                else:
                    offset = 0  # No offset in preserve-indices mode
            else:  # auto-offset
                offset = current_offset

            info = {
                'index': idx,
                'source': source,
                'source_identifier': source_identifier,
                'original_range': {
                    'start': min_validator,
                    'end': max_validator + 1  # Make it exclusive like the original
                },
                'offset': offset,
                'new_range': {
                    'start': min_validator + offset,
                    'end': (max_validator + 1) + offset
                },
                'validator_count': validator_count,
                'nodes_with_validators': len(nodes_with_validators)
            }
            inventory_info.append(info)

            # Update offset for next inventory (only in auto-offset mode)
            if merge_strategy == 'auto-offset':
                current_offset = info['new_range']['end']
        else:
            # No validators in this inventory
            info = {
                'index': idx,
                'source': source,
                'source_identifier': source_identifier,
                'original_range': None,
                'offset': 0,
                'new_range': None,
                'validator_count': 0,
                'nodes_with_validators': 0
            }
            inventory_info.append(info)

    return inventory_info


def confirm_processing_order(inventory_info: List[Dict[str, Any]], merge_strategy: str) -> bool:
    """
    Display processing order and offsets for confirmation.

    Args:
        inventory_info: List of inventory information with offsets
        merge_strategy: The merge strategy being used

    Returns:
        True if user confirms, False otherwise
    """
    print("\n" + "="*80)
    print("📋 INVENTORY PROCESSING CONFIRMATION")
    print(f"   Merge Strategy: {merge_strategy}")
    print("="*80)

    print("\nInventories will be processed in the following order:\n")

    for info in inventory_info:
        print(f"  [{info['index'] + 1}] {info['source']}")
        if info.get('source_identifier'):
            print(f"      Identifier: {info['source_identifier']}")
        if info['original_range']:
            print(f"      Original validator range: [{info['original_range']['start']:,}, {info['original_range']['end']:,})")
            print(f"      Validators: {info['validator_count']:,} across {info['nodes_with_validators']} nodes")
            if info['offset'] > 0:
                print(f"      ✨ Offset applied: +{info['offset']:,}")
                print(f"      New validator range: [{info['new_range']['start']:,}, {info['new_range']['end']:,})")
            elif merge_strategy == 'preserve-indices':
                print(f"      Final validator range: [{info['new_range']['start']:,}, {info['new_range']['end']:,})")
        else:
            print(f"      No validators in this inventory")
        print()

    # Calculate actual validator counts (not using max index)
    total_assigned_validators = sum(info['validator_count'] for info in inventory_info)
    total_nodes = sum(info['nodes_with_validators'] for info in inventory_info)

    # Find the actual max index from all ranges
    max_index = -1
    for info in inventory_info:
        if info['new_range']:
            max_index = max(max_index, info['new_range']['end'] - 1)

    print("📊 Summary:")
    print(f"  - Total inventories: {len(inventory_info)}")
    print(f"  - Assigned validators: {total_assigned_validators:,}")
    print(f"  - Max validator index: {max_index:,}")
    print(f"  - Total nodes with validators: {total_nodes}")

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


def merge_network_specs(specs: List[Dict[str, Any]], inventory_info: List[Dict[str, Any]],
                       merge_strategy: str = 'preserve-indices') -> Dict[str, Any]:
    """
    Merge multiple network specifications into one with automatic offset application.

    Args:
        specs: List of parsed network specifications
        inventory_info: List of inventory information with calculated offsets
        merge_strategy: The merge strategy being used

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

    # Track merge strategy in metadata
    merged['metadata']['merge_strategy'] = merge_strategy

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

    # Calculate actual validator count (sum of all validator counts, not max index)
    actual_validator_count = 0
    for node_name, node_data in merged['nodes'].items():
        if node_data.get('validator_range'):
            actual_validator_count += node_data['validator_range']['count']

    # Store both counts for clarity
    merged['validators']['assigned_count'] = actual_validator_count
    merged['validators']['max_index'] = max_validator_index
    # Keep total_count for backward compatibility but use assigned count
    merged['validators']['total_count'] = actual_validator_count

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
    parser.add_argument(
        '--merge-strategy',
        choices=['auto-offset', 'preserve-indices'],
        default='preserve-indices',
        help='Merge strategy for validator ranges (default: preserve-indices)'
    )
    parser.add_argument(
        '--validator-mapping',
        type=str,
        help='JSON mapping of inventory identifiers to offsets (e.g., \'{"testinprod-io": {"offset": 50912}}\')'
    )
    parser.add_argument(
        '--expected-validators',
        type=int,
        help='Expected total number of validators (for validation)'
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

        # Parse validator mapping if provided
        validator_mapping = None
        if args.validator_mapping:
            try:
                validator_mapping = json.loads(args.validator_mapping)
                print(f"\n📍 Using validator mapping: {validator_mapping}")
            except json.JSONDecodeError as e:
                print(f"\n❌ Error parsing validator mapping JSON: {e}", file=sys.stderr)
                sys.exit(1)

        # Merge specifications if multiple
        if len(specs) > 1:
            print(f"\nAnalyzing {len(specs)} inventory files...")
            print(f"Merge strategy: {args.merge_strategy}")

            # Analyze validator ranges and calculate offsets
            inventory_info = analyze_validator_ranges(specs, source_list,
                                                     args.merge_strategy,
                                                     validator_mapping)

            # Show confirmation dialog
            if not confirm_processing_order(inventory_info, args.merge_strategy):
                print("\n❌ Operation cancelled by user")
                sys.exit(0)

            print(f"\n✅ Proceeding with merge using {args.merge_strategy} strategy...")
            network_spec = merge_network_specs(specs, inventory_info, args.merge_strategy)

            # Check for overlaps if using preserve-indices
            if args.merge_strategy == 'preserve-indices':
                overlaps = check_validator_overlaps(network_spec)
                if overlaps:
                    print("\n❌ Error: Validator range overlaps detected!")
                    print("   Cannot proceed with preserve-indices strategy when ranges overlap.")
                    print("   Consider using --merge-strategy auto-offset or fix the inventory files.")
                    sys.exit(1)

            print("  ✓ Merge complete")
        else:
            network_spec = specs[0]
            inventory_info = analyze_validator_ranges(specs, source_list,
                                                     args.merge_strategy,
                                                     validator_mapping)

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

        # Print validator counts
        if 'assigned_count' in network_spec['validators']:
            print(f"  - Assigned validators: {network_spec['validators']['assigned_count']:,}")
            print(f"  - Max validator index: {network_spec['validators'].get('max_index', 0):,}")
        else:
            print(f"  - Total validators: {network_spec['validators']['total_count']:,}")

        # Check against expected validators if provided
        if args.expected_validators:
            actual = network_spec['validators'].get('assigned_count', network_spec['validators']['total_count'])
            if actual != args.expected_validators:
                print(f"\n⚠️  WARNING: Validator count mismatch!")
                print(f"    Expected: {args.expected_validators:,}")
                print(f"    Actual:   {actual:,}")
                print(f"    Missing:  {args.expected_validators - actual:,}")
            else:
                print(f"  ✅ Validator count matches expected: {args.expected_validators:,}")

        # Detect and report gaps
        gaps = detect_validator_gaps(network_spec)
        if gaps:
            print("\n⚠️  Validator gaps detected:")
            total_gap_size = 0
            for gap_start, gap_end in gaps:
                gap_size = gap_end - gap_start
                total_gap_size += gap_size
                print(f"    - Indices {gap_start:,}-{gap_end-1:,} ({gap_size:,} validators) - no nodes assigned")
            print(f"    Total gap size: {total_gap_size:,} validators")

        if len(source_list) > 1:
            print(f"\n  - Merged from {len(source_list)} inventory files")
            print(f"  - Merge strategy: {args.merge_strategy}")

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