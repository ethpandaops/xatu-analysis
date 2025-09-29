"""
ClickHouse queries for Blob Propagation Analysis.

These queries analyze how blob sidecar events propagate to different attester groups
for slots proposed by specific proposer groups, tracking propagation patterns and
client coverage across the network.

Following the same modular CTE approach as PeerDAS Analysis V2.
"""

# ============================================================================
# REUSABLE CTE COMPONENTS FOR BLOB PROPAGATION ANALYSIS
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
    """CTE for identifying MEV relay slots using int_block_mev_head table."""
    return """
    mev_slots_list AS (
      -- Get slots that were delivered via MEV relay
      -- Using int_block_mev_head table which indicates MEV blocks
      SELECT DISTINCT slot
      FROM int_block_mev_head
      WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND slot GLOBAL IN %(eligible_slots)s
        AND slot > 0  -- Filter out corrupt entries with slot = 0
    ),
    mev_slots AS (
      -- Materialize as array to avoid distributed join issues
      SELECT groupArray(slot) as slots FROM mev_slots_list
    )"""


def _get_blob_sidecar_events_cte(data_source: str = "beacon_api") -> str:
    """CTE for getting blob sidecar events with client information.
    
    Only selects fields that exist in both beacon_api and libp2p tables.
    """
    
    # Table names based on data source
    if data_source == 'libp2p':
        blob_sidecar_table = 'libp2p_gossipsub_blob_sidecar FINAL'
        client_impl_col = 'meta_client_implementation'
    else:
        blob_sidecar_table = 'beacon_api_eth_v1_events_blob_sidecar'
        client_impl_col = 'meta_consensus_implementation'
    
    return f"""
    blob_sidecar_events AS (
      SELECT 
        bs.slot,
        bs.blob_index,
        bs.meta_client_name,
        bs.{client_impl_col},
        bs.propagation_slot_start_diff,
        bs.slot_start_date_time,
        bs.meta_client_geo_continent_code
      FROM {blob_sidecar_table} bs
      WHERE bs.meta_network_name = %(network)s
        AND bs.slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND bs.slot GLOBAL IN %(eligible_slots)s
        AND bs.propagation_slot_start_diff < %(max_propagation_ms)s
        AND bs.meta_client_name != ''
    )"""


def _get_blob_sidecar_events_with_time_buckets_cte(data_source: str = "beacon_api", time_bucket_ms: int = 1000) -> str:
    """CTE for getting blob sidecar events with time bucketing for timeline analysis.
    
    Only selects fields that exist in both beacon_api and libp2p tables.
    """
    
    # Table names based on data source
    if data_source == 'libp2p':
        blob_sidecar_table = 'libp2p_gossipsub_blob_sidecar FINAL'
        client_impl_col = 'meta_client_implementation'
    else:
        blob_sidecar_table = 'beacon_api_eth_v1_events_blob_sidecar'
        client_impl_col = 'meta_consensus_implementation'
    
    return f"""
    blob_sidecar_events AS (
      SELECT 
        bs.slot,
        bs.blob_index,
        bs.meta_client_name,
        bs.{client_impl_col},
        bs.propagation_slot_start_diff,
        bs.slot_start_date_time,
        -- Create time buckets for timeline analysis
        toUInt32(bs.propagation_slot_start_diff / {time_bucket_ms}) * {time_bucket_ms} AS time_bucket_ms,
        bs.meta_client_geo_continent_code
      FROM {blob_sidecar_table} bs
      WHERE bs.meta_network_name = %(network)s
        AND bs.slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND bs.slot GLOBAL IN %(eligible_slots)s
        AND bs.propagation_slot_start_diff < %(max_propagation_ms)s
        AND bs.meta_client_name != ''
    )"""


