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
    attested AS (
      SELECT slot, arrayJoin(validators) AS validator_index, beacon_block_root
      FROM canonical_beacon_elaborated_attestation
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
      {validator_filter}
      UNION ALL
      SELECT slot, attesting_validator_index AS validator_index, beacon_block_root
      FROM libp2p_gossipsub_beacon_attestation
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
        AND attesting_validator_index IS NOT NULL
      {validator_filter}
      UNION ALL
      SELECT slot, attesting_validator_index AS validator_index, beacon_block_root
      FROM beacon_api_eth_v1_events_attestation
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
        AND attesting_validator_index IS NOT NULL
      {validator_filter}
    ),
    attested_with_committee AS (
      -- Join attestations with committee to filter only scheduled validators
      SELECT 
        a.slot AS slot, 
        a.validator_index AS validator_index,
        a.beacon_block_root AS beacon_block_root,
        e.block_root AS proposed_block_root
      FROM attested a
      INNER JOIN committee_members cm ON a.slot = cm.slot AND a.validator_index = cm.validator_index
      LEFT JOIN eligible_slots e ON a.slot = e.slot
    ),
    attested_unique AS (
      -- Aggregate to get unique validator votes per slot
      SELECT 
        slot, 
        validator_index,
        maxIf(1, beacon_block_root = proposed_block_root) AS correct_vote
      FROM attested_with_committee
      GROUP BY slot, validator_index
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
           coalesce(countDistinct(cm.validator_index), 0) AS total_scheduled,
           coalesce(countDistinctIf(au.validator_index, au.correct_vote = 1), 0) AS correct_votes,
           if(countDistinct(cm.validator_index) > 0,
              round(100.0 * countDistinctIf(au.validator_index, au.correct_vote = 1)
                    / countDistinct(cm.validator_index), 2),
              NULL
           ) AS head_correctness_pct,
           coalesce(sb.blob_count, toUInt64(0)) AS blob_count
    -- Start from eligible_slots to ensure we have results even without committee data
    FROM eligible_slots e
    LEFT JOIN committee_members cm ON e.slot = cm.slot
    LEFT JOIN attested_unique au ON e.slot = au.slot AND cm.validator_index = au.validator_index
    LEFT JOIN slot_blob sb ON e.slot = sb.slot
    GROUP BY e.slot, sb.blob_count
    ORDER BY e.slot
    """


def get_head_correctness_per_slot_stake_weighted_query() -> str:
    """
    Compute stake-weighted head correctness per slot entirely in ClickHouse.
    
    This version weights validators by their effective balance, important for
    MaxEB validators who can have up to 2048 ETH effective balance.
    
    Inputs via params/formatting:
    - %(network)s: network name
    - %(start_date)s, %(end_date)s: datetime bounds (UTC)
    - %(eligible_slots)s: slots tuple string e.g. "(26400,26401,...)" (loader injects)
    - {validator_filter}: optional SQL fragment to restrict validators
    
    Returns head correctness weighted by stake rather than validator count.
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
      LIMIT 1 BY slot
    ),
    -- Get effective balances for all validators (fallback to 32 ETH if not available)
    validator_balances AS (
      SELECT 
        validator_index,
        effective_balance
      FROM canonical_beacon_validators
      WHERE meta_network_name = %(network)s
        AND epoch = (SELECT max(epoch) FROM canonical_beacon_validators WHERE meta_network_name = %(network)s LIMIT 1)
        AND epoch IS NOT NULL
    ),
    committee_members AS (
      SELECT cm.slot, cm.validator_index, coalesce(vb.effective_balance, 32000000000) as effective_balance
      FROM (
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
      ) cm
      LEFT JOIN validator_balances vb ON cm.validator_index = vb.validator_index
    ),
    attested AS (
      SELECT slot, arrayJoin(validators) AS validator_index, beacon_block_root
      FROM canonical_beacon_elaborated_attestation
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
      {validator_filter}
      UNION ALL
      SELECT slot, attesting_validator_index AS validator_index, beacon_block_root
      FROM libp2p_gossipsub_beacon_attestation
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
        AND attesting_validator_index IS NOT NULL
      {validator_filter}
      UNION ALL
      SELECT slot, attesting_validator_index AS validator_index, beacon_block_root
      FROM beacon_api_eth_v1_events_attestation
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
        AND attesting_validator_index IS NOT NULL
      {validator_filter}
    ),
    attested_with_committee AS (
      -- Join attestations with committee to filter only scheduled validators
      SELECT 
        a.slot AS slot, 
        a.validator_index AS validator_index,
        a.beacon_block_root AS beacon_block_root,
        e.block_root AS proposed_block_root,
        cm.effective_balance AS effective_balance
      FROM attested a
      INNER JOIN committee_members cm ON a.slot = cm.slot AND a.validator_index = cm.validator_index
      LEFT JOIN eligible_slots e ON a.slot = e.slot
    ),
    attested_unique AS (
      -- Aggregate to get unique validator votes per slot
      SELECT 
        slot, 
        validator_index,
        maxIf(1, beacon_block_root = proposed_block_root) AS correct_vote,
        max(effective_balance) AS effective_balance
      FROM attested_with_committee
      GROUP BY slot, validator_index
    ),
    blob_counts AS (
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
      SELECT slot, max(blob_count) AS blob_count
      FROM blob_counts
      GROUP BY slot
    )
    SELECT e.slot,
           coalesce(sum(cm.effective_balance), 0) AS total_scheduled_stake,
           coalesce(sumIf(au.effective_balance, au.correct_vote = 1), 0) AS correct_stake,
           if(sum(cm.effective_balance) > 0,
              round(100.0 * sumIf(au.effective_balance, au.correct_vote = 1)
                    / sum(cm.effective_balance), 2),
              NULL
           ) AS head_correctness_pct,
           coalesce(countDistinct(cm.validator_index), 0) AS total_validators_assigned,
           coalesce(countDistinctIf(au.validator_index, au.correct_vote = 1), 0) AS correct_head_votes,
           coalesce(sb.blob_count, toUInt64(0)) AS blob_count
    -- Start from eligible_slots to ensure we have results even without committee data
    FROM eligible_slots e
    LEFT JOIN committee_members cm ON e.slot = cm.slot
    LEFT JOIN attested_unique au ON e.slot = au.slot AND cm.validator_index = au.validator_index
    LEFT JOIN slot_blob sb ON e.slot = sb.slot
    GROUP BY e.slot, sb.blob_count
    ORDER BY e.slot
    """


def get_committee_distinct_validators_query() -> str:
    """
    Get distinct validator indices scheduled in the eligible slots.

    Uses both canonical_beacon_committee and beacon_api_eth_v1_beacon_committee.
    """
    return """
    SELECT DISTINCT validator_index
    FROM (
      SELECT arrayJoin(validators) AS validator_index
      FROM canonical_beacon_committee
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
      UNION DISTINCT
      SELECT arrayJoin(validators) AS validator_index
      FROM beacon_api_eth_v1_beacon_committee
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
    )
    ORDER BY validator_index
    """


def get_head_correctness_per_slot_grouped_stake_weighted_query(group_by: str) -> str:
    """
    Compute stake-weighted head correctness per slot grouped by PROPOSER characteristics.
    
    This version weights validators by their effective balance (important for MaxEB validators).
    
    Supported group_by: 'node_type' | 'cl_client' | 'el_client' | 'cl_el_combined' | 'cl_node_type'
    
    Requires inline proposer mapping injected as {proposer_map_union_selects}.
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
      SELECT slot, block_root, proposer_index
      FROM beacon_api_eth_v2_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
      GROUP BY slot, block_root, proposer_index
      LIMIT 1 BY slot
    ),
    proposer_map AS (
      {{proposer_map_union_selects}}
    ),
    slots_with_proposer_info AS (
      SELECT es.slot, es.block_root, es.proposer_index, {group_expr} AS group_key
      FROM eligible_slots es
      LEFT JOIN proposer_map pm ON es.slot = pm.slot
    ),
    -- Get effective balances for all validators (fallback to 32 ETH if not available)
    validator_balances AS (
      SELECT 
        validator_index,
        effective_balance
      FROM canonical_beacon_validators
      WHERE meta_network_name = %(network)s
        AND epoch = (SELECT max(epoch) FROM canonical_beacon_validators WHERE meta_network_name = %(network)s LIMIT 1)
        AND epoch IS NOT NULL
    ),
    committee_members AS (
      SELECT cm.slot, cm.validator_index, coalesce(vb.effective_balance, 32000000000) as effective_balance
      FROM (
        SELECT slot, arrayJoin(validators) AS validator_index
        FROM canonical_beacon_committee
        WHERE meta_network_name = %(network)s
          AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
          AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
        UNION DISTINCT
        SELECT slot, arrayJoin(validators) AS validator_index
        FROM beacon_api_eth_v1_beacon_committee
        WHERE meta_network_name = %(network)s
          AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
          AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
      ) cm
      LEFT JOIN validator_balances vb ON cm.validator_index = vb.validator_index
    ),
    attested AS (
      -- Get all attestations
      SELECT slot, arrayJoin(validators) AS validator_index, beacon_block_root
      FROM canonical_beacon_elaborated_attestation
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
      UNION ALL
      SELECT slot, attesting_validator_index AS validator_index, beacon_block_root
      FROM libp2p_gossipsub_beacon_attestation
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
        AND attesting_validator_index IS NOT NULL
      UNION ALL
      SELECT slot, attesting_validator_index AS validator_index, beacon_block_root
      FROM beacon_api_eth_v1_events_attestation
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
        AND attesting_validator_index IS NOT NULL
    ),
    attested_with_committee AS (
      -- Join attestations with committee to filter only scheduled validators
      SELECT 
        a.slot AS slot, 
        a.validator_index AS validator_index,
        a.beacon_block_root AS beacon_block_root,
        e.block_root AS proposed_block_root,
        cm.effective_balance AS effective_balance
      FROM attested a
      INNER JOIN committee_members cm ON a.slot = cm.slot AND a.validator_index = cm.validator_index
      LEFT JOIN eligible_slots e ON a.slot = e.slot
    ),
    attested_unique AS (
      -- Aggregate to get unique validator votes per slot
      SELECT 
        slot, 
        validator_index,
        maxIf(1, beacon_block_root = proposed_block_root) AS correct_vote,
        max(effective_balance) AS effective_balance
      FROM attested_with_committee
      GROUP BY slot, validator_index
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
      -- Calculate stake-weighted head correctness per slot
      -- Start from eligible_slots to ensure we always have results
      SELECT 
        e.slot AS slot,
        coalesce(sum(cm.effective_balance), 0) AS total_scheduled_stake,
        coalesce(sumIf(au.effective_balance, au.correct_vote = 1), 0) AS correct_stake,
        if(sum(cm.effective_balance) > 0,
           round(100.0 * sumIf(au.effective_balance, au.correct_vote = 1)
                 / sum(cm.effective_balance), 2),
           NULL
        ) AS head_correctness_pct
      FROM eligible_slots e
      LEFT JOIN committee_members cm ON e.slot = cm.slot
      LEFT JOIN attested_unique au ON e.slot = au.slot AND cm.validator_index = au.validator_index
      GROUP BY e.slot
    )
    SELECT
      e.slot AS slot,
      coalesce(sb.blob_count, toUInt64(0)) AS blob_count,
      spi.group_key AS group_key,
      coalesce(shc.total_scheduled_stake, 0) AS total_scheduled_in_group,
      coalesce(shc.correct_stake, 0) AS correct_votes_in_group,
      shc.head_correctness_pct AS head_correctness_pct
    FROM eligible_slots e
    LEFT JOIN slot_head_correctness shc ON e.slot = shc.slot
    LEFT JOIN slots_with_proposer_info spi ON e.slot = spi.slot
    LEFT JOIN slot_blob sb ON e.slot = sb.slot
    ORDER BY e.slot, spi.group_key
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
    slots_with_proposer_info AS (
      SELECT es.slot, es.block_root, es.proposer_index, {group_expr} AS group_key
      FROM eligible_slots es
      LEFT JOIN proposer_map pm ON es.slot = pm.slot
    ),
    committee_members AS (
      SELECT slot, arrayJoin(validators) AS validator_index
      FROM canonical_beacon_committee
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
      UNION DISTINCT
      SELECT slot, arrayJoin(validators) AS validator_index
      FROM beacon_api_eth_v1_beacon_committee
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
    ),
    attested AS (
      -- Get all attestations
      SELECT slot, arrayJoin(validators) AS validator_index, beacon_block_root
      FROM canonical_beacon_elaborated_attestation
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
      UNION ALL
      SELECT slot, attesting_validator_index AS validator_index, beacon_block_root
      FROM libp2p_gossipsub_beacon_attestation
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
        AND attesting_validator_index IS NOT NULL
      UNION ALL
      SELECT slot, attesting_validator_index AS validator_index, beacon_block_root
      FROM beacon_api_eth_v1_events_attestation
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
        AND attesting_validator_index IS NOT NULL
    ),
    attested_with_committee AS (
      -- Join attestations with committee to filter only scheduled validators
      SELECT 
        a.slot AS slot, 
        a.validator_index AS validator_index,
        a.beacon_block_root AS beacon_block_root,
        e.block_root AS proposed_block_root
      FROM attested a
      INNER JOIN committee_members cm ON a.slot = cm.slot AND a.validator_index = cm.validator_index
      LEFT JOIN eligible_slots e ON a.slot = e.slot
    ),
    attested_unique AS (
      -- Aggregate to get unique validator votes per slot
      SELECT 
        slot, 
        validator_index,
        maxIf(1, beacon_block_root = proposed_block_root) AS correct_vote
      FROM attested_with_committee
      GROUP BY slot, validator_index
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
        coalesce(countDistinct(cm.validator_index), 0) AS total_scheduled,
        coalesce(countDistinctIf(au.validator_index, au.correct_vote = 1), 0) AS correct_votes,
        if(countDistinct(cm.validator_index) > 0,
           round(100.0 * countDistinctIf(au.validator_index, au.correct_vote = 1) 
                 / countDistinct(cm.validator_index), 2),
           NULL
        ) AS head_correctness_pct
      FROM eligible_slots e
      LEFT JOIN committee_members cm ON e.slot = cm.slot
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
    FROM eligible_slots e
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

def get_eligible_slots_with_blob_query() -> str:
    """
    Get eligible slots limited to those with blob sidecar data present.

    This prevents confusing states where proposer-eligible slots exist but no
    sidecar data is available to bucket by blob_count.
    """
    return """
    WITH sidecar_slots AS (
      SELECT DISTINCT slot
      FROM (
        SELECT slot
        FROM libp2p_gossipsub_data_column_sidecar
        WHERE meta_network_name = %(network)s
          AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        UNION ALL
        SELECT slot
        FROM beacon_api_eth_v1_events_data_column_sidecar
        WHERE meta_network_name = %(network)s
          AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
      )
    ),
    blocks AS (
      SELECT slot, block_root, proposer_index, slot_start_date_time, epoch
      FROM beacon_api_eth_v2_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        {proposer_filter}
        AND slot GLOBAL IN (SELECT slot FROM sidecar_slots)
      GROUP BY slot, block_root, proposer_index, slot_start_date_time, epoch
      -- In rare cases of multiple blocks per slot, just take any one
      LIMIT 1 BY slot
    )
    SELECT DISTINCT
        slot,
        slot_start_date_time,
        epoch,
        block_root,
        proposer_index
    FROM blocks
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
    -- Source 1: Canonical elaborated attestations
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
    
    -- Source 2: Libp2p gossipsub attestations
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
    
    -- Source 3: Beacon API events attestations
    beacon_api_attestations AS (
        SELECT 
            slot,
            attesting_validator_index as validator_index,
            committee_index,
            beacon_block_root,
            'beacon_api_events' as source
        FROM beacon_api_eth_v1_events_attestation
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND slot IN %(eligible_slots)s
            AND attesting_validator_index IS NOT NULL
    ),
    
    -- Combine all sources
    all_attestations AS (
        SELECT * FROM canonical_attestations
        UNION ALL
        SELECT * FROM libp2p_attestations
        UNION ALL
        SELECT * FROM beacon_api_attestations
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
    WITH blocks AS (
      SELECT 
          slot,
          block_root,
          proposer_index,
          meta_client_name as proposer_client
      FROM beacon_api_eth_v2_beacon_block
      WHERE meta_network_name = %(network)s
          AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
          {proposer_conditions}
      GROUP BY slot, block_root, proposer_index, proposer_client
      -- In rare cases of multiple blocks per slot, just take any one
      LIMIT 1 BY slot
    )
    SELECT * FROM blocks
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
