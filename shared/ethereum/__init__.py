"""
Ethereum beacon chain data utilities

This package provides reusable functionality for loading and processing
Ethereum beacon chain data from Xatu:

- validators.py: Validator metadata (blockprint, ethseer)
- blocks.py: Block and proposer data
- attestations.py: Attestation data loading
- validator_filters.py: Validator filtering utilities for network analysis
"""

# Convenient imports for common functions
from .validators import load_blockprint_clients, load_validators_from_ethseer
from .blocks import fetch_proposer_indices, fetch_proposer_indices_parquet
from .attestations import load_attestation_data, load_attestation_data_parquet
from .validator_filters import (
    create_proposer_filters_ui,
    create_attester_filters_ui,
    get_filtered_proposer_indices,
    get_filtered_attester_indices,
    get_node_classifications,
    get_network_summary,
    validate_network_filters
)

__all__ = [
    'load_blockprint_clients',
    'load_validators_from_ethseer', 
    'fetch_proposer_indices',
    'fetch_proposer_indices_parquet',
    'load_attestation_data',
    'load_attestation_data_parquet',
    'create_proposer_filters_ui',
    'create_attester_filters_ui',
    'get_filtered_proposer_indices',
    'get_filtered_attester_indices',
    'get_node_classifications',
    'get_network_summary',
    'validate_network_filters'
]