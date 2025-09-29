"""
ClickHouse queries for Blob Mempool Analysis.

These queries analyze blob transactions in the mempool compared to blobs
included in canonical beacon blocks, tracking mempool presence and inclusion rates.
"""

from typing import List

def get_canonical_blob_data_query() -> str:
    """
    Query to get canonical blob data from beacon blocks.
    
    This retrieves all slots with their blob counts and blob hashes from canonical blocks.
    """
    return """
    WITH canonical_blobs AS (
        SELECT 
            b.slot,
            b.slot_start_date_time,
            b.block_root,
            b.proposer_index,
            length(bs.kzg_commitment) as blob_count,
            bs.kzg_commitment as kzg_commitments,
            [toString(bs.versioned_hash)] as blob_hashes
        FROM beacon_api_eth_v2_beacon_block b
        LEFT JOIN beacon_api_eth_v1_events_blob_sidecar bs
            ON b.slot = bs.slot 
            AND b.meta_network_name = bs.meta_network_name
        WHERE b.meta_network_name = %(network)s
            AND b.slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            -- AND b.slot BETWEEN %(start_slot)s AND %(end_slot)s
    )
    SELECT 
        slot,
        slot_start_date_time,
        block_root,
        proposer_index,
        COALESCE(blob_count, 0) as blob_count,
        COALESCE(blob_hashes, []) as blob_hashes,
        COALESCE(kzg_commitments, []) as kzg_commitments
    FROM canonical_blobs
    ORDER BY slot
    """

def get_mempool_blob_data_query(client_names: List[str]) -> str:
    """
    Query to get blob transactions from mempool for selected clients.
    
    This retrieves type 3 (blob) transactions from the mempool with their blob hashes
    for the specified time range and clients.
    """
    # Build client filter clause like other queries
    client_filter_clause = ""
    if client_names:
        client_list = "', '".join(client_names)
        client_filter_clause = f"AND meta_client_name IN ('{client_list}')"
    
    return f"""
    SELECT 
        meta_client_name,
        COUNT(*) as mempool_tx_count,
        SUM(length(blob_hashes)) as total_mempool_blobs,
        groupArrayArray(blob_hashes) as all_mempool_blob_hashes,
        AVG(blob_gas) as avg_blob_gas,
        AVG(blob_gas_fee_cap) as avg_blob_gas_fee_cap,
        SUM(blob_sidecars_size) as total_blob_sidecars_size
    FROM mempool_transaction FINAL
    WHERE meta_network_name = %(network)s
        AND event_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND type = 3  -- Blob transactions (EIP-4844)
        {client_filter_clause}
        AND length(blob_hashes) > 0
    GROUP BY meta_client_name
    ORDER BY meta_client_name
    """

def get_combined_blob_analysis_query() -> str:
    """
    Combined query to analyze blob mempool vs canonical inclusion.
    
    This query shows canonical block data (blob data will be loaded separately and merged).
    """
    return """
    SELECT 
        slot,
        slot_start_date_time,
        block_root,
        proposer_index,
        -- Note: Blob data is loaded separately via get_blob_sidecar_data_query()
        -- and merged in Python to avoid distributed query issues
        0 as canonical_blob_count,
        [] as canonical_blob_hashes,
        'No Data' as client_name,
        0 as mempool_tx_count,
        0 as mempool_blob_count,
        [] as mempool_blob_hashes,
        0 as avg_blob_gas,
        0 as avg_blob_gas_fee_cap,
        0 as total_blob_sidecars_size,
        [] as matching_blob_hashes,
        0 as matching_blob_count,
        0 as match_percentage
    FROM beacon_api_eth_v2_beacon_block
    WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        -- AND slot BETWEEN %(start_slot)s AND %(end_slot)s
    ORDER BY slot
    """

def get_blob_sidecar_data_query() -> str:
    """
    Query to get blob sidecar data for slots.
    
    This retrieves blob data separately to avoid JOIN issues.
    """
    return """
    SELECT 
        slot,
        length(kzg_commitments) as blob_count,
        kzg_commitments as blob_hashes
    FROM beacon_api_eth_v1_events_data_column_sidecar
    WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        --AND slot BETWEEN %(start_slot)s AND %(end_slot)s
    ORDER BY slot
    """

def get_client_list_query() -> str:
    """
    Query to get available clients from mempool transaction data.
    
    This is used to populate the client selection dropdown.
    """
    return """
    SELECT DISTINCT meta_client_name
    FROM mempool_transaction FINAL
    WHERE meta_network_name = %(network)s
        AND event_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND meta_client_name != ''
        AND type = 3  -- Only blob transactions
        AND length(blob_hashes) > 0  -- Only clients that have seen blob transactions
    ORDER BY meta_client_name
    """
