"""
Metrics calculation functions for reorg analysis
"""
import polars as pl
import numpy as np
from typing import Dict, Optional, Tuple
from pages.analysis.reorgs.config_utils import get_severity_weights, get_episode_clustering_config

def calculate_basic_metrics(df: pl.DataFrame) -> Dict:
    """
    Calculate basic reorg metrics from the data.
    
    Args:
        df: Reorg event dataframe
        
    Returns:
        dict: Dictionary of calculated metrics
    """
    if df.is_empty():
        return {
            "total_reorgs": 0,
            "avg_depth": 0,
            "max_depth": 0,
            "min_depth": 0,
            "std_depth": 0,
            "unique_slots": 0,
            "affected_epochs": 0,
            "reporting_clients": 0,
            "deep_reorgs": 0,
            "very_deep_reorgs": 0
        }
    
    metrics = {
        "total_reorgs": len(df),
        "avg_depth": df["depth"].mean(),
        "max_depth": df["depth"].max(),
        "min_depth": df["depth"].min(),
        "std_depth": df["depth"].std(),
        "unique_slots": df["slot"].n_unique(),
        "affected_epochs": df["epoch"].n_unique(),
        "reporting_clients": df["meta_client_name"].n_unique(),
        "deep_reorgs": len(df.filter(pl.col("depth") > 2)),
        "very_deep_reorgs": len(df.filter(pl.col("depth") > 7))
    }
    
    # Calculate percentiles
    depth_values = df["depth"].to_list()
    if depth_values:
        metrics["p50_depth"] = np.percentile(depth_values, 50)
        metrics["p95_depth"] = np.percentile(depth_values, 95)
        metrics["p99_depth"] = np.percentile(depth_values, 99)
    
    return metrics

def calculate_reorg_rate(df: pl.DataFrame, time_bucket: str = "1h") -> pl.DataFrame:
    """
    Calculate reorg rate over time buckets.
    
    Args:
        df: Reorg event dataframe
        time_bucket: Time bucket size (5min, 1h, 1d, etc.)
        
    Returns:
        pl.DataFrame: Time series of reorg rates
    """
    # Map time bucket to truncation function
    truncate_map = {
        "5min": lambda x: x.dt.truncate("5m"),
        "15min": lambda x: x.dt.truncate("15m"),
        "30min": lambda x: x.dt.truncate("30m"),
        "1h": lambda x: x.dt.truncate("1h"),
        "4h": lambda x: x.dt.truncate("4h"),
        "1d": lambda x: x.dt.truncate("1d")
    }
    
    truncate_fn = truncate_map.get(time_bucket, lambda x: x.dt.truncate("1h"))
    
    # Group by time bucket and calculate rate
    rate_df = df.with_columns([
        truncate_fn(pl.col("event_date_time")).alias("time_bucket")
    ]).group_by("time_bucket").agg([
        pl.count().alias("reorg_count"),
        pl.col("depth").mean().alias("avg_depth"),
        pl.col("depth").max().alias("max_depth"),
        pl.col("meta_client_name").n_unique().alias("unique_clients")
    ]).sort("time_bucket")
    
    return rate_df

def calculate_client_metrics(df: pl.DataFrame) -> pl.DataFrame:
    """
    Calculate metrics grouped by individual client nodes.
    
    Args:
        df: Reorg event dataframe
        
    Returns:
        pl.DataFrame: Node-specific metrics
    """
    # Group by individual client name (node-level view)
    client_metrics = df.group_by(["meta_client_name", "meta_consensus_implementation"]).agg([
        pl.count().alias("reorg_count"),
        pl.col("depth").mean().alias("avg_depth"),
        pl.col("depth").median().alias("median_depth"),
        pl.col("depth").max().alias("max_depth"),
        pl.col("depth").std().alias("depth_std"),
        pl.col("detection_delay_seconds").mean().alias("avg_detection_delay"),
        pl.col("slot").n_unique().alias("unique_slots"),
        (pl.col("depth") > 2).sum().alias("deep_reorgs"),
        (pl.col("depth") > 7).sum().alias("very_deep_reorgs")
    ]).sort("reorg_count", descending=True)
    
    # Add percentage of total reorgs
    total_reorgs = df.height
    client_metrics = client_metrics.with_columns([
        (pl.col("reorg_count") / total_reorgs * 100).alias("pct_of_total")
    ])
    
    return client_metrics

