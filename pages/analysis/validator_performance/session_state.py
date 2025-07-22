"""Session state management for validator performance dashboard."""
import streamlit as st
from typing import Dict, List


def store_validator_mappings(pubkey_to_index: Dict[str, int], excluded_pubkeys: List[str]) -> None:
    """
    Store validator pubkey to index mappings and excluded pubkeys in session state.
    
    Args:
        pubkey_to_index: Dictionary mapping pubkeys to validator indices
        excluded_pubkeys: List of pubkeys that were not found in the database
    """
    st.session_state['validator_performance_pubkey_to_index'] = pubkey_to_index
    st.session_state['validator_performance_excluded_pubkeys'] = excluded_pubkeys


def get_valid_validators() -> Dict[str, int]:
    """
    Get the stored pubkey to index mapping.
    
    Returns:
        Dictionary mapping pubkeys to validator indices
    """
    return st.session_state.get('validator_performance_pubkey_to_index', {})


def get_excluded_validators() -> List[str]:
    """
    Get the list of excluded validator pubkeys.
    
    Returns:
        List of pubkeys that were not found in the database
    """
    return st.session_state.get('validator_performance_excluded_pubkeys', [])


def clear_validator_mappings() -> None:
    """
    Clear stored validator mappings when configuration changes.
    """
    if 'validator_performance_pubkey_to_index' in st.session_state:
        del st.session_state['validator_performance_pubkey_to_index']
    if 'validator_performance_excluded_pubkeys' in st.session_state:
        del st.session_state['validator_performance_excluded_pubkeys']