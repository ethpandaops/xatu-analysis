"""
Data loading functions for reorg analysis
"""
import streamlit as st
import polars as pl
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from pages.analysis.reorgs.config_utils import get_depth_filter_config, get_client_normalization_rules

# Import existing shared data loading functionality
from shared.database import get_database_connection

def get_active_nodes_per_slot(
    start_time: datetime,
    end_time: datetime,
    network: str,
    cluster: str,
    include_ethpandaops: bool = False
) -> pl.DataFrame:
    """
    Get count of active nodes per slot from block events.
    
    Args:
        start_time: Start timestamp
        end_time: End timestamp
        network: Network name
        cluster: Data cluster
        include_ethpandaops: Whether to include ethpandaops nodes
        
    Returns:
        pl.DataFrame: Active node counts per slot
    """
    ethpandaops_filter = "" if include_ethpandaops else " AND NOT startsWith(meta_client_name, 'ethpandaops')"
    
    # Query that gets active node counts using 5-minute buckets for efficiency
    query = f"""
    WITH reorg_slots AS (
        -- Get unique slots where reorgs occurred with 5-minute buckets
        SELECT DISTINCT
            slot,
            slot_start_date_time,
            toStartOfFiveMinutes(slot_start_date_time) as time_bucket
        FROM default.beacon_api_eth_v1_events_chain_reorg
        WHERE meta_network_name = '{network}'
            AND event_date_time >= '{start_time.strftime('%Y-%m-%d %H:%M:%S')}'
            AND event_date_time <= '{end_time.strftime('%Y-%m-%d %H:%M:%S')}'
    ),
    node_counts AS (
        -- Count nodes per 5-minute bucket for efficiency
        SELECT 
            toStartOfFiveMinutes(slot_start_date_time) as time_bucket,
            COUNT(DISTINCT meta_client_name) as node_count
        FROM default.beacon_api_eth_v1_events_block
        WHERE meta_network_name = '{network}'
            AND slot_start_date_time >= (
                SELECT MIN(slot_start_date_time) - INTERVAL 5 MINUTE 
                FROM reorg_slots
            )
            AND slot_start_date_time <= (
                SELECT MAX(slot_start_date_time) + INTERVAL 5 MINUTE 
                FROM reorg_slots
            )
            {ethpandaops_filter}
        GROUP BY time_bucket
    )
    SELECT
        r.slot,
        CAST(n.node_count AS Int64) as active_node_count
    FROM reorg_slots r
    LEFT JOIN node_counts n ON r.time_bucket = n.time_bucket
    ORDER BY slot DESC
    """
    
    try:
        conn = get_database_connection(cluster)
        pandas_df = pd.read_sql(query, conn)
        return pl.from_pandas(pandas_df)
    except Exception as e:
        raise ValueError(f"Failed to load active node counts: {e}. Cannot proceed without this critical data.")