def get_blob_propagation_by_proposer_attester_query(
    data_source: str = "beacon_api",
    proposer_group_by: str = "node_type", 
    attester_group_by: str = "node_type"
) -> str:
    """
    Query for blob propagation analysis grouped by proposer and attester characteristics.
    
    Following the PeerDAS v2 pattern with modular CTEs and proper proposer mapping injection.
    
    Requires inline proposer mapping injected as {{proposer_map_union_selects}}, e.g.,
      SELECT 12345 AS proposer_index, 'supernode' AS node_type, 'lighthouse' AS cl_client, 'geth' AS el_client, 'ARM' AS architecture
      UNION ALL
      SELECT 12346 AS proposer_index, 'regular' AS node_type, 'prysm' AS cl_client, 'nethermind' AS el_client, 'x86' AS architecture
    
    Args:
        data_source: Either 'beacon_api' or 'libp2p'
        proposer_group_by: How to group proposers ('node_type', 'cl_client', 'el_client', etc.)
        attester_group_by: How to group attesters ('node_type', 'cl_client', etc.)
    
    Returns:
        SQL query string with placeholders for proposer mapping
    """
    
    # Table names based on data source  
    if data_source == 'libp2p':
        client_impl_col = 'meta_client_implementation'
    else:
        client_impl_col = 'meta_consensus_implementation'
    
    # Proposer grouping expressions (same as PeerDAS v2)
    proposer_group_expr = {
        'node_type': "coalesce(pm.node_type, 'unknown')",
        'cl_client': "coalesce(pm.cl_client, 'unknown')",
        'el_client': "coalesce(pm.el_client, 'unknown')",
        'architecture': "coalesce(pm.architecture, 'unknown')",
        'operator': "coalesce(pm.operator, 'unknown')",
        'cl_el_combined': "coalesce(concat(pm.cl_client, '-', pm.el_client), 'unknown')",
        'cl_node_type': "coalesce(concat(pm.cl_client, '-', pm.node_type), 'unknown')",
        'cl_architecture': "coalesce(concat(pm.cl_client, '-', pm.architecture), 'unknown')"
    }.get(proposer_group_by, "coalesce(pm.node_type, 'unknown')")
    
    # Attester grouping expressions (using client info from blob sidecar events)
    # Note: For blob events, we only have client implementation info, not full node data
    attester_group_expr = {
        'node_type': f"coalesce(bs.{client_impl_col}, 'unknown')",
        'cl_client': f"coalesce(bs.{client_impl_col}, 'unknown')",
        'el_client': "'unknown'",  # Not available in blob sidecar data
        'architecture': "'unknown'",  # Not available in blob sidecar data
        'operator': "'unknown'",  # Not available in blob sidecar data
        'cl_el_combined': f"coalesce(bs.{client_impl_col}, 'unknown')",
        'cl_node_type': f"coalesce(bs.{client_impl_col}, 'unknown')",
        'cl_architecture': f"coalesce(bs.{client_impl_col}, 'unknown')"
    }.get(attester_group_by, f"coalesce(bs.{client_impl_col}, 'unknown')")
    
    # Build CTEs properly following PeerDAS v2 pattern
    ctes = []
    ctes.append(_get_eligible_slots_cte().strip())
    ctes.append(_get_mev_slots_cte().strip())
    ctes.append(_get_blob_sidecar_events_cte(data_source).strip())
    
    # Add proposer mapping CTE (will be injected by loader)
    proposer_map_cte = """proposer_map AS (
      {{proposer_map_union_selects}}
    ),
    proposer_map_with_operator AS (
      SELECT DISTINCT
        pm.*,
        coalesce(dn.source, 'unknown') AS operator
      FROM proposer_map pm
      LEFT JOIN `{{network}}`.dim_node dn ON pm.proposer_index = dn.validator_index
      {{operator_filter_proposer}}
    )"""
    ctes.append(proposer_map_cte)
    
    cte_string = ",\n    ".join(ctes)
    
    return f"""
    WITH
    {cte_string},
    -- Combine proposer info with blob events
    combined_data AS (
      SELECT 
        es.slot,
        bs.blob_index,
        bs.meta_client_name AS attester_client,
        bs.{client_impl_col} AS attester_implementation,
        {proposer_group_expr} AS proposer_group,
        {attester_group_expr} AS attester_group,
        bs.propagation_slot_start_diff,
        bs.meta_client_geo_continent_code
      FROM eligible_slots es
      LEFT JOIN proposer_map_with_operator pm ON es.proposer_index = pm.proposer_index
      INNER JOIN blob_sidecar_events bs ON es.slot = bs.slot
      CROSS JOIN mev_slots
    )
    -- Final aggregation by proposer and attester groups
    SELECT 
      slot,
      proposer_group,
      attester_group,
      COUNT(DISTINCT blob_index) AS unique_blobs_seen,
      COUNT(DISTINCT attester_client) AS unique_attester_clients,
      COUNT(*) AS total_blob_events,
      AVG(propagation_slot_start_diff) AS avg_propagation_time_ms,
      quantile(0.5)(propagation_slot_start_diff) AS median_propagation_time_ms,
      quantile(0.9)(propagation_slot_start_diff) AS p90_propagation_time_ms,
      quantile(0.95)(propagation_slot_start_diff) AS p95_propagation_time_ms,
      quantile(0.99)(propagation_slot_start_diff) AS p99_propagation_time_ms,
      stddevPop(propagation_slot_start_diff) AS propagation_std_dev,
      COUNT(DISTINCT meta_client_geo_continent_code) AS unique_continents
    FROM combined_data
    GROUP BY 
      slot, 
      proposer_group, 
      attester_group
    ORDER BY 
      slot DESC, 
      proposer_group, 
      attester_group
    """


