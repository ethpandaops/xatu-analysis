"""
ClickHouse queries for Gossipsub Monitoring - Reverse lookup approach.
Start from IHAVE messages and work backwards to find slots.
"""


def get_ihave_based_slots_query() -> str:
    """
    Get slots based on available IHAVE beacon_block messages.
    This works backwards from the data we actually have.
    """
    return """
    WITH ihave_windows AS (
        -- Get distinct time windows where we have beacon_block IHAVE messages
        -- Round to 12-second slot boundaries
        SELECT 
            toUInt32(toUnixTimestamp(event_date_time) / 12) * 12 as slot_timestamp,
            toDateTime(toUInt32(toUnixTimestamp(event_date_time) / 12) * 12) as slot_time,
            COUNT(DISTINCT peer_id_unique_key) as peer_count
        FROM libp2p_rpc_meta_control_ihave
        WHERE 
            meta_network_name = %(network)s
            AND topic_name = 'beacon_block'
            AND event_date_time BETWEEN %(start_time)s AND %(end_time)s
        GROUP BY slot_timestamp, slot_time
        HAVING peer_count >= 10  -- Only include slots with meaningful data
    )
    SELECT 
        -- Calculate slot number from timestamp (using Ethereum mainnet genesis)
        toUInt64((slot_timestamp - 1606824023) / 12) as slot,
        slot_time,
        peer_count
    FROM ihave_windows
    ORDER BY slot DESC
    LIMIT %(limit)s
    """


def get_ihave_data_for_slot_time() -> str:
    """
    Get all IHAVE data for a specific slot time.
    This assumes we already know the slot exists in IHAVE data.
    """
    return """
    WITH ihave_raw AS (
        SELECT 
            peer_id_unique_key,
            meta_client_name,
            event_date_time,
            toInt64((event_date_time - toDateTime(%(slot_time)s)) * 1000) as delay_ms
        FROM libp2p_rpc_meta_control_ihave
        WHERE 
            meta_network_name = %(network)s
            AND topic_name = 'beacon_block'
            -- Look for IHAVE messages around this slot time
            AND event_date_time BETWEEN toDateTime(%(slot_time)s) - INTERVAL 2 SECOND 
                AND toDateTime(%(slot_time)s) + INTERVAL 20 SECOND
            AND toInt64((event_date_time - toDateTime(%(slot_time)s)) * 1000) BETWEEN -2000 AND 20000
    ),
    -- Get first observer for each peer
    first_observer AS (
        SELECT 
            peer_id_unique_key,
            argMin(meta_client_name, delay_ms) as first_meta_client,
            MIN(delay_ms) as min_propagation_delay_ms,
            argMin(event_date_time, delay_ms) as first_ihave_time
        FROM ihave_raw
        GROUP BY peer_id_unique_key
    ),
    -- Get closest heartbeat for latency data
    heartbeat_with_latency AS (
        SELECT 
            ih.peer_id_unique_key,
            ih.first_meta_client,
            ih.min_propagation_delay_ms as propagation_delay_ms,
            ih.first_ihave_time,
            argMin(hb.latency_ms, ABS(toInt64((hb.event_date_time - ih.first_ihave_time) * 1000))) as closest_rtt_ms
        FROM first_observer ih
        LEFT JOIN libp2p_synthetic_heartbeat hb 
            ON ih.peer_id_unique_key = hb.remote_peer_id_unique_key
            AND ih.first_meta_client = hb.meta_client_name
            AND hb.event_date_time BETWEEN ih.first_ihave_time - INTERVAL 10 MINUTE 
                AND ih.first_ihave_time + INTERVAL 2 MINUTE
        WHERE hb.meta_network_name = %(network)s OR hb.meta_network_name IS NULL
        GROUP BY ih.peer_id_unique_key, ih.first_meta_client, ih.min_propagation_delay_ms, ih.first_ihave_time
    ),
    -- Get latest geo data for each peer from heartbeat table
    geo_data AS (
        SELECT 
            remote_peer_id_unique_key,
            argMax(remote_geo_continent_code, event_date_time) as continent,
            argMax(remote_geo_country, event_date_time) as country,
            argMax(remote_geo_latitude, event_date_time) as latitude,
            argMax(remote_geo_longitude, event_date_time) as longitude
        FROM libp2p_synthetic_heartbeat
        WHERE 
            meta_network_name = %(network)s
            AND event_date_time <= toDateTime(%(slot_time)s) + INTERVAL 30 SECOND
            AND event_date_time >= toDateTime(%(slot_time)s) - INTERVAL 5 MINUTE
        GROUP BY remote_peer_id_unique_key
    )
    SELECT 
        %(slot)s as slot,
        '' as block,
        toDateTime(%(slot_time)s) as slot_start_date_time,
        0 as block_propagation_time,
        hl.peer_id_unique_key as peer_id,
        hl.first_meta_client,
        toDateTime(%(slot_time)s) + INTERVAL hl.propagation_delay_ms MILLISECOND as ihave_time,
        hl.propagation_delay_ms,
        hl.closest_rtt_ms as rtt_ms,
        hl.closest_rtt_ms / 2 as one_way_latency_ms,
        hl.propagation_delay_ms - (hl.closest_rtt_ms / 2) as adjusted_propagation_ms,
        COALESCE(geo.continent, 'Unknown') as continent,
        COALESCE(geo.country, 'Unknown') as country
    FROM heartbeat_with_latency hl
    LEFT JOIN geo_data geo ON hl.peer_id_unique_key = geo.remote_peer_id_unique_key
    """