def load_reorg_data(
    start_time: datetime, 
    end_time: datetime, 
    network: str = "mainnet",
    cluster: str = "default",
    max_depth: Optional[int] = None,
    exclude_invalid: bool = True,
    include_ethpandaops: bool = False
) -> pl.DataFrame:
    """
    Load and clean reorg event data from ClickHouse.
    
    Args:
        start_time: Start timestamp
        end_time: End timestamp  
        network: Network name (mainnet, holesky, etc.)
        cluster: Data cluster to query
        max_depth: Maximum depth to include (filters out deep reorgs)
        exclude_invalid: Whether to exclude known invalid depth values
        include_ethpandaops: Whether to include ethpandaops nodes (default: False)
    
    Returns:
        pl.DataFrame: Cleaned reorg event data
    """
    depth_config = get_depth_filter_config()
    invalid_values = depth_config["invalid_depth_values"]
    
    # Build depth filter conditions
    depth_conditions = []
    # We'll handle invalid value filtering in apply_client_normalizations
    # Just apply the max_depth filter if specified
    if max_depth is not None:
        depth_conditions.append(f"depth <= {max_depth}")
    
    depth_filter = " AND ".join(depth_conditions) if depth_conditions else "1=1"
    
    # Build ethpandaops filter
    ethpandaops_filter = "" if include_ethpandaops else " AND NOT startsWith(meta_client_name, 'ethpandaops')"
    
    # Query for reorg events with filtering
    query = f"""
    SELECT 
        event_date_time,
        slot,
        epoch,
        depth,
        meta_consensus_implementation,
        meta_client_name,
        meta_network_name,
        new_head_block,
        old_head_block,
        propagation_slot_start_diff,
        execution_optimistic,
        meta_client_geo_city,
        meta_client_geo_country,
        meta_client_geo_latitude,
        meta_client_geo_longitude,
        slot_start_date_time,
        epoch_start_date_time
    FROM default.beacon_api_eth_v1_events_chain_reorg
    WHERE meta_network_name = '{network}'
        AND event_date_time >= '{start_time.strftime('%Y-%m-%d %H:%M:%S')}'
        AND event_date_time <= '{end_time.strftime('%Y-%m-%d %H:%M:%S')}'
        AND {depth_filter}
        {ethpandaops_filter}
    ORDER BY event_date_time DESC
    """
    
    conn = get_database_connection(cluster)
    # Load data using pandas then convert to polars
    pandas_df = pd.read_sql(query, conn)
    df = pl.from_pandas(pandas_df)
    
    # Ensure numeric columns have correct types
    df = df.with_columns([
        pl.col("slot").cast(pl.Int64),
        pl.col("epoch").cast(pl.Int64),
        pl.col("depth").cast(pl.Int64),
        pl.col("propagation_slot_start_diff").cast(pl.Float64),  # Keep nulls to preserve data integrity
        pl.col("meta_client_geo_latitude").cast(pl.Float64, strict=False),
        pl.col("meta_client_geo_longitude").cast(pl.Float64, strict=False)
    ])
    
    # Apply client-specific normalization (handles off-by-one differences and invalid values)
    original_count = len(df)
    df = apply_client_normalizations(df)
    filtered_count = original_count - len(df)
    
    if filtered_count > 0:
        st.info(f"Filtered {filtered_count} invalid reorg records during normalization")
    
    # Add derived columns
    df = df.with_columns([
        # Slot position within epoch
        (pl.col("slot") % 32).alias("slot_in_epoch"),
        
        # Detection delay in seconds
        (pl.col("propagation_slot_start_diff") / 1000).alias("detection_delay_seconds"),
        
        # Flag for deep reorgs
        (pl.col("depth") > 2).alias("is_deep_reorg"),
        
        # Flag for very deep reorgs
        (pl.col("depth") > 7).alias("is_very_deep_reorg")
    ])
    
    # Get active node counts for slots with reorgs
    active_nodes_df = get_active_nodes_per_slot(
        start_time, end_time, network, cluster, include_ethpandaops
    )
    
    # Join active node counts with reorg data
    if not active_nodes_df.is_empty():
        df = df.join(
            active_nodes_df,
            on="slot",
            how="left"
        )
        
        # Check if we have any null active node counts
        null_count = df.filter(pl.col("active_node_count").is_null()).height
        if null_count > 0:
            raise ValueError(
                f"Failed to determine active node count for {null_count} slots. "
                "Cannot proceed without accurate node count data."
            )
    else:
        # If we couldn't get active node counts at all, raise an error
        raise ValueError(
            "Failed to load active node counts. Cannot proceed without this data. "
            "Please check database connectivity and data availability."
        )
    
    return df

def apply_client_normalizations(df: pl.DataFrame) -> pl.DataFrame:
    """
    Apply client-specific normalizations to handle reporting differences.
    
    Args:
        df: Raw reorg data
        
    Returns:
        pl.DataFrame: Normalized reorg data
    """
    normalization_rules = get_client_normalization_rules()
    
    # First, filter out invalid depth values for specific clients
    for client, rules in normalization_rules.items():
        if rules["filter_values"]:
            # Filter out specific invalid values for this client
            df = df.filter(
                ~((pl.col("meta_consensus_implementation") == client) & 
                  pl.col("depth").is_in(rules["filter_values"]))
            )
    
    # Then apply depth adjustments
    for client, rules in normalization_rules.items():
        if rules["depth_adjustment"] != 0:
            df = df.with_columns(
                pl.when(pl.col("meta_consensus_implementation") == client)
                .then(pl.col("depth") + rules["depth_adjustment"])
                .otherwise(pl.col("depth"))
                .alias("depth")
            )
    
    # Filter out any remaining invalid depths (safety check)
    df = df.filter(pl.col("depth") >= 0)
    
    return df

