"""
ClickHouse queries for PeerDAS analysis.

These queries perform the correct aggregation on the database side:
1. Per-client, per-slot: Calculate when each client has data available
2. Then aggregate by chosen metric (blob count or custody count)
"""

def get_blob_count_query(data_source: str, aggregation: str = "p90", client_filter: list = None) -> str:
    """
    Query for PeerDAS metrics grouped by blob count.
    
    Args:
        data_source: Either 'libp2p' or 'beacon_api'
        aggregation: Aggregation function ('mean', 'p50', 'p90', 'p95', 'p99')
        client_filter: Optional list of client names to include
    
    Returns:
        SQL query string
    """
    
    # Map aggregation to ClickHouse function
    agg_funcs = {
        'mean': 'avg(data_available_time)',
        'p50': 'quantile(0.5)(data_available_time)',
        'p90': 'quantile(0.9)(data_available_time)',
        'p95': 'quantile(0.95)(data_available_time)',
        'p99': 'quantile(0.99)(data_available_time)'
    }
    agg_expr = agg_funcs.get(aggregation, 'quantile(0.9)(data_available_time)')
    
    # Table names based on data source
    if data_source == 'libp2p':
        block_table = 'libp2p_gossipsub_beacon_block FINAL'
        sidecar_table = 'libp2p_gossipsub_data_column_sidecar FINAL'
        blob_count_expr = 'kzg_commitments_count'
    else:
        block_table = 'beacon_api_eth_v1_events_block'
        sidecar_table = 'beacon_api_eth_v1_events_data_column_sidecar'
        blob_count_expr = 'kzg_commitments_count'
    
    # Build client filter clause
    client_filter_clause = ""
    if client_filter:
        client_filter_clause = "AND meta_client_name IN %(client_filter)s"
    
    query = f"""
    WITH 
    -- Step 1: Per-client, per-slot sidecar times
    client_slot_sidecars AS (
        SELECT 
            slot,
            meta_client_name,
            any({blob_count_expr}) as blob_count,
            MAX(propagation_slot_start_diff) as max_column_time
        FROM {sidecar_table}
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND propagation_slot_start_diff < %(max_propagation)s
            AND meta_client_name != ''
            AND column_index < %(custody_filter)s
            {client_filter_clause}
        GROUP BY slot, meta_client_name
    ),
    -- Step 2: Per-client, per-slot block times
    client_slot_blocks AS (
        SELECT 
            slot,
            meta_client_name,
            MIN(propagation_slot_start_diff) as block_time
        FROM {block_table}
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND propagation_slot_start_diff < %(max_propagation)s
            AND meta_client_name != ''
            {client_filter_clause}
        GROUP BY slot, meta_client_name
    ),
    -- Step 3: Combine block and sidecar times
    client_slot_availability AS (
        SELECT 
            s.slot,
            s.meta_client_name,
            s.blob_count,
            greatest(
                COALESCE(b.block_time, 0),
                s.max_column_time
            ) as data_available_time
        FROM client_slot_sidecars s
        LEFT JOIN client_slot_blocks b 
            ON s.slot = b.slot AND s.meta_client_name = b.meta_client_name
    )
    -- Step 4: Final aggregation by blob count
    SELECT 
        blob_count,
        {agg_expr} as aggregated_time,
        COUNT(*) as sample_count,
        COUNT(DISTINCT meta_client_name) as unique_clients,
        stddevPop(data_available_time) as std_dev
    FROM client_slot_availability
    GROUP BY blob_count
    ORDER BY blob_count
    """
    
    return query