def calculate_implementation_metrics(df: pl.DataFrame) -> pl.DataFrame:
    """
    Calculate metrics grouped by consensus implementation type.
    
    Args:
        df: Reorg event dataframe
        
    Returns:
        pl.DataFrame: Implementation-level metrics
    """
    impl_metrics = df.group_by("meta_consensus_implementation").agg([
        pl.count().alias("reorg_count"),
        pl.col("depth").mean().alias("avg_depth"),
        pl.col("depth").median().alias("median_depth"),
        pl.col("depth").max().alias("max_depth"),
        pl.col("depth").std().alias("depth_std"),
        pl.col("detection_delay_seconds").mean().alias("avg_detection_delay"),
        pl.col("slot").n_unique().alias("unique_slots"),
        pl.col("meta_client_name").n_unique().alias("unique_nodes"),
        (pl.col("depth") > 2).sum().alias("deep_reorgs"),
        (pl.col("depth") > 7).sum().alias("very_deep_reorgs")
    ]).sort("reorg_count", descending=True)
    
    # Add percentage of total reorgs
    total_reorgs = df.height
    impl_metrics = impl_metrics.with_columns([
        (pl.col("reorg_count") / total_reorgs * 100).alias("pct_of_total")
    ])
    
    return impl_metrics

def calculate_episode_metrics(df: pl.DataFrame) -> Tuple[pl.DataFrame, Dict]:
    """
    Calculate metrics for reorg episodes (clustered events).
    
    Args:
        df: Reorg event dataframe with episode_id column
        
    Returns:
        Tuple of episode dataframe and summary metrics
    """
    if "episode_id" not in df.columns:
        return pl.DataFrame(), {}
    
    # Calculate episode-level metrics
    episodes = df.group_by("episode_id").agg([
        pl.col("event_date_time").min().alias("episode_start"),
        pl.col("event_date_time").max().alias("episode_end"),
        pl.col("depth").max().alias("max_depth"),
        pl.col("depth").mean().alias("avg_depth"),
        pl.count().alias("event_count"),
        pl.col("meta_client_name").n_unique().alias("reporting_clients"),
        pl.col("meta_consensus_implementation").n_unique().alias("reporting_implementations"),
        pl.col("slot").min().alias("start_slot"),
        pl.col("slot").max().alias("end_slot"),
        pl.col("epoch").n_unique().alias("epochs_affected")
    ])
    
    # Calculate episode duration
    episodes = episodes.with_columns([
        ((pl.col("episode_end") - pl.col("episode_start")).dt.total_seconds()).alias("duration_seconds"),
        (pl.col("end_slot") - pl.col("start_slot")).alias("slot_span"),
        (pl.col("epochs_affected") > 1).alias("cross_epoch")
    ])
    
    # Calculate severity score
    episodes = calculate_severity_scores(episodes)
    
    # Summary metrics
    summary = {
        "total_episodes": len(episodes),
        "avg_episode_duration": episodes["duration_seconds"].mean(),
        "max_episode_duration": episodes["duration_seconds"].max(),
        "episodes_cross_epoch": episodes["cross_epoch"].sum(),
        "high_severity_episodes": len(episodes.filter(pl.col("severity_score") > 0.7)),
        "storm_events": detect_reorg_storms(episodes)
    }
    
    return episodes, summary

def calculate_severity_scores(episodes: pl.DataFrame) -> pl.DataFrame:
    """
    Calculate severity scores for reorg episodes.
    
    Args:
        episodes: Episode dataframe
        
    Returns:
        pl.DataFrame: Episodes with severity scores
    """
    weights = get_severity_weights()
    
    # Normalize components
    episodes = episodes.with_columns([
        # Log-scale depth component
        (pl.col("max_depth").log1p() / np.log1p(100)).alias("depth_component"),
        
        # Log-scale duration component
        (pl.col("duration_seconds").log1p() / np.log1p(300)).alias("duration_component"),
        
        # Client diversity component (inverse for weight)
        (1 / pl.col("reporting_clients").clip(1, 10)).alias("client_component"),
        
        # Cross-epoch flag
        pl.col("cross_epoch").cast(pl.Float64).alias("cross_epoch_component"),
        
        # Near justified checkpoint (placeholder - would need checkpoint data)
        pl.lit(0.0).alias("near_justified_component")
    ])
    
    # Calculate weighted severity score
    episodes = episodes.with_columns([
        (
            pl.col("depth_component") * weights["depth_weight"] +
            pl.col("duration_component") * weights["duration_weight"] +
            pl.col("client_component") * weights["client_weight"] +
            pl.col("cross_epoch_component") * weights["cross_epoch_weight"] +
            pl.col("near_justified_component") * weights["near_justified_weight"]
        ).alias("severity_score")
    ])
    
    return episodes

