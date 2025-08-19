"""
ClickHouse queries for Gossipsub Monitoring.
"""


def get_latest_blocks_query() -> str:
    """Get query for fetching the latest beacon blocks with their message IDs."""
    return """
    SELECT 
        slot,
        block,
        message_id,
        meta_client_name,
        propagation_slot_start_diff,
        slot_start_date_time
    FROM libp2p_gossipsub_beacon_block FINAL
    WHERE 
        meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_time)s AND %(end_time)s
        AND propagation_slot_start_diff < %(max_propagation)s
        AND message_id != ''
    ORDER BY slot DESC
    LIMIT %(limit)s
    """


def get_ihave_messages_query() -> str:
    """Get query for fetching IHAVE messages for specific message IDs - simplified version."""
    return """
    SELECT 
        ih.message_id,
        ih.peer_id_unique_key as peer_id,
        ih.meta_client_name as observer_name,
        ih.topic_name,
        ih.event_date_time,
        b.slot,
        b.block
    FROM libp2p_gossipsub_beacon_block b FINAL
    INNER JOIN libp2p_rpc_meta_control_ihave ih 
        ON b.message_id = ih.message_id
    WHERE 
        b.meta_network_name = %(network)s
        AND b.slot_start_date_time BETWEEN %(start_time)s AND %(end_time)s
        AND b.propagation_slot_start_diff < %(max_propagation)s
        AND b.message_id != ''
        AND ih.meta_network_name = %(network)s
        AND ih.event_date_time BETWEEN %(start_time)s AND %(end_time)s
    ORDER BY b.slot DESC
    LIMIT %(slot_limit)s
    """


def get_peer_metadata_query() -> str:
    """Get query for fetching peer metadata from connected table - simplified version."""
    return """
    SELECT DISTINCT
        c.remote_peer_id_unique_key as peer_id,
        c.remote_agent_version as agent_version,
        c.remote_protocol as protocol_version,
        c.meta_client_name,
        c.remote_geo_continent_code as continent,
        c.remote_geo_country as country,
        c.remote_geo_city as city,
        c.direction,
        c.opened
    FROM libp2p_connected c
    WHERE 
        c.meta_network_name = %(network)s
        AND c.event_date_time BETWEEN %(start_time)s AND %(end_time)s
    """


def get_blocks_in_range_query() -> str:
    """Get unique blocks in a time range (one per slot)."""
    return """
    WITH filtered_blocks AS (
        SELECT 
            slot,
            block,
            message_id,
            propagation_slot_start_diff,
            slot_start_date_time
        FROM libp2p_gossipsub_beacon_block FINAL
        WHERE 
            meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_time)s AND %(end_time)s
            AND propagation_slot_start_diff < %(max_propagation)s
            AND message_id != ''
    )
    SELECT 
        slot,
        any(block) as block,
        any(message_id) as message_id,
        MIN(propagation_slot_start_diff) as propagation_slot_start_diff,
        any(slot_start_date_time) as slot_start_date_time
    FROM filtered_blocks
    GROUP BY slot
    ORDER BY slot DESC
    LIMIT %(limit)s
    """


def get_ihave_for_messages_batch_query() -> str:
    """Get IHAVE messages for a list of message_ids."""
    return """
    SELECT 
        message_id,
        peer_id_unique_key,
        MIN(event_date_time) as ihave_time,
        any(meta_client_name) as ihave_observer
    FROM libp2p_rpc_meta_control_ihave
    WHERE 
        meta_network_name = %(network)s
        AND event_date_time BETWEEN %(start_time)s AND %(end_time)s
        AND message_id IN %(message_ids)s
    GROUP BY message_id, peer_id_unique_key
    """


def get_peer_metadata_batch_query() -> str:
    """Get peer metadata for a list of peer_ids."""
    return """
    SELECT DISTINCT
        remote_peer_id_unique_key as peer_id,
        remote_agent_version as agent_version,
        remote_geo_continent_code as continent,
        remote_geo_country as country,
        remote_geo_city as city
    FROM libp2p_connected
    WHERE 
        meta_network_name = %(network)s
        AND event_date_time BETWEEN %(start_time)s AND %(end_time)s
        AND remote_peer_id_unique_key IN %(peer_ids)s
    """


