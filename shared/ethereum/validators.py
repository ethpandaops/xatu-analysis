"""
Validator metadata utilities for Ethereum beacon chain analysis

Functions for loading validator consensus client and entity information.
"""
import pandas as pd
from sqlalchemy import text
from ..database import get_database_connection


def load_blockprint_clients(network):
    """Load blockprint client information for validators.
    
    Args:
        network (str): Network name (mainnet, holesky, sepolia)
        
    Returns:
        dict: Mapping of proposer_index -> blockprint_client
    """
    connection = get_database_connection()
    if connection is None:
        return {}
        
    try:
        # Electra epoch 364032 = slot 11,649,024. Blockprint is broken after Electra.
        # We use pre-Electra blockprint data for ALL blocks by each validator.
        electra_slot = 364032 * 32  # 11,649,024
        
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
    finally:
        connection.close()


def load_validators_from_ethseer(network):
    """Load validators from the ethseer_validator_entity table for the specified network.
    
    Args:
        network (str): Network name (mainnet, holesky, sepolia)
        
    Returns:
        dict: Mapping of proposer_index -> entity
    """
    connection = get_database_connection()
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
    finally:
        connection.close()