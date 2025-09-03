"""
ClickHouse queries for PeerDAS Analysis V2 - Head correctness analysis.

These queries analyze attestation head correctness (voting for proposed block_roots,
including those that may have been reorged) and blob counts, with support for 
filtering by proposer and attester node characteristics.
"""

def get_head_correctness_per_slot_query() -> str:
    """
    Compute head correctness per slot entirely in ClickHouse.

    Inputs via params/formatting:
    - %(network)s: network name
    - %(start_date)s, %(end_date)s: datetime bounds (UTC)
    - %(eligible_slots)s: slots tuple string e.g. "(26400,26401,...)" (loader injects)
    - {validator_filter}: optional SQL fragment to restrict validators (e.g., "AND validator_index IN (...)")

    Notes:
    - Unions canonical elaborated attestations (expands validators) with gossipsub aggregators.
    - Deduplicates per (slot, validator_index) and counts a validator as correct if ANY attestation
      for that (slot, validator) voted for the proposed block_root (including reorged blocks).
    - Blob counts are derived from sidecar tables. For libp2p on fusaka-devnet-4, divide
      kzg_commitments_count by 2 to correct the known doubling.
    - Uses GLOBAL IN to avoid distributed_product_mode errors.
    """
    return """
    WITH
    eligible_slots AS (
      -- CRITICAL: We use beacon_api_eth_v2_beacon_block NOT canonical_beacon_block
      -- This captures ALL proposed blocks including those that were reorged out
      -- Using canonical would create survivorship bias - we want to see what validators
      -- voted for AT THE TIME, not just the blocks that eventually won
      SELECT slot, block_root
      FROM beacon_api_eth_v2_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
      GROUP BY slot, block_root
      -- In rare cases of multiple blocks per slot, just take any one (they're all valid proposals)
      LIMIT 1 BY slot
    ),
    -- Keep only slots that have committee data to avoid bogus counts from LEFT JOIN defaults
    committee_members AS (
      SELECT slot, arrayJoin(validators) AS validator_index
      FROM canonical_beacon_committee
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
      {validator_filter}
      UNION DISTINCT
      SELECT slot, arrayJoin(validators) AS validator_index
      FROM beacon_api_eth_v1_beacon_committee
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
      {validator_filter}
    ),
    committee_slots AS (
      SELECT DISTINCT slot FROM committee_members
    ),
    eligible_slots_filtered AS (
      -- Only include slots that have committee data
      SELECT es.slot, es.block_root
      FROM eligible_slots es
      INNER JOIN committee_slots cs ON es.slot = cs.slot
    ),
    attested_unique AS (
      -- Get attestations and check correctness in one step
      -- Only count attestations from validators who were assigned to attest in this slot
      SELECT 
        a.slot AS slot, 
        a.validator_index AS validator_index,
        maxIf(1, a.beacon_block_root = e.block_root) AS correct_vote
      FROM (
        SELECT slot, arrayJoin(validators) AS validator_index, beacon_block_root
        FROM canonical_beacon_elaborated_attestation
        WHERE meta_network_name = %(network)s
          AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
          AND slot GLOBAL IN %(eligible_slots)s
        {validator_filter}
        UNION ALL
        SELECT slot, attesting_validator_index AS validator_index, beacon_block_root
        FROM libp2p_gossipsub_beacon_attestation
        WHERE meta_network_name = %(network)s
          AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
          AND slot GLOBAL IN %(eligible_slots)s
          AND attesting_validator_index IS NOT NULL
        {validator_filter}
        UNION ALL
        SELECT slot, attesting_validator_index AS validator_index, beacon_block_root
        FROM beacon_api_eth_v1_events_attestation
        WHERE meta_network_name = %(network)s
          AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
          AND slot GLOBAL IN %(eligible_slots)s
          AND attesting_validator_index IS NOT NULL
        {validator_filter}
      ) a
      LEFT JOIN eligible_slots e ON a.slot = e.slot
      INNER JOIN committee_members cm ON a.slot = cm.slot AND a.validator_index = cm.validator_index
      GROUP BY a.slot, a.validator_index
    ),
    blob_counts AS (
      -- Prefer API counts; adjust libp2p counts for fusaka-devnet-4 by dividing by 2
      SELECT slot, toUInt64(length(anyLast(kzg_commitments))) AS blob_count
      FROM beacon_api_eth_v1_events_data_column_sidecar
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
      GROUP BY slot
      UNION ALL
      SELECT slot,
             toUInt64(
               if(%(network)s = 'fusaka-devnet-4',
                  greatest(kzg_commitments_count / 2, 0),
                  kzg_commitments_count)
             ) AS blob_count
      FROM libp2p_gossipsub_data_column_sidecar
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
      GROUP BY slot, kzg_commitments_count
    ),
    slot_blob AS (
      -- If both sources exist, they should match; take max to be safe
      SELECT slot, max(blob_count) AS blob_count
      FROM blob_counts
      GROUP BY slot
    )
    SELECT e.slot,
           countDistinct(cm.validator_index) AS total_scheduled,
           countDistinctIf(cm.validator_index, au.correct_vote = 1) AS correct_votes,
           if(countDistinct(cm.validator_index) > 0,
              round(100.0 * countDistinctIf(cm.validator_index, au.correct_vote = 1)
                    / countDistinct(cm.validator_index), 2),
              NULL
           ) AS head_correctness_pct,
           coalesce(sb.blob_count, toUInt64(0)) AS blob_count
    -- Start from slots that we KNOW have committee data
    FROM eligible_slots_filtered e
    INNER JOIN committee_members cm ON e.slot = cm.slot
    LEFT JOIN attested_unique au ON e.slot = au.slot AND cm.validator_index = au.validator_index
    LEFT JOIN slot_blob sb ON e.slot = sb.slot
    GROUP BY e.slot, sb.blob_count
    ORDER BY e.slot
    """


