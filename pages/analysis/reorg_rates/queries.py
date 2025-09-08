"""
ClickHouse queries for Reorg Rates Analysis.

These queries analyze block reorganization rates by comparing blocks in 
beacon_api_eth_v2_beacon_block (all proposed blocks) vs canonical_beacon_block 
(finalized chain), with support for filtering by proposer characteristics.
"""

def get_canonical_max_slot_query() -> str:
    """
    Get the highest slot from canonical_beacon_block to ensure we only analyze finalized blocks.
    
    CRITICAL: Only analyze finalized blocks since canonical_beacon_block is 15+ minutes
    behind head. This ensures we don't incorrectly classify recent blocks as reorged
    when they simply haven't been finalized yet.
    """
    return """
    SELECT max(slot) AS max_canonical_slot
    FROM canonical_beacon_block
    WHERE meta_network_name = %(network)s
      AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
    """


def get_reorg_rates_query() -> str:
    """
    Calculate reorg rates by comparing proposed vs canonical blocks.
    
    A block is considered reorged if it exists in beacon_api_eth_v2_beacon_block 
    but NOT in canonical_beacon_block for the same slot.
    
    Inputs via params/formatting:
    - %(network)s: network name
    - %(start_date)s, %(end_date)s: datetime bounds (UTC)
    - %(max_canonical_slot)s: highest finalized slot (from get_canonical_max_slot_query)
    - %(eligible_slots)s: slots tuple string e.g. "(26400,26401,...)" (loader injects)
    - {proposer_filter}: optional SQL fragment to restrict proposers (e.g., "AND proposer_index IN (...)")
    """
    return """
    WITH
    proposed_blocks AS (
      -- Get all blocks that were proposed within our analysis range
      SELECT 
        slot,
        block_root,
        proposer_index,
        slot_start_date_time
      FROM beacon_api_eth_v2_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        {{proposer_filter}}
      GROUP BY slot, block_root, proposer_index, slot_start_date_time
    ),
    canonical_blocks AS (
      -- Get canonical (finalized) blocks for the same slots
      SELECT 
        slot,
        block_root
      FROM canonical_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
      GROUP BY slot, block_root
    ),
    canonical_slots AS (
      -- Get all slots that exist in canonical (to detect missing data)
      SELECT DISTINCT slot
      FROM canonical_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
    ),
    block_status AS (
      -- Determine if each proposed block was reorged
      -- ONLY analyze slots that exist in canonical to avoid false positives from missing data
      SELECT 
        pb.slot AS slot,
        pb.block_root AS proposed_block_root,
        pb.proposer_index AS proposer_index,
        pb.slot_start_date_time AS slot_start_date_time,
        cb.block_root AS canonical_block_root,
        CASE 
          WHEN cb.block_root IS NOT NULL AND substring(cb.block_root, 1, 2) = '0x' THEN 0  -- Block is canonical
          WHEN cs.slot IS NULL THEN -1  -- Slot missing from canonical table (skip)
          ELSE 1  -- Block was reorged
        END AS is_reorged
      FROM proposed_blocks pb
      INNER JOIN canonical_slots cs ON pb.slot = cs.slot  -- Only analyze slots that exist in canonical
      LEFT JOIN canonical_blocks cb ON pb.slot = cb.slot AND pb.block_root = cb.block_root
    )
    SELECT 
      slot,
      slot_start_date_time,
      proposer_index,
      proposed_block_root,
      canonical_block_root,
      is_reorged,
      CASE WHEN is_reorged = 1 THEN 'reorged' ELSE 'canonical' END AS block_status
    FROM block_status
    ORDER BY slot
    """