def get_blob_propagation_timeline_query(
    data_source: str = "beacon_api",
    proposer_group_by: str = "node_type",
    attester_group_by: str = "node_type",
    time_bucket_ms: int = 1000
) -> str:
    """
    Query for blob propagation timeline analysis with time bucketing.
    
    Following the PeerDAS v2 pattern with modular CTEs and proper proposer mapping injection.
    
    Requires inline proposer mapping injected as {{proposer_map_union_selects}}.
    
    Args:
        data_source: Either 'beacon_api' or 'libp2p'
        proposer_group_by: How to group proposers
        attester_group_by: How to group attesters
        time_bucket_ms: Time bucket size in milliseconds
    
    Returns:
        SQL query string with placeholders for proposer mapping
    """
    
    # Table names based on data source  
    if data_source == 'libp2p':
        client_impl_col = 'meta_client_implementation'
    else:
        client_impl_col = 'meta_consensus_implementation'
    
    # Proposer grouping expressions (same as PeerDAS v2)
    proposer_group_expr = {
        'node_type': "coalesce(pm.node_type, 'unknown')",
        'cl_client': "coalesce(pm.cl_client, 'unknown')",
        'el_client': "coalesce(pm.el_client, 'unknown')",
        'architecture': "coalesce(pm.architecture, 'unknown')",
        'operator': "coalesce(pm.operator, 'unknown')",
        'cl_el_combined': "coalesce(concat(pm.cl_client, '-', pm.el_client), 'unknown')",
        'cl_node_type': "coalesce(concat(pm.cl_client, '-', pm.node_type), 'unknown')",
        'cl_architecture': "coalesce(concat(pm.cl_client, '-', pm.architecture), 'unknown')"
    }.get(proposer_group_by, "coalesce(pm.node_type, 'unknown')")
    
    # Attester grouping expressions
    attester_group_expr = {
        'node_type': f"coalesce(bs.{client_impl_col}, 'unknown')",
        'cl_client': f"coalesce(bs.{client_impl_col}, 'unknown')",
        'el_client': "'unknown'",
        'architecture': "'unknown'",
        'operator': "'unknown'",
        'cl_el_combined': f"coalesce(bs.{client_impl_col}, 'unknown')",
        'cl_node_type': f"coalesce(bs.{client_impl_col}, 'unknown')",
        'cl_architecture': f"coalesce(bs.{client_impl_col}, 'unknown')"
    }.get(attester_group_by, f"coalesce(bs.{client_impl_col}, 'unknown')")
    
    # Build CTEs properly following PeerDAS v2 pattern
    ctes = []
    ctes.append(_get_eligible_slots_cte().strip())
    ctes.append(_get_mev_slots_cte().strip())
    ctes.append(_get_blob_sidecar_events_with_time_buckets_cte(data_source, time_bucket_ms).strip())
    
    # Add proposer mapping CTE (will be injected by loader)
    proposer_map_cte = """proposer_map AS (
      {{proposer_map_union_selects}}
    ),
    proposer_map_with_operator AS (
      SELECT DISTINCT
        pm.*,
        coalesce(dn.source, 'unknown') AS operator
      FROM proposer_map pm
      LEFT JOIN `{{network}}`.dim_node dn ON pm.proposer_index = dn.validator_index
      {{operator_filter_proposer}}
    )"""
    ctes.append(proposer_map_cte)
    
    cte_string = ",\n    ".join(ctes)
    
    return f"""
    WITH
    {cte_string},
    -- Combine proposer info with blob events including time buckets
    combined_data AS (
      SELECT 
        es.slot,
        bs.blob_index,
        bs.meta_client_name AS attester_client,
        bs.{client_impl_col} AS attester_implementation,
        {proposer_group_expr} AS proposer_group,
        {attester_group_expr} AS attester_group,
        bs.time_bucket_ms,
        bs.propagation_slot_start_diff,
        bs.meta_client_geo_continent_code
      FROM eligible_slots es
      LEFT JOIN proposer_map_with_operator pm ON es.proposer_index = pm.proposer_index
      INNER JOIN blob_sidecar_events bs ON es.slot = bs.slot
      CROSS JOIN mev_slots
    )
    -- Timeline aggregation by time buckets
    SELECT 
      slot,
      proposer_group,
      attester_group,
      time_bucket_ms,
      COUNT(DISTINCT blob_index) AS unique_blobs_seen,
      COUNT(DISTINCT attester_client) AS unique_attester_clients,
      COUNT(*) AS total_blob_events,
      AVG(propagation_slot_start_diff) AS avg_propagation_time_ms,
      quantile(0.5)(propagation_slot_start_diff) AS median_propagation_time_ms,
      quantile(0.9)(propagation_slot_start_diff) AS p90_propagation_time_ms,
      quantile(0.95)(propagation_slot_start_diff) AS p95_propagation_time_ms,
      COUNT(DISTINCT meta_client_geo_continent_code) AS unique_continents
    FROM combined_data
    GROUP BY 
      slot, 
      proposer_group, 
      attester_group,
      time_bucket_ms
    ORDER BY 
      slot DESC, 
      proposer_group, 
      attester_group,
      time_bucket_ms
    """