def get_custody_count_query(data_source: str, aggregation: str = "p90", client_filter: list = None) -> str:
    """
    Query for PeerDAS metrics grouped by custody count.
    
    Args:
        data_source: Either 'libp2p' or 'beacon_api'
        aggregation: Aggregation function ('mean', 'p50', 'p90', 'p95', 'p99')
        client_filter: Optional list of client names to include
    
    Returns:
        SQL query string
    """
    
    # Map aggregation to ClickHouse function
    agg_funcs = {
        'mean': 'avg(data_available_time)',
        'p50': 'quantile(0.5)(data_available_time)',
        'p90': 'quantile(0.9)(data_available_time)',
        'p95': 'quantile(0.95)(data_available_time)',
        'p99': 'quantile(0.99)(data_available_time)'
    }
    agg_expr = agg_funcs.get(aggregation, 'quantile(0.9)(data_available_time)')
    
    # Table names based on data source
    if data_source == 'libp2p':
        block_table = 'libp2p_gossipsub_beacon_block FINAL'
        sidecar_table = 'libp2p_gossipsub_data_column_sidecar FINAL'
        blob_count_expr = 'kzg_commitments_count'
    else:
        block_table = 'beacon_api_eth_v1_events_block'
        sidecar_table = 'beacon_api_eth_v1_events_data_column_sidecar'
        blob_count_expr = 'kzg_commitments_count'
    
    # Build client filter clause
    client_filter_clause = ""
    if client_filter:
        client_filter_clause = "AND meta_client_name IN %(client_filter)s"
    
    query = f"""
    WITH 
    -- Step 1: Get all sidecar data we need
    sidecar_data AS (
        SELECT 
            slot,
            meta_client_name,
            column_index,
            {blob_count_expr} as blob_count,
            propagation_slot_start_diff,
            slot_start_date_time
        FROM {sidecar_table}
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND propagation_slot_start_diff < %(max_propagation)s
            AND meta_client_name != ''
            {client_filter_clause}
    ),
    -- Step 2: Calculate max columns per client across all slots
    client_custody AS (
        SELECT 
            meta_client_name,
            COUNT(DISTINCT column_index) as custody_count
        FROM sidecar_data
        GROUP BY meta_client_name
    ),
    -- Step 3: Per-client, per-slot sidecar times with custody from above
    client_slot_sidecars AS (
        SELECT 
            s.slot,
            s.meta_client_name,
            any(s.blob_count) as blob_count,
            any(cc.custody_count) as custody_count,
            MAX(s.propagation_slot_start_diff) as max_column_time
        FROM sidecar_data s
        INNER JOIN client_custody cc ON s.meta_client_name = cc.meta_client_name
        GROUP BY s.slot, s.meta_client_name
    ),
    -- Step 4: Per-client, per-slot block times
    client_slot_blocks AS (
        SELECT 
            slot,
            meta_client_name,
            MIN(propagation_slot_start_diff) as block_time
        FROM {block_table}
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND propagation_slot_start_diff < %(max_propagation)s
            AND meta_client_name != ''
            {client_filter_clause}
        GROUP BY slot, meta_client_name
    ),
    -- Step 5: Combine block and sidecar times
    client_slot_availability AS (
        SELECT 
            s.slot,
            s.meta_client_name,
            s.blob_count,
            s.custody_count,
            greatest(
                COALESCE(b.block_time, 0),
                s.max_column_time
            ) as data_available_time
        FROM client_slot_sidecars s
        LEFT JOIN client_slot_blocks b 
            ON s.slot = b.slot AND s.meta_client_name = b.meta_client_name
    )
    -- Step 6: Final aggregation by custody count
    SELECT 
        custody_count,
        {agg_expr} as aggregated_time,
        COUNT(*) as sample_count,
        COUNT(DISTINCT meta_client_name) as unique_clients,
        stddevPop(data_available_time) as std_dev
    FROM client_slot_availability
    GROUP BY custody_count
    ORDER BY custody_count
    """
    
    return query


def get_peerdas_query(data_source: str, aggregation: str = "p90", group_by: str = "blob_count", client_filter: list = None) -> str:
    """
    Get THE query for PeerDAS metrics with proper aggregation.
    
    This is the ONLY correct way to calculate PeerDAS metrics:
    - Phase 1: Calculate per-client, per-slot data availability time
    - Phase 2: Aggregate those times by chosen metric
    
    Args:
        data_source: Either 'libp2p' or 'beacon_api'
        aggregation: Aggregation function ('mean', 'p50', 'p90', 'p95', 'p99')
        group_by: Metric to group by ('blob_count' or 'custody_count')
        client_filter: Optional list of client names to include
        
    Returns:
        SQL query string
    """
    
    if group_by == 'custody_count':
        return get_custody_count_query(data_source, aggregation, client_filter)
    else:
        return get_blob_count_query(data_source, aggregation, client_filter)