def get_slot_based_analysis_query() -> str:
    """Get query for per-slot analysis with continental breakdown - simplified version."""
    # This query will be executed in two steps in the data loader
    return """
    SELECT 
        slot,
        block,
        message_id,
        meta_client_name,
        propagation_slot_start_diff,
        slot_start_date_time
    FROM libp2p_gossipsub_beacon_block FINAL
    WHERE 
        meta_network_name = %(network)s
        AND slot = %(target_slot)s
        AND propagation_slot_start_diff < %(max_propagation)s
        AND message_id != ''
    LIMIT 1
    """


def get_single_slot_complete_query() -> str:
    """Get complete gossipsub data for a single slot - all in one query."""
    return """
    WITH block_data AS (
        SELECT 
            slot,
            any(block) as block,
            any(message_id) as message_id,
            MIN(slot_start_date_time) as slot_start_date_time,
            MIN(propagation_slot_start_diff) as propagation_slot_start_diff
        FROM libp2p_gossipsub_beacon_block
        WHERE 
            meta_network_name = %(network)s
            AND slot = %(slot)s
            AND message_id != ''
        GROUP BY slot
        LIMIT 1
    ),
    ihave_data AS (
        SELECT 
            i.peer_id_unique_key,
            MIN(i.event_date_time) as ihave_time
        FROM libp2p_rpc_meta_control_ihave i
        WHERE 
            i.meta_network_name = %(network)s
            AND i.message_id IN (SELECT message_id FROM block_data)
            AND i.event_date_time BETWEEN %(ihave_start_time)s AND %(ihave_end_time)s
        GROUP BY i.peer_id_unique_key
    ),
    peer_data AS (
        SELECT DISTINCT
            remote_peer_id_unique_key as peer_id,
            any(remote_geo_continent_code) as continent,
            any(remote_geo_country) as country
        FROM libp2p_connected
        WHERE 
            meta_network_name = %(network)s
            AND remote_peer_id_unique_key IN (SELECT peer_id_unique_key FROM ihave_data)
            AND event_date_time BETWEEN %(peer_start_time)s AND %(peer_end_time)s
        GROUP BY remote_peer_id_unique_key
    )
    SELECT 
        b.slot,
        b.block,
        b.message_id,
        b.slot_start_date_time,
        b.propagation_slot_start_diff as block_propagation_time,
        i.peer_id_unique_key as peer_id,
        i.ihave_time,
        toInt64((i.ihave_time - b.slot_start_date_time) * 1000) as propagation_delay_ms,
        COALESCE(p.continent, 'Unknown') as continent,
        COALESCE(p.country, 'Unknown') as country
    FROM block_data b
    CROSS JOIN ihave_data i
    LEFT JOIN peer_data p ON i.peer_id_unique_key = p.peer_id
    WHERE propagation_delay_ms > -1000 AND propagation_delay_ms < 180000
    """


def get_combined_gossipsub_query() -> str:
    """Get combined gossipsub data in a single query."""
    return """
    WITH filtered_blocks AS (
        SELECT 
            slot,
            block,
            message_id,
            slot_start_date_time
        FROM libp2p_gossipsub_beacon_block FINAL
        WHERE 
            meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_time)s AND %(end_time)s
            AND message_id != ''
    ),
    blocks AS (
        SELECT 
            slot,
            any(block) as block,
            any(message_id) as message_id,
            any(slot_start_date_time) as slot_start_date_time
        FROM filtered_blocks
        GROUP BY slot
        ORDER BY slot DESC
        LIMIT %(limit)s
    ),
    ihaves AS (
        SELECT 
            message_id,
            peer_id_unique_key,
            MIN(event_date_time) as ihave_time
        FROM libp2p_rpc_meta_control_ihave
        WHERE 
            meta_network_name = %(network)s
            AND event_date_time BETWEEN %(ihave_start_time)s AND %(ihave_end_time)s
            AND message_id IN (SELECT message_id FROM blocks)
        GROUP BY message_id, peer_id_unique_key
    )
    SELECT 
        b.slot,
        b.block,
        b.message_id,
        b.slot_start_date_time,
        i.peer_id_unique_key as peer_id,
        i.ihave_time,
        toInt64((i.ihave_time - b.slot_start_date_time) * 1000) as propagation_delay_ms
    FROM blocks b
    INNER JOIN ihaves i ON b.message_id = i.message_id
    WHERE propagation_delay_ms > -1000 AND propagation_delay_ms < 180000
    """