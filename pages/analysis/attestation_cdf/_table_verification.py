import streamlit as st
from shared.database import get_database_connection


@st.cache_data(ttl=3600)
def verify_table_structures():
    """Verify existence and structure of required tables."""
    conn = get_database_connection()
    
    required_tables = [
        "libp2p_gossipsub_beacon_attestation",
        "beacon_api_eth_v1_events_attestation", 
        "beacon_api_eth_v1_events_block",
        "beacon_api_eth_v2_beacon_block",
        "mev_relay_proposer_payload_delivered",
        "canonical_beacon_block"
    ]
    
    table_info = {}
    for table in required_tables:
        try:
            # Check table existence and get sample columns
            result = conn.execute(f"DESCRIBE {table} LIMIT 5").fetchall()
            table_info[table] = {
                "exists": True,
                "columns": [row[0] for row in result],
                "sample_query": f"SELECT * FROM {table} LIMIT 1"
            }
        except Exception as e:
            table_info[table] = {
                "exists": False,
                "error": str(e),
                "alternative_tables": []
            }
    
    return table_info


def get_verified_query_templates():
    """Return verified SQL query templates based on actual schema with partition optimization."""
    return {
        "attestation_timing": """
            SELECT 
                meta_client_name,
                slot,
                attesting_validator_index,
                propagation_slot_start_diff,
                meta_network_name
            FROM libp2p_gossipsub_beacon_attestation
            WHERE slot_start_date_time BETWEEN '{start_date}' AND '{end_date}'
                AND attesting_validator_index IS NOT NULL
                AND slot BETWEEN {start_slot} AND {end_slot}
                AND meta_network_name = '{network}'
            """,
        "beacon_api_attestations": """
            SELECT 
                slot,
                attesting_validator_index,
                propagation_slot_start_diff,
                meta_client_name,
                meta_network_name
            FROM beacon_api_eth_v1_events_attestation
            WHERE slot_start_date_time BETWEEN '{start_date}' AND '{end_date}'
                AND attesting_validator_index IS NOT NULL
                AND slot BETWEEN {start_slot} AND {end_slot}
                AND meta_network_name = '{network}'
            """,
        "block_events": """
            SELECT 
                slot,
                block as block_root,
                propagation_slot_start_diff,
                meta_client_name
            FROM beacon_api_eth_v1_events_block
            WHERE slot_start_date_time BETWEEN '{start_date}' AND '{end_date}'
                AND slot BETWEEN {start_slot} AND {end_slot}
                AND meta_network_name = '{network}'
            """,
        "block_details": """
            SELECT 
                slot,
                proposer_index,
                block_root,
                execution_payload_gas_used,
                meta_network_name
            FROM beacon_api_eth_v2_beacon_block
            WHERE slot_start_date_time BETWEEN '{start_date}' AND '{end_date}'
                AND slot BETWEEN {start_slot} AND {end_slot}
                AND meta_network_name = '{network}'
            """,
        "mev_relay_blocks": """
            SELECT 
                slot,
                block_hash,
                proposer_pubkey,
                relay_name,
                1 as is_mev
            FROM mev_relay_proposer_payload_delivered
            WHERE slot_start_date_time BETWEEN '{start_date}' AND '{end_date}'
                AND slot BETWEEN {start_slot} AND {end_slot}
            """,
        "canonical_blocks": """
            SELECT 
                slot,
                block_root,
                1 as is_canonical
            FROM canonical_beacon_block
            WHERE slot_start_date_time BETWEEN '{start_date}' AND '{end_date}'
                AND slot BETWEEN {start_slot} AND {end_slot}
            """
    }