def get_node_classification_raw_query(data_source: str, client_filter: list = None) -> str:
    """
    Query for raw PeerDAS data with node classification for box plots.
    
    Returns per-client, per-slot data with custody count classification.
    
    Args:
        data_source: Either 'libp2p' or 'beacon_api'
        client_filter: Optional list of client names to include
    
    Returns:
        SQL query string
    """
    
    # Table names and columns based on data source
    if data_source == 'libp2p':
        block_table = 'libp2p_gossipsub_beacon_block FINAL'
        sidecar_table = 'libp2p_gossipsub_data_column_sidecar FINAL'
        blob_count_expr = 'kzg_commitments_count'
        consensus_impl_col = 'meta_client_implementation'
    else:
        block_table = 'beacon_api_eth_v1_events_block'
        sidecar_table = 'beacon_api_eth_v1_events_data_column_sidecar'
        blob_count_expr = 'kzg_commitments_count'
        consensus_impl_col = 'meta_consensus_implementation'
    
    # Build client filter clause
    client_filter_clause = ""
    if client_filter:
        client_filter_clause = "AND meta_client_name IN %(client_filter)s"
    
    query = f"""
    WITH 
    -- Step 1: Get all sidecar data we need
    sidecar_data AS (
        SELECT 
            slot,
            meta_client_name,
            column_index,
            {blob_count_expr} as blob_count,
            propagation_slot_start_diff,
            slot_start_date_time,
            {consensus_impl_col} as consensus_implementation
        FROM {sidecar_table}
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND propagation_slot_start_diff < %(max_propagation)s
            AND meta_client_name != ''
            {client_filter_clause}
    ),
    -- Step 2: Calculate max columns per client across all slots
    client_custody AS (
        SELECT 
            meta_client_name,
            COUNT(DISTINCT column_index) as custody_count
        FROM sidecar_data
        GROUP BY meta_client_name
    ),
    -- Step 3: Per-client, per-slot sidecar times with custody from above
    client_slot_sidecars AS (
        SELECT 
            s.slot,
            s.meta_client_name,
            any(s.blob_count) as blob_count,
            any(cc.custody_count) as custody_count,
            any(s.consensus_implementation) as consensus_implementation,
            MAX(s.propagation_slot_start_diff) as max_column_time
        FROM sidecar_data s
        INNER JOIN client_custody cc ON s.meta_client_name = cc.meta_client_name
        GROUP BY s.slot, s.meta_client_name
    ),
    -- Step 4: Per-client, per-slot block times
    client_slot_blocks AS (
        SELECT 
            slot,
            meta_client_name,
            MIN(propagation_slot_start_diff) as block_time
        FROM {block_table}
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND propagation_slot_start_diff < %(max_propagation)s
            AND meta_client_name != ''
            {client_filter_clause}
        GROUP BY slot, meta_client_name
    ),
    -- Step 5: Combine block and sidecar times with node classification
    client_slot_availability AS (
        SELECT 
            s.slot,
            s.meta_client_name,
            s.blob_count,
            s.custody_count,
            s.consensus_implementation,
            CASE 
                WHEN s.custody_count = 8 THEN 'non-validating'
                WHEN s.custody_count >= 128 THEN 'supernode'
                ELSE 'validating-standard'
            END as node_class,
            greatest(
                COALESCE(b.block_time, 0),
                s.max_column_time
            ) as data_available_time
        FROM client_slot_sidecars s
        LEFT JOIN client_slot_blocks b 
            ON s.slot = b.slot AND s.meta_client_name = b.meta_client_name
    )
    -- Step 6: Return raw data with classification
    SELECT 
        blob_count,
        node_class,
        custody_count,
        data_available_time,
        meta_client_name,
        consensus_implementation
    FROM client_slot_availability
    WHERE custody_count <= %(custody_filter)s
    ORDER BY blob_count, node_class, data_available_time
    """
    
    return query


def get_max_blob_count_query(data_source: str) -> str:
    """
    Quick query to get the maximum blob count in the dataset.
    
    Args:
        data_source: Either 'libp2p' or 'beacon_api'
    
    Returns:
        SQL query string
    """
    
    # Table names based on data source
    if data_source == 'libp2p':
        sidecar_table = 'libp2p_gossipsub_data_column_sidecar FINAL'
        blob_count_expr = 'kzg_commitments_count'
    else:
        sidecar_table = 'beacon_api_eth_v1_events_data_column_sidecar'
        blob_count_expr = 'kzg_commitments_count'
    
    query = f"""
    SELECT 
        MAX({blob_count_expr}) as max_blob_count
    FROM {sidecar_table}
    WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND meta_client_name != ''
    """
    
    return query


def get_unique_clients_query(data_source: str) -> str:
    """
    Query to get unique client names from the dataset.
    
    Args:
        data_source: Either 'libp2p' or 'beacon_api'
    
    Returns:
        SQL query string
    """
    
    # Use the appropriate table based on data source
    if data_source == 'libp2p':
        table = 'libp2p_gossipsub_data_column_sidecar FINAL'
    else:
        table = 'beacon_api_eth_v1_events_data_column_sidecar'
    
    query = f"""
    SELECT DISTINCT meta_client_name
    FROM {table}
    WHERE meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        AND meta_client_name != ''
    ORDER BY meta_client_name
    """
    
    return query