def get_reorg_rates_grouped_query(group_by: str) -> str:
    """
    Calculate reorg rates grouped by proposer characteristics.
    
    Supported group_by: 'node_type' | 'cl_client' | 'el_client' | 'cl_el_combined' | 'cl_node_type' | 
                        'node_type_mev' | 'cl_node_type_mev'
    
    Requires inline proposer mapping injected as {{proposer_map_union_selects}}, e.g.,
      SELECT 12345 AS proposer_index, 'supernode' AS node_type, 'lighthouse' AS cl_client, 'geth' AS el_client
      UNION ALL
      SELECT 12346 AS proposer_index, 'regular' AS node_type, 'prysm' AS cl_client, 'nethermind' AS el_client
    """
    # Check if we need MEV data
    needs_mev = group_by in ['block_building', 'node_type_mev', 'cl_node_type_mev']
    
    # Handle MEV grouping
    if group_by == 'block_building':
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

    # Build query with conditional MEV CTE
    if needs_mev:
        query = """
    WITH
    proposed_blocks AS (
      -- Get all blocks that were proposed within our analysis range
      SELECT 
        slot,
        block_root,
        proposer_index,
        slot_start_date_time
      FROM beacon_api_eth_v2_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        {{proposer_filter}}
      GROUP BY slot, block_root, proposer_index, slot_start_date_time
    ),
    canonical_blocks AS (
      -- Get canonical (finalized) blocks for the same slots
      SELECT 
        slot,
        block_root
      FROM canonical_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
      GROUP BY slot, block_root
    ),
    canonical_slots AS (
      -- Get all slots that exist in canonical (to detect missing data)
      SELECT DISTINCT slot
      FROM canonical_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
    ),
    mev_slots AS (
      -- Get slots that were delivered via MEV relay
      -- IMPORTANT: Filter out slot = 0 which is invalid/corrupt data
      SELECT DISTINCT slot
      FROM mev_relay_proposer_payload_delivered
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot > 0  -- Filter out corrupt entries with slot = 0
    ),
    proposer_map AS (
      {{proposer_map_union_selects}}
    ),
    block_status AS (
      -- Determine if each proposed block was reorged and add grouping info
      -- ONLY analyze slots that exist in canonical to avoid false positives from missing data
      SELECT 
        pb.slot AS slot,
        pb.block_root AS proposed_block_root,
        pb.proposer_index AS proposer_index,
        pb.slot_start_date_time AS slot_start_date_time,
        cb.block_root AS canonical_block_root,
        CASE 
          WHEN cb.block_root IS NOT NULL AND substring(cb.block_root, 1, 2) = '0x' THEN 0  -- Block is canonical
          ELSE 1  -- Block was reorged
        END AS is_reorged,
        {{group_expr}} AS group_key
      FROM proposed_blocks pb
      INNER JOIN canonical_slots cs ON pb.slot = cs.slot  -- Only analyze slots that exist in canonical
      LEFT JOIN canonical_blocks cb ON pb.slot = cb.slot AND pb.block_root = cb.block_root
      LEFT JOIN proposer_map pm ON pb.proposer_index = pm.proposer_index
      LEFT JOIN mev_slots mev ON pb.slot = mev.slot
    )
    SELECT 
      slot,
      slot_start_date_time,
      proposer_index,
      proposed_block_root,
      canonical_block_root,
      is_reorged,
      CASE WHEN is_reorged = 1 THEN 'reorged' ELSE 'canonical' END AS block_status,
      coalesce(group_key, 'unknown') AS group_key
    FROM block_status
    ORDER BY slot, group_key
    """
        # Replace group_expr placeholder
        query = query.replace('{{group_expr}}', group_expr)
        return query
    else:
        # No MEV data needed
        query = """
    WITH
    proposed_blocks AS (
      -- Get all blocks that were proposed within our analysis range
      SELECT 
        slot,
        block_root,
        proposer_index,
        slot_start_date_time
      FROM beacon_api_eth_v2_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        {{proposer_filter}}
      GROUP BY slot, block_root, proposer_index, slot_start_date_time
    ),
    canonical_blocks AS (
      -- Get canonical (finalized) blocks for the same slots
      SELECT 
        slot,
        block_root
      FROM canonical_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
      GROUP BY slot, block_root
    ),
    canonical_slots AS (
      -- Get all slots that exist in canonical (to detect missing data)
      SELECT DISTINCT slot
      FROM canonical_beacon_block
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
    ),
    proposer_map AS (
      {{proposer_map_union_selects}}
    ),
    block_status AS (
      -- Determine if each proposed block was reorged and add grouping info
      -- ONLY analyze slots that exist in canonical to avoid false positives from missing data
      SELECT 
        pb.slot AS slot,
        pb.block_root AS proposed_block_root,
        pb.proposer_index AS proposer_index,
        pb.slot_start_date_time AS slot_start_date_time,
        cb.block_root AS canonical_block_root,
        CASE 
          WHEN cb.block_root IS NOT NULL AND substring(cb.block_root, 1, 2) = '0x' THEN 0  -- Block is canonical
          ELSE 1  -- Block was reorged
        END AS is_reorged,
        {{group_expr}} AS group_key
      FROM proposed_blocks pb
      INNER JOIN canonical_slots cs ON pb.slot = cs.slot  -- Only analyze slots that exist in canonical
      LEFT JOIN canonical_blocks cb ON pb.slot = cb.slot AND pb.block_root = cb.block_root
      LEFT JOIN proposer_map pm ON pb.proposer_index = pm.proposer_index
    )
    SELECT 
      slot,
      slot_start_date_time,
      proposer_index,
      proposed_block_root,
      canonical_block_root,
      is_reorged,
      CASE WHEN is_reorged = 1 THEN 'reorged' ELSE 'canonical' END AS block_status,
      coalesce(group_key, 'unknown') AS group_key
    FROM block_status
    ORDER BY slot, group_key
    """
        # Replace group_expr placeholder
        query = query.replace('{{group_expr}}', group_expr)
        return query


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
      {{proposer_filter}}
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