def get_idontwant_data_for_slot_time() -> str:
    """
    Get all IDONTWANT data for a specific slot time.
    Since IDONTWANT doesn't have topic_name, we work with timing.
    """
    return """
    WITH idontwant_raw AS (
        SELECT 
            peer_id_unique_key,
            meta_client_name,
            event_date_time,
            toInt64((event_date_time - toDateTime(%(slot_time)s)) * 1000) as delay_ms
        FROM libp2p_rpc_meta_control_idontwant
        WHERE 
            meta_network_name = %(network)s
            -- Look for IDONTWANT messages around this slot time
            AND event_date_time BETWEEN toDateTime(%(slot_time)s) - INTERVAL 2 SECOND 
                AND toDateTime(%(slot_time)s) + INTERVAL 20 SECOND
            AND message_id != ''
            AND toInt64((event_date_time - toDateTime(%(slot_time)s)) * 1000) BETWEEN -2000 AND 20000
    ),
    -- Get first observer for each peer
    first_observer AS (
        SELECT 
            peer_id_unique_key,
            argMin(meta_client_name, delay_ms) as first_meta_client,
            MIN(delay_ms) as min_propagation_delay_ms,
            argMin(event_date_time, delay_ms) as first_idontwant_time
        FROM idontwant_raw
        GROUP BY peer_id_unique_key
    ),
    -- Get closest heartbeat for latency data
    heartbeat_with_latency AS (
        SELECT 
            idw.peer_id_unique_key,
            idw.first_meta_client,
            idw.min_propagation_delay_ms as propagation_delay_ms,
            idw.first_idontwant_time,
            argMin(hb.latency_ms, ABS(toInt64((hb.event_date_time - idw.first_idontwant_time) * 1000))) as closest_rtt_ms
        FROM first_observer idw
        LEFT JOIN libp2p_synthetic_heartbeat hb 
            ON idw.peer_id_unique_key = hb.remote_peer_id_unique_key
            AND idw.first_meta_client = hb.meta_client_name
            AND hb.event_date_time BETWEEN idw.first_idontwant_time - INTERVAL 10 MINUTE 
                AND idw.first_idontwant_time + INTERVAL 2 MINUTE
        WHERE hb.meta_network_name = %(network)s OR hb.meta_network_name IS NULL
        GROUP BY idw.peer_id_unique_key, idw.first_meta_client, idw.min_propagation_delay_ms, idw.first_idontwant_time
    ),
    -- Get latest geo data for each peer from heartbeat table
    geo_data AS (
        SELECT 
            remote_peer_id_unique_key,
            argMax(remote_geo_continent_code, event_date_time) as continent,
            argMax(remote_geo_country, event_date_time) as country,
            argMax(remote_geo_latitude, event_date_time) as latitude,
            argMax(remote_geo_longitude, event_date_time) as longitude
        FROM libp2p_synthetic_heartbeat
        WHERE 
            meta_network_name = %(network)s
            AND event_date_time <= toDateTime(%(slot_time)s) + INTERVAL 30 SECOND
            AND event_date_time >= toDateTime(%(slot_time)s) - INTERVAL 5 MINUTE
        GROUP BY remote_peer_id_unique_key
    )
    SELECT 
        %(slot)s as slot,
        '' as block,
        toDateTime(%(slot_time)s) as slot_start_date_time,
        0 as block_propagation_time,
        hl.peer_id_unique_key as peer_id,
        hl.first_meta_client,
        toDateTime(%(slot_time)s) + INTERVAL hl.propagation_delay_ms MILLISECOND as idontwant_time,
        hl.propagation_delay_ms,
        hl.closest_rtt_ms as rtt_ms,
        hl.closest_rtt_ms / 2 as one_way_latency_ms,
        hl.propagation_delay_ms - (hl.closest_rtt_ms / 2) as adjusted_propagation_ms,
        COALESCE(geo.continent, 'Unknown') as continent,
        COALESCE(geo.country, 'Unknown') as country
    FROM heartbeat_with_latency hl
    LEFT JOIN geo_data geo ON hl.peer_id_unique_key = geo.remote_peer_id_unique_key
    """