def detect_reorg_storms(episodes: pl.DataFrame) -> int:
    """
    Detect "reorg storm" events (multiple episodes in short time).
    
    Args:
        episodes: Episode dataframe
        
    Returns:
        int: Number of storm events detected
    """
    config = get_episode_clustering_config()
    storm_window = config["storm_window_minutes"] * 60  # Convert to seconds
    storm_threshold = config["storm_threshold_episodes"]
    
    # Sort episodes by start time
    episodes = episodes.sort("episode_start")
    
    # Use rolling window to count episodes
    episodes = episodes.with_columns([
        (pl.col("episode_start").dt.epoch() // 1000).alias("start_seconds")  # Convert ms to seconds
    ])
    
    storm_count = 0
    for i in range(len(episodes)):
        current_time = episodes["start_seconds"][i]
        window_start = current_time
        window_end = current_time + storm_window
        
        # Count episodes within window
        episodes_in_window = len(episodes.filter(
            (pl.col("start_seconds") >= window_start) & 
            (pl.col("start_seconds") <= window_end)
        ))
        
        if episodes_in_window >= storm_threshold:
            storm_count += 1
    
    return storm_count

def calculate_epoch_boundary_effects(df: pl.DataFrame) -> pl.DataFrame:
    """
    Analyze reorg patterns relative to epoch boundaries.
    
    Args:
        df: Reorg event dataframe
        
    Returns:
        pl.DataFrame: Reorg statistics by slot position
    """
    # Group by slot position within epoch
    boundary_effects = df.group_by("slot_in_epoch").agg([
        pl.count().alias("reorg_count"),
        pl.col("depth").mean().alias("avg_depth"),
        pl.col("depth").max().alias("max_depth"),
        pl.col("detection_delay_seconds").mean().alias("avg_detection_delay")
    ]).sort("slot_in_epoch")
    
    # Add percentage of total
    total_reorgs = boundary_effects["reorg_count"].sum()
    boundary_effects = boundary_effects.with_columns([
        (pl.col("reorg_count") / total_reorgs * 100).alias("pct_of_total")
    ])
    
    return boundary_effects

def correlate_with_missed_slots(
    reorg_df: pl.DataFrame, 
    missed_slots_df: pl.DataFrame
) -> Dict:
    """
    Correlate reorgs with missed slot events.
    
    Args:
        reorg_df: Reorg event dataframe
        missed_slots_df: Missed slots dataframe
        
    Returns:
        dict: Correlation metrics
    """
    if reorg_df.is_empty() or missed_slots_df.is_empty():
        return {
            "correlation_rate": 0,
            "reorgs_after_missed": 0,
            "avg_delay_after_missed": 0
        }
    
    # Find reorgs that occurred after missed slots
    reorgs_after_missed = 0
    delays = []
    
    for _, reorg in reorg_df.iter_rows(named=True):
        reorg_slot = reorg["slot"]
        
        # Check if previous slot was missed
        prev_slot = reorg_slot - 1
        prev_missed = missed_slots_df.filter(
            (pl.col("slot") == prev_slot) & 
            (pl.col("is_missed") == 1)
        )
        
        if not prev_missed.is_empty():
            reorgs_after_missed += 1
            if "detection_delay_seconds" in reorg:
                delays.append(reorg["detection_delay_seconds"])
    
    correlation_metrics = {
        "correlation_rate": (reorgs_after_missed / len(reorg_df) * 100) if len(reorg_df) > 0 else 0,
        "reorgs_after_missed": reorgs_after_missed,
        "avg_delay_after_missed": np.mean(delays) if delays else 0
    }
    
    return correlation_metrics

def calculate_geographic_distribution(df: pl.DataFrame) -> pl.DataFrame:
    """
    Calculate reorg distribution by geographic location.
    
    Args:
        df: Reorg event dataframe
        
    Returns:
        pl.DataFrame: Geographic distribution metrics
    """
    # Group by country
    geo_metrics = df.group_by("meta_client_geo_country").agg([
        pl.count().alias("reorg_count"),
        pl.col("depth").mean().alias("avg_depth"),
        pl.col("meta_client_name").n_unique().alias("unique_clients"),
        pl.col("detection_delay_seconds").mean().alias("avg_detection_delay")
    ]).sort("reorg_count", descending=True)
    
    # Add percentage
    total_reorgs = geo_metrics["reorg_count"].sum()
    geo_metrics = geo_metrics.with_columns([
        (pl.col("reorg_count") / total_reorgs * 100).alias("pct_of_total")
    ])
    
    return geo_metrics