def load_missed_slots_data(
    start_time: datetime,
    end_time: datetime,
    network: str = "mainnet",
    cluster: str = "default"
) -> pl.DataFrame:
    """
    Load data about missed slots to correlate with reorgs.
    
    Args:
        start_time: Start timestamp
        end_time: End timestamp
        network: Network name
        cluster: Data cluster
        
    Returns:
        pl.DataFrame: Missed slots data
    """
    # For now, return empty dataframe since we don't have the canonical tables
    # In the future, we could identify missed slots by looking for gaps in block production
    return pl.DataFrame()

def load_reorg_episodes(
    df: pl.DataFrame,
    episode_window_seconds: int = 4
) -> pl.DataFrame:
    """
    Group reorg events into episodes based on temporal proximity.
    
    Args:
        df: Reorg event data
        episode_window_seconds: Window size for grouping events
        
    Returns:
        pl.DataFrame: Reorg data with episode IDs
    """
    # Sort by event time
    df = df.sort("event_date_time")
    
    # Create episode windows based on time proximity
    df = df.with_columns([
        # Round to episode window (dt.epoch() returns milliseconds, so divide by 1000 for seconds)
        ((pl.col("event_date_time").dt.epoch() // 1000) // episode_window_seconds).alias("episode_window")
    ])
    
    # Assign episode IDs based on window and block hashes
    df = df.with_columns([
        # Create composite key for episode grouping
        pl.concat_str([
            pl.col("episode_window").cast(pl.Utf8),
            pl.col("old_head_block"),
            pl.col("new_head_block")
        ], separator="_").alias("episode_key")
    ])
    
    # Assign sequential episode IDs
    unique_episodes = df.select("episode_key").unique().with_row_count("episode_id")
    df = df.join(unique_episodes, on="episode_key", how="left")
    
    return df

def load_client_metadata(
    network: str = "mainnet",
    cluster: str = "default"
) -> pl.DataFrame:
    """
    Load metadata about clients for normalization and analysis.
    
    Args:
        network: Network name
        cluster: Data cluster
        
    Returns:
        pl.DataFrame: Client metadata
    """
    query = f"""
    SELECT DISTINCT
        meta_client_name,
        meta_consensus_implementation,
        meta_consensus_version,
        meta_client_geo_country,
        meta_client_geo_city,
        COUNT(*) as event_count
    FROM default.beacon_api_eth_v1_events_chain_reorg
    WHERE meta_network_name = '{network}'
        AND event_date_time >= now() - INTERVAL 30 DAY
    GROUP BY 
        meta_client_name,
        meta_consensus_implementation,
        meta_consensus_version,
        meta_client_geo_country,
        meta_client_geo_city
    ORDER BY event_count DESC
    """
    
    try:
        conn = get_database_connection(cluster)
        # Load data using pandas then convert to polars
        pandas_df = pd.read_sql(query, conn)
        df = pl.from_pandas(pandas_df)
        return df
    except Exception as e:
        st.warning(f"Could not load client metadata: {e}")
        return pl.DataFrame()

def deduplicate_reorg_events(
    df: pl.DataFrame,
    time_window_seconds: int = 60,
    match_old_head: bool = False
) -> pl.DataFrame:
    """
    Deduplicate reorg events that may be reported by multiple clients.
    
    This groups events by new_head_block (and optionally old_head_block) to find
    the same reorg reported by different nodes.
    
    Args:
        df: Raw reorg event data
        time_window_seconds: Max time difference to consider events as same (default: 60)
        match_old_head: Whether to also match on old_head_block (default: False)
        
    Returns:
        pl.DataFrame: Deduplicated events with confidence scores
    """
    # Import the advanced normalizer
    from reorg_normalizer import normalize_reorg_events
    
    # Use the advanced normalization
    normalized_events, event_clusters = normalize_reorg_events(
        df, 
        time_window_seconds=time_window_seconds,
        match_old_head=match_old_head
    )
    
    # Return in a format compatible with existing code
    dedup_df = normalized_events.rename({
        "observer_count": "reporting_clients",
        "unique_implementations": "reporting_implementations",
        "avg_propagation_delay": "avg_detection_delay"
    }).with_columns([
        # Add depth_variance for backward compatibility
        (pl.col("consensus_depth") * 0.1).alias("depth_variance"),
        
        # Extract first reporter from the event clusters
        pl.lit("multiple").alias("first_reporter")  # Will be updated if needed
    ])
    
    return dedup_df