def get_latest_ihave_slot() -> str:
    """
    Get the latest slot that has IHAVE beacon_block data.
    """
    return """
    WITH latest_ihave AS (
        SELECT 
            MAX(event_date_time) as max_time,
            toUInt32(toUnixTimestamp(MAX(event_date_time)) / 12) * 12 as slot_timestamp
        FROM libp2p_rpc_meta_control_ihave
        WHERE 
            meta_network_name = %(network)s
            AND topic_name = 'beacon_block'
            AND event_date_time <= now() - INTERVAL 5 MINUTE  -- Account for any delay
    )
    SELECT 
        toUInt64((slot_timestamp - 1606824023) / 12) as slot,
        toDateTime(slot_timestamp) as slot_time
    FROM latest_ihave
    """


def get_all_ihave_data_in_range() -> str:
    """
    Get all IHAVE data grouped by slot time windows.
    This is the most efficient approach for time ranges.
    """
    return """
    WITH slot_data AS (
        -- Calculate slot for each IHAVE message
        SELECT 
            peer_id_unique_key,
            meta_client_name,
            event_date_time,
            toUInt32(toUnixTimestamp(event_date_time) / 12) * 12 as slot_timestamp,
            toUInt64((toUInt32(toUnixTimestamp(event_date_time) / 12) * 12 - 1606824023) / 12) as slot,
            toInt64((event_date_time - toDateTime(toUInt32(toUnixTimestamp(event_date_time) / 12) * 12)) * 1000) as delay_ms
        FROM libp2p_rpc_meta_control_ihave
        WHERE 
            meta_network_name = %(network)s
            AND topic_name = 'beacon_block'
            AND event_date_time BETWEEN %(start_time)s AND %(end_time)s
            AND toInt64((event_date_time - toDateTime(toUInt32(toUnixTimestamp(event_date_time) / 12) * 12)) * 1000) BETWEEN -2000 AND 20000
    ),
    -- Get first observer for each peer/slot
    first_observer AS (
        SELECT 
            slot,
            toDateTime(slot_timestamp) as slot_start_date_time,
            peer_id_unique_key as peer_id,
            argMin(meta_client_name, delay_ms) as first_meta_client,
            argMin(event_date_time, delay_ms) as ihave_time,
            MIN(delay_ms) as propagation_delay_ms
        FROM slot_data
        GROUP BY slot, slot_timestamp, peer_id_unique_key
    ),
    -- Get closest heartbeat for latency data
    with_latency AS (
        SELECT 
            fo.slot,
            fo.slot_start_date_time,
            fo.peer_id,
            fo.first_meta_client,
            fo.ihave_time,
            fo.propagation_delay_ms,
            argMin(hb.latency_ms, ABS(toInt64((hb.event_date_time - fo.ihave_time) * 1000))) as closest_rtt_ms
        FROM first_observer fo
        LEFT JOIN libp2p_synthetic_heartbeat hb 
            ON fo.peer_id = hb.remote_peer_id_unique_key
            AND fo.first_meta_client = hb.meta_client_name
            AND hb.event_date_time BETWEEN fo.ihave_time - INTERVAL 10 MINUTE 
                AND fo.ihave_time + INTERVAL 2 MINUTE
            AND hb.meta_network_name = %(network)s
        GROUP BY fo.slot, fo.slot_start_date_time, fo.peer_id, fo.first_meta_client, fo.ihave_time, fo.propagation_delay_ms
    ),
    -- Get latest geo data for each peer from heartbeat table
    geo_data AS (
        SELECT 
            remote_peer_id_unique_key,
            argMax(remote_geo_continent_code, event_date_time) as continent,
            argMax(remote_geo_country, event_date_time) as country,
            argMax(remote_geo_latitude, event_date_time) as latitude,
            argMax(remote_geo_longitude, event_date_time) as longitude
        FROM libp2p_synthetic_heartbeat
        WHERE 
            meta_network_name = %(network)s
            AND event_date_time BETWEEN %(start_time)s - INTERVAL 5 MINUTE AND %(end_time)s + INTERVAL 30 SECOND
        GROUP BY remote_peer_id_unique_key
    )
    SELECT 
        wl.slot,
        '' as block,
        wl.slot_start_date_time,
        0 as block_propagation_time,
        wl.peer_id,
        wl.first_meta_client,
        wl.ihave_time,
        wl.propagation_delay_ms,
        wl.closest_rtt_ms as rtt_ms,
        wl.closest_rtt_ms / 2 as one_way_latency_ms,
        wl.propagation_delay_ms - (wl.closest_rtt_ms / 2) as adjusted_propagation_ms,
        COALESCE(geo.continent, 'Unknown') as continent,
        COALESCE(geo.country, 'Unknown') as country
    FROM with_latency wl
    LEFT JOIN geo_data geo ON wl.peer_id = geo.remote_peer_id_unique_key
    ORDER BY wl.slot DESC, wl.propagation_delay_ms ASC
    """


