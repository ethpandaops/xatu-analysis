"""
Validator metadata utilities for Ethereum beacon chain analysis

Functions for loading validator consensus client and entity information.
"""
import pandas as pd
from sqlalchemy import text
from ..database import get_database_connection
import streamlit as st


@st.cache_data(ttl=3600)  # Cache for 1 hour
def load_blockprint_clients(network, cluster_name=None):
    """Load blockprint client information for validators.
    
    Args:
        network (str): Network name (mainnet, holesky, sepolia)
        cluster_name (str, optional): ClickHouse cluster name. If None, uses default cluster.
        
    Returns:
        dict: Mapping of proposer_index -> blockprint_client. Returns empty dict if no data available.
    """
    connection = get_database_connection(cluster_name)
    if connection is None:
        return {}
        
    try:
        # Electra epochs by network:
        # - mainnet: epoch 364032 = slot 11,649,024
        # - holesky: epoch 105088 = slot 3,362,816
        # - sepolia: epoch 378368 = slot 12,107,776
        electra_slots = {
            'mainnet': 364032 * 32,  # 11,649,024
            'holesky': 105088 * 32,  # 3,362,816
            'sepolia': 378368 * 32   # 12,107,776
        }
        electra_slot = electra_slots.get(network, 364032 * 32)  # Default to mainnet if unknown
        
        blockprint_query = text("""
        WITH pre_electra_blockprint AS (
            SELECT DISTINCT
                proposer_index,
                argMax(best_guess_single, slot) as blockprint_client
            FROM
                default.beacon_block_classification
            WHERE
                slot < :electra_slot
            GROUP BY
                proposer_index
        ),
        all_validators AS (
            SELECT DISTINCT proposer_index
            FROM canonical_beacon_block
            WHERE meta_network_name = :network
        )
        
        SELECT
            av.proposer_index,
            COALESCE(peb.blockprint_client, 'unknown') AS blockprint_client
        FROM
            all_validators av
        LEFT JOIN
            pre_electra_blockprint peb ON peb.proposer_index = av.proposer_index
        """)
        
        result = connection.execute(blockprint_query, {"network": network, "electra_slot": electra_slot}).fetchall()
        
        # Convert to DataFrame
        blockprint_df = pd.DataFrame(result, columns=['proposer_index', 'blockprint_client'])
        
        # Create a dictionary with validator index as key and blockprint client as value
        blockprint_map = {}
        for _, row in blockprint_df.iterrows():
            client = row['blockprint_client']
            if client is None or pd.isna(client) or client == '':
                client = 'unknown'
            blockprint_map[row['proposer_index']] = client
        
        return blockprint_map
    except Exception as e:
        # Log the error but don't fail - return empty dict for graceful fallback
        # This handles cases where the blockprint tables might not have data
        import logging
        logging.warning(f"Could not load blockprint clients for network {network}: {str(e)}")
        return {}
    finally:
        connection.close()


@st.cache_data(ttl=3600)  # Cache for 1 hour
def load_validators_from_ethseer(network, cluster_name=None):
    """Load validators from the ethseer_validator_entity table for the specified network.
    
    Args:
        network (str): Network name (mainnet, holesky, sepolia)
        cluster_name (str, optional): ClickHouse cluster name. If None, uses default cluster.
        
    Returns:
        dict: Mapping of proposer_index -> entity. Returns empty dict if no data available.
    """
    connection = get_database_connection(cluster_name)
    if connection is None:
        return {}
        
    try:
        # Query to fetch validator entities from ethseer
        proposer_query = text("""
            SELECT 
                `index` as proposer_index,
                entity
            FROM ethseer_validator_entity
            WHERE 
                meta_network_name = :network
        """)
        
        result = connection.execute(proposer_query, {"network": network}).fetchall()
        
        # If no data is available (e.g., for non-mainnet networks), return empty dict
        # The calling code should handle this gracefully with fallback to 'unknown'
        if not result:
            return {}
        
        # Convert the result to a pandas DataFrame
        validator_entities_df = pd.DataFrame(result, columns=['proposer_index', 'entity'])
        
        # Convert the dataframe to a dictionary for easier lookup
        validators_map = {}
        for _, row in validator_entities_df.iterrows():
            entity = row['entity']
            if entity is None or pd.isna(entity) or entity == '':
                entity = 'unknown'
            validators_map[row['proposer_index']] = entity
        
        return validators_map
    except Exception as e:
        # Log the error but don't fail - return empty dict for graceful fallback
        # This handles cases where the ethseer_validator_entity table might not exist
        # or have data for certain networks
        import logging
        logging.warning(f"Could not load validator entities for network {network}: {str(e)}")
        return {}
    finally:
        connection.close()