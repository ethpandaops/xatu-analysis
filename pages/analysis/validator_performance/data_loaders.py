"""Data loading functionality for validator performance analysis."""
import streamlit as st
from typing import List, Dict, Any, Tuple, Optional
import pandas as pd
from sqlalchemy import text
from shared.database import get_database_connection


def load_validator_indices(pubkeys: List[str], network: str) -> Tuple[Dict[str, int], List[str]]:
    """
    Load validator indices from ClickHouse for given pubkeys.
    
    Args:
        pubkeys: List of cleaned, validated pubkeys (0x-prefixed, lowercase)
        network: Network name ('mainnet', 'holesky', etc.)
        
    Returns:
        Tuple of (mapping dict, list of missing pubkeys)
        - mapping dict: {pubkey: validator_index}
        - missing list: pubkeys not found in database
    """
    if not pubkeys:
        return {}, []
    
    conn = None
    try:
        conn = get_database_connection()
        
        # Build the query with proper formatting for ClickHouse IN clause
        # Convert pubkeys list to a comma-separated string of quoted values
        pubkeys_str = ', '.join([f"'{pk}'" for pk in pubkeys])
        
        query = f"""
            SELECT pubkey, `index` 
            FROM canonical_beacon_validators_pubkeys FINAL 
            WHERE meta_network_name = '{network}' 
            AND pubkey IN ({pubkeys_str})
        """
        
        # Execute query using pandas read_sql for better compatibility
        df = pd.read_sql(query, conn)
        
        # Build mapping from results
        pubkey_to_index = {row['pubkey']: row['index'] for _, row in df.iterrows()}
        
        # Identify missing pubkeys
        missing_pubkeys = [pk for pk in pubkeys if pk not in pubkey_to_index]
        
        return pubkey_to_index, missing_pubkeys
        
    except Exception as e:
        st.error(f"Error loading validator indices: {str(e)}")
        # Return empty mapping and all pubkeys as missing on error
        return {}, pubkeys
        
    finally:
        if conn:
            conn.close()