def get_all_idontwant_data_in_range() -> str:
    """
    Get all IDONTWANT data grouped by slot time windows.
    Since IDONTWANT doesn't have topic_name, we work with timing and message_ids.
    """
    return """
    WITH slot_data AS (
        -- Calculate slot for each IDONTWANT message based on timing
        SELECT 
            peer_id_unique_key,
            meta_client_name,
            event_date_time,
            message_id,
            toUInt32(toUnixTimestamp(event_date_time) / 12) * 12 as slot_timestamp,
            toUInt64((toUInt32(toUnixTimestamp(event_date_time) / 12) * 12 - 1606824023) / 12) as slot,
            toInt64((event_date_time - toDateTime(toUInt32(toUnixTimestamp(event_date_time) / 12) * 12)) * 1000) as delay_ms
        FROM libp2p_rpc_meta_control_idontwant
        WHERE 
            meta_network_name = %(network)s
            AND event_date_time BETWEEN %(start_time)s AND %(end_time)s
            AND message_id != ''
            AND toInt64((event_date_time - toDateTime(toUInt32(toUnixTimestamp(event_date_time) / 12) * 12)) * 1000) BETWEEN -2000 AND 20000
    ),
    -- Get first observer for each peer/slot
    first_observer AS (
        SELECT 
            slot,
            toDateTime(slot_timestamp) as slot_start_date_time,
            peer_id_unique_key as peer_id,
            argMin(meta_client_name, delay_ms) as first_meta_client,
            argMin(event_date_time, delay_ms) as idontwant_time,
            MIN(delay_ms) as propagation_delay_ms
        FROM slot_data
        GROUP BY slot, slot_timestamp, peer_id_unique_key
    ),
    -- Get closest heartbeat for latency data
    with_latency AS (
        SELECT 
            fo.slot,
            fo.slot_start_date_time,
            fo.peer_id,
            fo.first_meta_client,
            fo.idontwant_time,
            fo.propagation_delay_ms,
            argMin(hb.latency_ms, ABS(toInt64((hb.event_date_time - fo.idontwant_time) * 1000))) as closest_rtt_ms
        FROM first_observer fo
        LEFT JOIN libp2p_synthetic_heartbeat hb 
            ON fo.peer_id = hb.remote_peer_id_unique_key
            AND fo.first_meta_client = hb.meta_client_name
            AND hb.event_date_time BETWEEN fo.idontwant_time - INTERVAL 10 MINUTE 
                AND fo.idontwant_time + INTERVAL 2 MINUTE
            AND hb.meta_network_name = %(network)s
        GROUP BY fo.slot, fo.slot_start_date_time, fo.peer_id, fo.first_meta_client, fo.idontwant_time, fo.propagation_delay_ms
    ),
    -- Get latest geo data for each peer from heartbeat table
    geo_data AS (
        SELECT 
            remote_peer_id_unique_key,
            argMax(remote_geo_continent_code, event_date_time) as continent,
            argMax(remote_geo_country, event_date_time) as country,
            argMax(remote_geo_latitude, event_date_time) as latitude,
            argMax(remote_geo_longitude, event_date_time) as longitude
        FROM libp2p_synthetic_heartbeat
        WHERE 
            meta_network_name = %(network)s
            AND event_date_time BETWEEN %(start_time)s - INTERVAL 5 MINUTE AND %(end_time)s + INTERVAL 30 SECOND
        GROUP BY remote_peer_id_unique_key
    )
    SELECT 
        wl.slot,
        '' as block,
        wl.slot_start_date_time,
        0 as block_propagation_time,
        wl.peer_id,
        wl.first_meta_client,
        wl.idontwant_time,
        wl.propagation_delay_ms,
        wl.closest_rtt_ms as rtt_ms,
        wl.closest_rtt_ms / 2 as one_way_latency_ms,
        wl.propagation_delay_ms - (wl.closest_rtt_ms / 2) as adjusted_propagation_ms,
        COALESCE(geo.continent, 'Unknown') as continent,
        COALESCE(geo.country, 'Unknown') as country
    FROM with_latency wl
    LEFT JOIN geo_data geo ON wl.peer_id = geo.remote_peer_id_unique_key
    ORDER BY wl.slot DESC, wl.propagation_delay_ms ASC
    """


