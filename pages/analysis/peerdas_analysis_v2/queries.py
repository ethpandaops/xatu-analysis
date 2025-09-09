"""
ClickHouse queries for PeerDAS Analysis V2 - Head correctness analysis.

These queries analyze attestation head correctness (voting for proposed block_roots,
including those that may have been reorged) and blob counts, with support for 
filtering by proposer and attester node characteristics.
"""

# ============================================================================
# REUSABLE CTE COMPONENTS
# ============================================================================

def _get_eligible_slots_cte() -> str:
    """CTE for getting eligible slots with proposed blocks (including reorged)."""
    return """
    eligible_slots AS (
      -- CRITICAL: We use beacon_api_eth_v2_beacon_block NOT canonical_beacon_block
      -- This captures ALL proposed blocks including those that were reorged out
      SELECT slot, block_root, proposer_index
      FROM beacon_api_eth_v2_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
      GROUP BY slot, block_root, proposer_index
      -- In rare cases of multiple blocks per slot, just take any one (they're all valid proposals)
      LIMIT 1 BY slot
    )"""


def _get_mev_slots_cte() -> str:
    """CTE for identifying MEV relay slots."""
    return """
    mev_slots AS (
      -- Get slots that were delivered via MEV relay
      -- IMPORTANT: Filter out slot = 0 which is invalid/corrupt data
      SELECT DISTINCT slot
      FROM mev_relay_proposer_payload_delivered
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
        AND slot > 0  -- Filter out corrupt entries with slot = 0
    )"""


def _get_committee_members_cte() -> str:
    """CTE for getting committee members with optional validator filter."""
    return """
    committee_members AS (
      SELECT slot, arrayJoin(validators) AS validator_index
      FROM canonical_beacon_committee
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
      {validator_filter}
      UNION DISTINCT
      SELECT slot, arrayJoin(validators) AS validator_index
      FROM beacon_api_eth_v1_beacon_committee
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
      {validator_filter}
    )"""


def _get_committee_slots_cte() -> str:
    """CTE for getting distinct slots with committee data."""
    return """
    committee_slots AS (
      SELECT DISTINCT slot FROM committee_members
    )"""


def _get_eligible_slots_filtered_cte(include_proposer: bool = True) -> str:
    """CTE for filtering eligible slots to those with committee data."""
    if include_proposer:
        fields = "es.slot AS slot, es.block_root AS block_root, es.proposer_index AS proposer_index"
    else:
        fields = "es.slot AS slot, es.block_root AS block_root"
    return f"""
    eligible_slots_filtered AS (
      SELECT {fields}
      FROM eligible_slots es
      INNER JOIN committee_slots cs ON es.slot = cs.slot
    )"""


def _get_attested_unique_cte() -> str:
    """CTE for getting unique attestations and checking correctness."""
    return """
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
    )"""


def _get_blob_counts_cte() -> str:
    """CTE for getting blob counts from sidecar data."""
    return """
    blob_counts AS (
      SELECT b1.slot AS slot, toUInt64(length(anyLast(b1.kzg_commitments))) AS blob_count
      FROM beacon_api_eth_v1_events_data_column_sidecar AS b1
      WHERE b1.meta_network_name = %(network)s
        AND b1.slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND b1.slot GLOBAL IN %(eligible_slots)s
      GROUP BY b1.slot
      UNION ALL
      SELECT b2.slot AS slot, toUInt64(b2.kzg_commitments_count) AS blob_count
      FROM libp2p_gossipsub_data_column_sidecar AS b2
      WHERE b2.meta_network_name = %(network)s
        AND b2.slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND b2.slot GLOBAL IN %(eligible_slots)s
      GROUP BY b2.slot, b2.kzg_commitments_count
    )"""


def _get_slot_blob_cte() -> str:
    """CTE for aggregating blob counts per slot."""
    return """
    slot_blob AS (
      SELECT blob_counts.slot AS slot, max(blob_counts.blob_count) AS blob_count
      FROM blob_counts
      GROUP BY blob_counts.slot
    )"""