# ============================================================================
# SIMPLIFIED QUERIES FOR SPECIFIC USE CASES
# ============================================================================

def get_eligible_slots_for_blob_analysis_query() -> str:
    """
    Get slots where blocks were proposed, for blob propagation analysis.
    
    This returns slots where blocks were actually proposed, which will be used
    to analyze blob sidecar propagation patterns.
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


def build_proposer_filter_for_blob_analysis(proposer_indices: list = None) -> str:
    """
    Build SQL filter clause for proposer eligibility in blob analysis.
    
    Uses the same approach as PeerDAS v2 for consistency.
    
    Args:
        proposer_indices: List of specific proposer indices from network spec
    
    Returns:
        SQL WHERE clause fragment
    """
    if not proposer_indices:
        return ""
    
    sorted_indices = sorted(set(int(idx) for idx in proposer_indices))
    
    # For large sets, use range compression (same as PeerDAS v2)
    if len(sorted_indices) > 200:
        ranges = []
        range_start = sorted_indices[0]
        prev_idx = range_start
        
        for idx in sorted_indices[1:]:
            if idx == prev_idx + 1:
                prev_idx = idx
                continue
            
            ranges.append((range_start, prev_idx))
            range_start = idx
            prev_idx = idx
        
        ranges.append((range_start, prev_idx))
        
        conditions = []
        for start, end in ranges:
            if start == end:
                conditions.append(f"proposer_index = {start}")
            else:
                conditions.append(f"proposer_index BETWEEN {start} AND {end}")
        
        if conditions:
            if len(conditions) == 1:
                clause = conditions[0]
            else:
                clause = '(' + ' OR '.join(conditions) + ')'
            return f"AND {clause}"
    else:
        # For smaller sets, use IN clause
        indices_str = ','.join(str(idx) for idx in sorted_indices)
        return f"AND proposer_index IN ({indices_str})"
    
    return ""


# ============================================================================
# VALIDATOR FILTER FUNCTIONS (COPIED FROM PEERDAS V2)
# ============================================================================

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


def build_validator_filter_ranges(validator_ranges: list = None) -> str:
    """
    Build SQL filter clause for validator filtering using range-based CTE.
    More efficient for large validator sets.
    
    Args:
        validator_ranges: List of tuples (start, end) representing validator ranges
    
    Returns:
        SQL CTE and WHERE clause fragment
    """
    if not validator_ranges:
        return ""

    # Build the range expansion using arrayJoin and arrayConcat
    range_parts = []
    for start, end in validator_ranges:
        range_parts.append(f"range({start}, {end})")

    # If we have many ranges, chunk them to avoid hitting limits
    if len(range_parts) > 100:
        # For very large sets, use UNION ALL approach with chunking
        # Split ranges into chunks of 50 to avoid query size limits
        chunk_size = 50
        chunks = [range_parts[i:i + chunk_size] for i in range(0, len(range_parts), chunk_size)]

        union_parts = []
        for chunk in chunks:
            union_parts.append(f"""
      SELECT arrayJoin(
        arrayConcat(
          {','.join(chunk)}
        )
      ) AS validator_index""")

        cte = f"""valid_validators AS (
      {' UNION ALL '.join(union_parts)}
    )"""
        where_clause = "AND validator_index IN (SELECT validator_index FROM valid_validators)"
    else:
        # Use arrayConcat for smaller sets
        cte = f"""valid_validators AS (
      SELECT arrayJoin(
        arrayConcat(
          {',\n          '.join(range_parts)}
        )
      ) AS validator_index
    )"""
        where_clause = "AND validator_index IN (SELECT validator_index FROM valid_validators)"

    return cte + "|||" + where_clause  # Use ||| as separator