def get_head_correctness_per_slot_grouped_query(group_by: str) -> str:
    """
    Compute head correctness per slot grouped by PROPOSER characteristics.

    Supported group_by: 'node_type' | 'cl_client' | 'el_client' | 'cl_el_combined' | 'cl_node_type'

    Requires inline proposer mapping injected as {proposer_map_union_selects}, e.g.,
      SELECT 12345 AS slot, 'supernode' AS node_type, 'lighthouse' AS cl_client, 'geth' AS el_client
      UNION ALL  
      SELECT 12346 AS slot, 'regular' AS node_type, 'prysm' AS cl_client, 'nethermind' AS el_client
    """
    group_expr = {
        'node_type': "coalesce(pm.node_type, 'unknown')",
        'cl_client': "coalesce(pm.cl_client, 'unknown')",
        'el_client': "coalesce(pm.el_client, 'unknown')",
        'cl_el_combined': "coalesce(concat(pm.cl_client, '-', pm.el_client), 'unknown')",
        'cl_node_type': "coalesce(concat(pm.cl_client, '-', pm.node_type), 'unknown')"
    }.get(group_by, "coalesce(pm.node_type, 'unknown')")

    return f"""
    WITH
    eligible_slots AS (
      -- CRITICAL: We use beacon_api_eth_v2_beacon_block NOT canonical_beacon_block
      -- This captures ALL proposed blocks including those that were reorged out
      -- Using canonical would create survivorship bias - we want to see what validators
      -- voted for AT THE TIME, not just the blocks that eventually won
      SELECT slot, block_root, proposer_index
      FROM beacon_api_eth_v2_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
      GROUP BY slot, block_root, proposer_index
      -- In rare cases of multiple blocks per slot, just take any one (they're all valid proposals)
      LIMIT 1 BY slot
    ),
    proposer_map AS (
      {{proposer_map_union_selects}}
    ),
    -- Committee members for filtering to valid slots only
    committee_members AS (
      SELECT slot, arrayJoin(validators) AS validator_index
      FROM canonical_beacon_committee
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
      UNION DISTINCT
      SELECT slot, arrayJoin(validators) AS validator_index
      FROM beacon_api_eth_v1_beacon_committee
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
    ),
    committee_slots AS (
      SELECT DISTINCT slot FROM committee_members
    ),
    eligible_slots_filtered AS (
      SELECT es.slot, es.block_root, es.proposer_index
      FROM eligible_slots es
      INNER JOIN committee_slots cs ON es.slot = cs.slot
    ),
    slots_with_proposer_info AS (
      SELECT es.slot, es.block_root, es.proposer_index, {group_expr} AS group_key
      FROM eligible_slots_filtered es
      LEFT JOIN proposer_map pm ON es.slot = pm.slot
    ),
    attested_unique AS (
      -- Get attestations and check correctness in one step
      -- Only count attestations from validators who were assigned to attest in this slot
      SELECT 
        a.slot AS slot, 
        a.validator_index AS validator_index,
        maxIf(1, a.beacon_block_root = e.block_root) AS correct_vote
      FROM (
        SELECT slot, arrayJoin(validators) AS validator_index, beacon_block_root
        FROM canonical_beacon_elaborated_attestation
        WHERE meta_network_name = %(network)s
          AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
          AND slot GLOBAL IN %(eligible_slots)s
        {{validator_filter}}
        UNION ALL
        SELECT slot, attesting_validator_index AS validator_index, beacon_block_root
        FROM libp2p_gossipsub_beacon_attestation
        WHERE meta_network_name = %(network)s
          AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
          AND slot GLOBAL IN %(eligible_slots)s
          AND attesting_validator_index IS NOT NULL
        {{validator_filter}}
        UNION ALL
        SELECT slot, attesting_validator_index AS validator_index, beacon_block_root
        FROM beacon_api_eth_v1_events_attestation
        WHERE meta_network_name = %(network)s
          AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
          AND slot GLOBAL IN %(eligible_slots)s
          AND attesting_validator_index IS NOT NULL
        {{validator_filter}}
      ) a
      LEFT JOIN eligible_slots e ON a.slot = e.slot
      INNER JOIN committee_members cm ON a.slot = cm.slot AND a.validator_index = cm.validator_index
      GROUP BY a.slot, a.validator_index
    ),
    blob_counts AS (
      SELECT slot, toUInt64(length(anyLast(kzg_commitments))) AS blob_count
      FROM beacon_api_eth_v1_events_data_column_sidecar
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
      GROUP BY slot
      UNION ALL
      SELECT slot, toUInt64(
               if(%(network)s = 'fusaka-devnet-4', greatest(kzg_commitments_count / 2, 0), kzg_commitments_count)
             ) AS blob_count
      FROM libp2p_gossipsub_data_column_sidecar
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
      GROUP BY slot, kzg_commitments_count
    ),
    slot_blob AS (
      SELECT slot, max(blob_count) AS blob_count
      FROM blob_counts
      GROUP BY slot
    ),
    slot_head_correctness AS (
      -- Calculate head correctness per slot
      -- Start from eligible_slots to ensure we always have results
      SELECT 
        e.slot AS slot,
        countDistinct(cm.validator_index) AS total_scheduled,
        countDistinctIf(cm.validator_index, au.correct_vote = 1) AS correct_votes,
        if(countDistinct(cm.validator_index) > 0,
           round(100.0 * countDistinctIf(cm.validator_index, au.correct_vote = 1) 
                 / countDistinct(cm.validator_index), 2),
           NULL
        ) AS head_correctness_pct
      FROM eligible_slots_filtered e
      INNER JOIN committee_members cm ON e.slot = cm.slot
      LEFT JOIN attested_unique au ON e.slot = au.slot AND cm.validator_index = au.validator_index
      GROUP BY e.slot
    )
    SELECT
      e.slot AS slot,
      coalesce(sb.blob_count, toUInt64(0)) AS blob_count,
      spi.group_key AS group_key,
      coalesce(shc.total_scheduled, 0) AS total_scheduled_in_group,
      coalesce(shc.correct_votes, 0) AS correct_votes_in_group,
      shc.head_correctness_pct AS head_correctness_pct
    FROM eligible_slots_filtered e
    LEFT JOIN slot_head_correctness shc ON e.slot = shc.slot
    LEFT JOIN slots_with_proposer_info spi ON e.slot = spi.slot
    LEFT JOIN slot_blob sb ON e.slot = sb.slot
    ORDER BY e.slot, spi.group_key
    """


def get_eligible_slots_query() -> str:
    """
    Get slots where blocks were proposed, filtered by proposer characteristics.
    
    This returns slots where blocks were actually proposed by nodes matching
    the proposer filter criteria. The proposer_filter is built based on
    validator indices from the network spec.
    """
    return """
    SELECT DISTINCT
        slot,
        slot_start_date_time,
        epoch,
        block_root,
        proposer_index
    FROM beacon_api_eth_v2_beacon_block
    WHERE meta_network_name = %(network)s
      AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
      {proposer_filter}
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