def get_head_correctness_per_slot_query() -> str:
    """
    Compute head correctness per slot entirely in ClickHouse.
    Uses reusable CTE components.
    """
    # Build CTEs properly
    ctes = []
    ctes.append(_get_eligible_slots_cte().strip())
    ctes.append(_get_committee_members_cte().strip())
    ctes.append(_get_committee_slots_cte().strip())
    ctes.append(_get_eligible_slots_filtered_cte(include_proposer=False).strip())
    ctes.append(_get_attested_unique_cte().strip())
    ctes.append(_get_blob_counts_cte().strip())
    ctes.append(_get_slot_blob_cte().strip())
    
    cte_string = ",\n    ".join(ctes)
    
    return f"""
    WITH
    {cte_string}
    SELECT e.slot,
           countDistinct(cm.validator_index) AS total_scheduled,
           countDistinctIf(cm.validator_index, au.correct_vote = 1) AS correct_votes,
           if(countDistinct(cm.validator_index) > 0,
              round(100.0 * countDistinctIf(cm.validator_index, au.correct_vote = 1)
                    / countDistinct(cm.validator_index), 2),
              NULL
           ) AS head_correctness_pct,
           coalesce(sb.blob_count, toUInt64(0)) AS blob_count
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

    Supported group_by: 'node_type' | 'cl_client' | 'el_client' | 'cl_el_combined' | 'cl_node_type' | 
                        'node_type_mev' | 'cl_node_type_mev'

    Requires inline proposer mapping injected as {proposer_map_union_selects}, e.g.,
      SELECT 12345 AS slot, 'supernode' AS node_type, 'lighthouse' AS cl_client, 'geth' AS el_client
      UNION ALL  
      SELECT 12346 AS slot, 'regular' AS node_type, 'prysm' AS cl_client, 'nethermind' AS el_client
    """
    # For MEV grouping, we need to handle the MEV check differently
    # Check if mev.slot is not null AND > 0 to handle corrupt data
    if group_by == 'none':
        # Special case: no grouping, show all proposers together
        group_expr = "'all'"
    elif group_by == 'block_building':
        group_expr = "if(isNotNull(mev.slot) AND mev.slot > 0, 'mev', 'non-mev')"
    elif group_by == 'node_type_mev':
        group_expr = "coalesce(concat(pm.node_type, '-', if(isNotNull(mev.slot) AND mev.slot > 0, 'mev', 'non-mev')), 'unknown')"
    elif group_by == 'cl_node_type_mev':
        group_expr = "coalesce(concat(pm.cl_client, '-', pm.node_type, '-', if(isNotNull(mev.slot) AND mev.slot > 0, 'mev', 'non-mev')), 'unknown')"
    else:
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
    mev_slots AS (
      -- Get slots that were delivered via MEV relay
      -- IMPORTANT: Filter out slot = 0 which is invalid/corrupt data
      SELECT DISTINCT slot
      FROM mev_relay_proposer_payload_delivered
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
        AND slot > 0  -- Filter out corrupt entries with slot = 0
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
      {{validator_filter}}
      UNION DISTINCT
      SELECT slot, arrayJoin(validators) AS validator_index
      FROM beacon_api_eth_v1_beacon_committee
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
      {{validator_filter}}
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
      SELECT 
        es.slot AS slot, 
        es.block_root AS block_root, 
        es.proposer_index AS proposer_index, 
        {group_expr} AS group_key
      FROM eligible_slots_filtered es
      LEFT JOIN proposer_map pm ON es.slot = pm.slot
      LEFT JOIN mev_slots mev ON es.slot = mev.slot
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
      SELECT b1.slot AS slot, toUInt64(length(anyLast(b1.kzg_commitments))) AS blob_count
      FROM beacon_api_eth_v1_events_data_column_sidecar AS b1
      WHERE b1.meta_network_name = %(network)s
        AND b1.slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND b1.slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
      GROUP BY b1.slot
      UNION ALL
      SELECT b2.slot AS slot, toUInt64(b2.kzg_commitments_count) AS blob_count
      FROM libp2p_gossipsub_data_column_sidecar AS b2
      WHERE b2.meta_network_name = %(network)s
        AND b2.slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND b2.slot GLOBAL IN %(eligible_slots)s  -- Use the full slot list, not just slots with blocks
      GROUP BY b2.slot, b2.kzg_commitments_count
    ),
    slot_blob AS (
      SELECT blob_counts.slot AS slot, max(blob_counts.blob_count) AS blob_count
      FROM blob_counts
      GROUP BY blob_counts.slot
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
      coalesce(spi.group_key, 'unknown') AS group_key,
      coalesce(shc.total_scheduled, 0) AS total_scheduled_in_group,
      coalesce(shc.correct_votes, 0) AS correct_votes_in_group,
      shc.head_correctness_pct AS head_correctness_pct
    FROM eligible_slots_filtered e
    LEFT JOIN slot_head_correctness shc ON e.slot = shc.slot
    LEFT JOIN slots_with_proposer_info spi ON e.slot = spi.slot
    LEFT JOIN slot_blob sb ON e.slot = sb.slot
    ORDER BY e.slot, coalesce(spi.group_key, 'unknown')
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


def get_head_correctness_per_slot_attester_grouped_query(group_by: str) -> str:
    """
    Compute head correctness grouped by ATTESTER characteristics.
    
    This groups validators by their node characteristics and calculates
    head correctness for each group across all slots.
    
    Supported group_by: 'node_type' | 'cl_client' | 'el_client' | 'cl_el_combined'
    
    Requires inline attester mapping injected as {attester_map_union_selects}, e.g.,
      SELECT 12345 AS validator_index, 'supernode' AS node_type, 'lighthouse' AS cl_client, 'geth' AS el_client
      UNION ALL  
      SELECT 12346 AS validator_index, 'regular' AS node_type, 'prysm' AS cl_client, 'nethermind' AS el_client
    """
    # Determine group expression
    # Note: No need for coalesce since we're INNER JOINing with attester_map
    if group_by == 'none':
        group_expr = "'all'"
    else:
        group_expr = {
            'node_type': "am.node_type",
            'cl_client': "am.cl_client",
            'el_client': "am.el_client",
            'cl_el_combined': "concat(am.cl_client, '-', am.el_client)",
            'cl_node_type': "concat(am.cl_client, '-', am.node_type)"
        }.get(group_by, "am.node_type")
    
    # Build CTEs properly - need to handle the placeholder replacements
    eligible_slots = _get_eligible_slots_cte().strip()
    attester_map = """attester_map AS (
      {attester_map_union_selects}
    )"""
    committee_members = _get_committee_members_cte().strip()
    committee_slots = _get_committee_slots_cte().strip()
    eligible_slots_filtered = _get_eligible_slots_filtered_cte(include_proposer=False).strip()
    attested_unique = _get_attested_unique_cte().strip()
    blob_counts = _get_blob_counts_cte().strip()
    slot_blob = _get_slot_blob_cte().strip()
    
    cte_string = f"""{eligible_slots},
    {attester_map},
    {committee_members},
    {committee_slots},
    {eligible_slots_filtered},
    {attested_unique},
    {blob_counts},
    {slot_blob}"""
    
    # Determine join type based on grouping
    # When group_by is 'none', include all validators
    # Otherwise, only include validators in our network spec
    if group_by == 'none':
        attester_join = "LEFT JOIN attester_map am ON cm.validator_index = am.validator_index"
    else:
        attester_join = "INNER JOIN attester_map am ON cm.validator_index = am.validator_index  -- INNER JOIN to filter out unknown validators"
    
    return f"""
    WITH
    {cte_string},
    -- Group attestations by attester characteristics
    attester_grouped_correctness AS (
      SELECT 
        e.slot AS slot,
        {group_expr} AS group_key,
        cm.validator_index AS validator_index,
        au.correct_vote AS correct_vote,
        sb.blob_count AS blob_count
      FROM eligible_slots_filtered e
      INNER JOIN committee_members cm ON e.slot = cm.slot
      {attester_join}
      LEFT JOIN attested_unique au ON e.slot = au.slot AND cm.validator_index = au.validator_index
      LEFT JOIN slot_blob sb ON e.slot = sb.slot
    )
    SELECT 
      agc.slot,
      agc.group_key,
      countDistinct(agc.validator_index) AS total_scheduled,
      countDistinctIf(agc.validator_index, agc.correct_vote = 1) AS correct_votes,
      if(countDistinct(agc.validator_index) > 0,
         round(100.0 * countDistinctIf(agc.validator_index, agc.correct_vote = 1)
               / countDistinct(agc.validator_index), 2),
         NULL
      ) AS head_correctness_pct,
      coalesce(agc.blob_count, toUInt64(0)) AS blob_count
    FROM attester_grouped_correctness agc
    GROUP BY agc.slot, agc.group_key, agc.blob_count
    ORDER BY agc.slot, agc.group_key
    """


def get_mev_slots_query() -> str:
    """
    Get slots that were delivered via MEV relay.
    
    Returns slots with MEV payloads from mev_relay_proposer_payload_delivered table.
    Filters out slot = 0 which is invalid/corrupt data.
    """
    return """
    SELECT DISTINCT
        slot
    FROM mev_relay_proposer_payload_delivered
    WHERE meta_network_name = %(network)s
      AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
      AND slot > 0  -- Filter out corrupt entries with slot = 0
    ORDER BY slot
    """