def get_combined_ihave_idontwant_data() -> str:
    """
    Get combined IHAVE and IDONTWANT data, taking the minimum time for each peer/slot.
    """
    return """
    WITH ihave_data AS (
        -- IHAVE data
        SELECT 
            peer_id_unique_key,
            meta_client_name,
            event_date_time,
            toUInt32(toUnixTimestamp(event_date_time) / 12) * 12 as slot_timestamp,
            toUInt64((toUInt32(toUnixTimestamp(event_date_time) / 12) * 12 - 1606824023) / 12) as slot,
            toInt64((event_date_time - toDateTime(toUInt32(toUnixTimestamp(event_date_time) / 12) * 12)) * 1000) as delay_ms,
            'IHAVE' as message_type
        FROM libp2p_rpc_meta_control_ihave
        WHERE 
            meta_network_name = %(network)s
            AND topic_name = 'beacon_block'
            AND event_date_time BETWEEN %(start_time)s AND %(end_time)s
    ),
    idontwant_data AS (
        -- IDONTWANT data (no topic_name filter)
        SELECT 
            peer_id_unique_key,
            meta_client_name,
            event_date_time,
            toUInt32(toUnixTimestamp(event_date_time) / 12) * 12 as slot_timestamp,
            toUInt64((toUInt32(toUnixTimestamp(event_date_time) / 12) * 12 - 1606824023) / 12) as slot,
            toInt64((event_date_time - toDateTime(toUInt32(toUnixTimestamp(event_date_time) / 12) * 12)) * 1000) as delay_ms,
            'IDONTWANT' as message_type
        FROM libp2p_rpc_meta_control_idontwant
        WHERE 
            meta_network_name = %(network)s
            AND event_date_time BETWEEN %(start_time)s AND %(end_time)s
            AND message_id != ''
    ),
    combined AS (
        SELECT * FROM ihave_data
        WHERE delay_ms >= -2000 AND delay_ms <= 20000
        UNION ALL
        SELECT * FROM idontwant_data
        WHERE delay_ms >= -2000 AND delay_ms <= 20000
    ),
    aggregated AS (
        -- Group by slot and peer, taking the earliest message time across all meta_clients
        SELECT 
            slot,
            toDateTime(slot_timestamp) as slot_start_date_time,
            peer_id_unique_key as peer_id,
            argMin(event_date_time, delay_ms) as first_seen_time,
            MIN(delay_ms) as propagation_delay_ms,
            argMin(message_type, delay_ms) as first_message_type,
            argMin(meta_client_name, delay_ms) as first_meta_client
        FROM combined
        GROUP BY slot, slot_timestamp, peer_id_unique_key
    ),
    -- Get closest heartbeat for latency data
    with_latency AS (
        SELECT 
            agg.slot,
            agg.slot_start_date_time,
            agg.peer_id,
            agg.first_meta_client,
            agg.first_seen_time,
            agg.propagation_delay_ms,
            agg.first_message_type,
            argMin(hb.latency_ms, ABS(toInt64((hb.event_date_time - agg.first_seen_time) * 1000))) as closest_rtt_ms
        FROM aggregated agg
        LEFT JOIN libp2p_synthetic_heartbeat hb 
            ON agg.peer_id = hb.remote_peer_id_unique_key
            AND agg.first_meta_client = hb.meta_client_name
            AND hb.event_date_time BETWEEN agg.first_seen_time - INTERVAL 10 MINUTE 
                AND agg.first_seen_time + INTERVAL 2 MINUTE
            AND hb.meta_network_name = %(network)s
        GROUP BY agg.slot, agg.slot_start_date_time, agg.peer_id, agg.first_meta_client, 
                 agg.first_seen_time, agg.propagation_delay_ms, agg.first_message_type
    ),
    -- Get latest geo data for each peer from heartbeat table
    geo_data AS (
        SELECT 
            remote_peer_id_unique_key,
            argMax(remote_geo_continent_code, event_date_time) as continent,
            argMax(remote_geo_country, event_date_time) as country,
            argMax(remote_geo_latitude, event_date_time) as latitude,
            argMax(remote_geo_longitude, event_date_time) as longitude
        FROM libp2p_synthetic_heartbeat
        WHERE 
            meta_network_name = %(network)s
            AND event_date_time BETWEEN %(start_time)s - INTERVAL 5 MINUTE AND %(end_time)s + INTERVAL 30 SECOND
        GROUP BY remote_peer_id_unique_key
    )
    SELECT 
        wl.slot,
        '' as block,
        wl.slot_start_date_time,
        0 as block_propagation_time,
        wl.peer_id,
        wl.first_meta_client,
        wl.first_seen_time,
        wl.propagation_delay_ms,
        wl.first_message_type,
        wl.closest_rtt_ms as rtt_ms,
        wl.closest_rtt_ms / 2 as one_way_latency_ms,
        wl.propagation_delay_ms - (wl.closest_rtt_ms / 2) as adjusted_propagation_ms,
        COALESCE(geo.continent, 'Unknown') as continent,
        COALESCE(geo.country, 'Unknown') as country
    FROM with_latency wl
    LEFT JOIN geo_data geo ON wl.peer_id = geo.remote_peer_id_unique_key
    ORDER BY wl.slot DESC, wl.propagation_delay_ms ASC
    """


def get_latest_idontwant_slot() -> str:
    """
    Get the latest slot that has IDONTWANT data.
    Since IDONTWANT doesn't have topic_name, we work with timing.
    """
    return """
    WITH latest_idontwant AS (
        SELECT 
            MAX(event_date_time) as max_time,
            toUInt32(toUnixTimestamp(MAX(event_date_time)) / 12) * 12 as slot_timestamp
        FROM libp2p_rpc_meta_control_idontwant
        WHERE 
            meta_network_name = %(network)s
            AND message_id != ''
            AND event_date_time <= now() - INTERVAL 5 MINUTE  -- Account for any delay
    )
    SELECT 
        toUInt64((slot_timestamp - 1606824023) / 12) as slot,
        toDateTime(slot_timestamp) as slot_time
    FROM latest_idontwant
    """