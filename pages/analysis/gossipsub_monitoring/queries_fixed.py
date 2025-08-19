"""
ClickHouse queries for Gossipsub Monitoring - Time-based approach.
Since message_ids don't match between tables, we use time correlation instead.
"""


def get_time_based_gossipsub_query() -> str:
    """
    Get gossipsub data using time-based correlation instead of message_id join.
    Ultra-simplified to avoid all distributed join issues.
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
        -- Wider time window: from 2 seconds before to 15 seconds after slot time
        AND event_date_time BETWEEN toDateTime(%(slot_time)s) - INTERVAL 2 SECOND 
            AND toDateTime(%(slot_time)s) + INTERVAL 15 SECOND
        -- Filter for beacon block topic (exact match)
        AND topic_name = 'beacon_block'
    GROUP BY peer_id_unique_key
    HAVING propagation_delay_ms >= -2000 AND propagation_delay_ms <= 15000
    """


def get_slots_in_range_simple() -> str:
    """Get slots in a time range - simplified."""
    return """
    SELECT DISTINCT slot
    FROM libp2p_gossipsub_beacon_block
    WHERE 
        meta_network_name = %(network)s
        AND slot_start_date_time BETWEEN %(start_time)s AND %(end_time)s
    ORDER BY slot DESC
    LIMIT %(limit)s
    """


def get_latest_slot_simple() -> str:
    """Get the latest slot with data."""
    return """
    SELECT MAX(slot) as max_slot
    FROM libp2p_gossipsub_beacon_block
    WHERE 
        meta_network_name = %(network)s
        AND slot_start_date_time >= now() - INTERVAL 1 HOUR
    """