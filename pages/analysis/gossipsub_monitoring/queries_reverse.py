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
    SELECT 
        %(slot)s as slot,
        '' as block,
        toDateTime(%(slot_time)s) as slot_start_date_time,
        0 as block_propagation_time,
        peer_id_unique_key as peer_id,
        MIN(event_date_time) as ihave_time,
        toInt64(MIN(event_date_time - toDateTime(%(slot_time)s)) * 1000) as propagation_delay_ms,
        'Unknown' as continent,
        'Unknown' as country
    FROM libp2p_rpc_meta_control_ihave
    WHERE 
        meta_network_name = %(network)s
        AND topic_name = 'beacon_block'
        -- Look for IHAVE messages around this slot time
        AND event_date_time BETWEEN toDateTime(%(slot_time)s) - INTERVAL 2 SECOND 
            AND toDateTime(%(slot_time)s) + INTERVAL 20 SECOND
    GROUP BY peer_id_unique_key
    HAVING propagation_delay_ms >= -2000 AND propagation_delay_ms <= 20000
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
            event_date_time,
            toUInt32(toUnixTimestamp(event_date_time) / 12) * 12 as slot_timestamp,
            toUInt64((toUInt32(toUnixTimestamp(event_date_time) / 12) * 12 - 1606824023) / 12) as slot
        FROM libp2p_rpc_meta_control_ihave
        WHERE 
            meta_network_name = %(network)s
            AND topic_name = 'beacon_block'
            AND event_date_time BETWEEN %(start_time)s AND %(end_time)s
    ),
    aggregated AS (
        -- Group by slot and peer to get first IHAVE time
        SELECT 
            slot,
            toDateTime(slot_timestamp) as slot_start_date_time,
            peer_id_unique_key as peer_id,
            MIN(event_date_time) as ihave_time,
            toInt64((MIN(event_date_time) - toDateTime(slot_timestamp)) * 1000) as propagation_delay_ms
        FROM slot_data
        GROUP BY slot, slot_timestamp, peer_id_unique_key
    )
    SELECT 
        slot,
        '' as block,
        slot_start_date_time,
        0 as block_propagation_time,
        peer_id,
        ihave_time,
        propagation_delay_ms,
        'Unknown' as continent,
        'Unknown' as country
    FROM aggregated
    WHERE propagation_delay_ms >= -2000 AND propagation_delay_ms <= 20000
    ORDER BY slot DESC, propagation_delay_ms ASC
    """