"""
ClickHouse queries for PeerDAS Analysis V2 - Head correctness analysis.

These queries analyze attestation head correctness (voting for the correct block_root)
and blob counts, with support for filtering by proposer and attester node characteristics.
"""

def get_eligible_slots_query() -> str:
    """
    Get eligible slots based on proposer filtering criteria.
    
    For devnets: Filter by proposer_index from network spec
    For others: Get all slots (no client filtering possible without network spec)
    """
    return """
    SELECT DISTINCT
        slot,
        slot_start_date_time,
        epoch,
        block_root,
        proposer_index
    FROM canonical_beacon_block
    WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        {proposer_filter}
    ORDER BY slot
    """

def get_committee_assignments_query() -> str:
    """
    Get committee assignments for eligible slots.
    
    Returns all validators that were scheduled to attest in the given slots.
    This is needed to calculate head correctness percentages.
    
    Uses both canonical_beacon_committee and beacon_api_eth_v1_beacon_committee tables,
    combining their data with deduplication.
    """
    return """
    SELECT DISTINCT
        slot,
        committee_index,
        validator_index
    FROM (
        SELECT 
            slot,
            committee_index,
            arrayJoin(validators) as validator_index
        FROM canonical_beacon_committee
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND slot IN %(eligible_slots)s
        
        UNION DISTINCT
        
        SELECT 
            slot,
            committee_index,
            arrayJoin(validators) as validator_index
        FROM beacon_api_eth_v1_beacon_committee
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND slot IN %(eligible_slots)s
    )
    ORDER BY slot, validator_index
    """

def get_head_correctness_attestations_query() -> str:
    """
    Get attestations for head correctness analysis from multiple sources.
    
    Gets attestations with their beacon_block_root to determine if they voted
    for the correct head. Combines both libp2p gossipsub and canonical elaborated
    attestations, limiting to 1 attestation per epoch per validator.
    """
    return """
    WITH 
    -- Source 1: Libp2p gossipsub attestations
    libp2p_attestations AS (
        SELECT 
            slot,
            attesting_validator_index as validator_index,
            committee_index,
            beacon_block_root,
            'libp2p_gossipsub' as source
        FROM libp2p_gossipsub_beacon_attestation FINAL
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND slot IN %(eligible_slots)s
            AND attesting_validator_index IS NOT NULL
    ),
    
    -- Source 2: Canonical elaborated attestations
    canonical_attestations AS (
        SELECT 
            slot,
            arrayJoin(validators) as validator_index,
            committee_index,
            beacon_block_root,
            'canonical_elaborated' as source
        FROM canonical_beacon_elaborated_attestation
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND slot IN %(eligible_slots)s
            AND validators IS NOT NULL AND length(validators) > 0
    ),
    
    -- Combine all sources
    all_attestations AS (
        SELECT * FROM libp2p_attestations
        UNION ALL
        SELECT * FROM canonical_attestations
    ),
    
    -- Deduplicate to 1 attestation per epoch per validator
    -- Use row_number to select first occurrence
    deduplicated_attestations AS (
        SELECT 
            slot,
            validator_index,
            committee_index,
            beacon_block_root,
            source,
            ROW_NUMBER() OVER (
                PARTITION BY intDiv(slot, 32), validator_index 
                ORDER BY slot, source
            ) as rn
        FROM all_attestations
        WHERE 1=1
            {validator_filter}
    )
    
    SELECT 
        slot,
        validator_index,
        committee_index,
        beacon_block_root,
        source
    FROM deduplicated_attestations
    WHERE rn = 1
    ORDER BY slot, validator_index
    """

def get_blob_counts_query() -> str:
    """
    Get blob counts from data_column_sidecar tables ONLY.
    
    Returns blob counts for slots to enable bucketing analysis.
    Uses kzg_commitments_count (libp2p) or length(kzg_commitments) (beacon_api).
    
    NOTE: Only returns data where data_column_sidecar exists. 
    No fallbacks - if there's no sidecar data, there's no blob data.
    """
    return """
    SELECT DISTINCT
        slot,
        blob_count
    FROM (
        -- libp2p_gossipsub_data_column_sidecar 
        SELECT 
            slot,
            kzg_commitments_count as blob_count
        FROM libp2p_gossipsub_data_column_sidecar
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND slot IN %(eligible_slots)s
            AND kzg_commitments_count IS NOT NULL
        GROUP BY slot, kzg_commitments_count
        
        UNION DISTINCT
        
        -- beacon_api_eth_v1_events_data_column_sidecar
        SELECT 
            slot,
            length(kzg_commitments) as blob_count
        FROM beacon_api_eth_v1_events_data_column_sidecar
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND slot IN %(eligible_slots)s
            AND kzg_commitments IS NOT NULL
        GROUP BY slot, blob_count
    )
    ORDER BY slot
    """

def get_node_classification_query() -> str:
    """
    Get node classifications from network configuration.
    
    Maps client names to node types, CL/EL implementations based on
    the network specification YAML files.
    """
    return """
    -- This query would need to be replaced with actual network mapping logic
    -- For now returning a simplified version
    SELECT DISTINCT
        meta_client_name as client_name,
        CASE 
            WHEN meta_client_name LIKE '%%supernode%%' THEN 'supernode'
            ELSE 'regular'
        END as node_type,
        splitByChar('-', meta_client_name)[1] as cl_implementation,
        splitByChar('-', meta_client_name)[2] as el_implementation
    FROM beacon_api_eth_v1_events_attestation
    WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND meta_client_name != ''
    GROUP BY meta_client_name
    """

def get_proposer_blocks_query() -> str:
    """
    Get blocks proposed by specific node types/implementations.
    
    Used to filter eligible slots based on proposer characteristics.
    """
    return """
    SELECT 
        slot,
        block_root,
        proposer_index,
        meta_client_name as proposer_client
    FROM canonical_beacon_block
    WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        {proposer_conditions}
    ORDER BY slot
    """

def build_proposer_filter(proposer_indices: list = None) -> str:
    """
    Build SQL filter clause for proposer eligibility.
    
    Only works with network spec - filters by proposer indices.
    
    Args:
        proposer_indices: List of specific proposer indices from network spec
    
    Returns:
        SQL WHERE clause fragment
    """
    if proposer_indices:
        indices_str = ','.join(str(idx) for idx in proposer_indices)
        return f"AND proposer_index IN ({indices_str})"
    return ""

def build_validator_filter(validator_indices: list = None) -> str:
    """
    Build SQL filter clause for validator filtering.
    
    Only works with network spec - filters by validator indices.
    
    Args:
        validator_indices: List of specific validator indices from network spec
    
    Returns:
        SQL WHERE clause fragment
    """
    if validator_indices:
        indices_str = ','.join(str(idx) for idx in validator_indices)
        return f"AND validator_index IN ({indices_str})"
    return ""