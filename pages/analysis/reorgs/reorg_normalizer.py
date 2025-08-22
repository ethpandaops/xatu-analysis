"""
Reorg normalization utilities for identifying common events across nodes
"""
import polars as pl
from typing import Tuple, Dict, List
from datetime import timedelta
from config_utils import get_client_normalization_rules

def normalize_reorg_events(
    df: pl.DataFrame,
    time_window_seconds: int = 60,  # Increased to 60s for better grouping
    match_old_head: bool = False  # Option to match on old_head_block too
) -> Tuple[pl.DataFrame, pl.DataFrame]:
    """
    Normalize reorg events to identify common events across multiple nodes.
    
    Uses new_head_block as primary key for matching (optionally old_head_block too).
    
    Args:
        df: Raw reorg event data with columns:
            - event_date_time: When the node observed it
            - slot: The slot where the reorg occurred
            - depth: How deep the reorg was
            - old_head_block: The block that was replaced
            - new_head_block: The block that replaced it
            - meta_client_name: The node that observed it
        time_window_seconds: Time window for grouping events (default 60s)
        match_old_head: Whether to also match on old_head_block (default False)
    
    Returns:
        Tuple of:
        - Normalized events DataFrame with one row per unique reorg
        - Event clusters DataFrame mapping individual events to normalized reorgs
    """
    # Calculate pivot slot (fork point)
    df = df.with_columns([
        (pl.col("slot") - pl.col("depth")).alias("pivot_slot")
    ])
    
    # Sort by time for clustering
    df = df.sort("event_date_time")
    
    # Group by new_head_block primarily (and optionally old_head_block)
    # Most reliable matching is just on new_head since nodes might have different old_heads
    group_cols = ["new_head_block", "old_head_block"] if match_old_head else ["new_head_block"]
    primary_groups = df.group_by(group_cols).agg([
        pl.col("event_date_time").min().alias("first_seen"),
        pl.col("event_date_time").max().alias("last_seen"),
        pl.col("meta_client_name").alias("observers"),
        pl.col("meta_consensus_implementation").alias("implementations"),
        pl.col("slot").alias("slots"),  # Collect all reported slots
        pl.col("depth").alias("depths"),
        pl.col("pivot_slot").alias("pivot_slots"),
        pl.col("old_head_block").alias("old_blocks"),  # Collect all old_head_blocks
        pl.col("propagation_slot_start_diff").alias("propagation_delays"),
        pl.col("active_node_count").max().alias("active_nodes")  # Get max active nodes for this group
    ])
    
    # Process each group to handle time windows and pivot tolerance
    normalized_events = []
    event_clusters = []
    
    for row in primary_groups.iter_rows(named=True):
        new_head = row["new_head_block"]
        observers = row["observers"]
        implementations = row["implementations"]
        slots = row["slots"]  # List of reported slots
        depths = row["depths"]
        pivot_slots = row["pivot_slots"]
        old_blocks = row["old_blocks"] if "old_blocks" in row else []
        first_seen = row["first_seen"]
        last_seen = row["last_seen"]
        propagation_delays = row["propagation_delays"]
        active_nodes = row["active_nodes"] if "active_nodes" in row else None
        
        # Determine old_head_block
        if match_old_head and "old_head_block" in row:
            # We grouped by old_head_block, so it's unique
            old_head = row["old_head_block"]
        else:
            # Find most common old_head_block among reports
            if old_blocks:
                old_block_counts = {}
                for block in old_blocks:
                    old_block_counts[block] = old_block_counts.get(block, 0) + 1
                old_head = max(old_block_counts, key=old_block_counts.get)
            else:
                old_head = "unknown"
        
        # Use the median slot as the consensus slot
        slot_values = [s for s in slots if s is not None]
        if slot_values:
            consensus_slot = sorted(slot_values)[len(slot_values) // 2]
        else:
            consensus_slot = 0
        
        # Check if events are within time window
        time_span = (last_seen - first_seen).total_seconds()
        
        if time_span <= time_window_seconds:
            # Single cluster - all events are the same reorg
            cluster_id = f"{new_head[:8]}_{old_head[:8]}"
            
            # Calculate consensus depth using trusted clients only
            normalization_rules = get_client_normalization_rules()
            trusted_depths = []
            
            # Collect depths from trusted implementations
            for i, impl in enumerate(implementations):
                if impl in normalization_rules and normalization_rules[impl].get("is_trusted", False):
                    if depths[i] is not None:
                        # Already normalized in data_loaders.py, so use directly
                        trusted_depths.append(depths[i])
            
            # If we have trusted depths, use them; otherwise fall back to all depths
            if trusted_depths:
                # Use the most common depth from trusted clients
                depth_counts = {}
                for d in trusted_depths:
                    depth_counts[d] = depth_counts.get(d, 0) + 1
                consensus_depth = max(depth_counts, key=depth_counts.get)
            elif depth_values := [d for d in depths if d is not None]:
                # Fallback: use most common depth from all clients
                depth_counts = {}
                for d in depth_values:
                    depth_counts[d] = depth_counts.get(d, 0) + 1
                consensus_depth = max(depth_counts, key=depth_counts.get)
            else:
                consensus_depth = 0
            
            # Calculate confidence score
            unique_observers = len(set(observers))
            unique_implementations = len(set(implementations))
            # Use trusted depths for consistency calculation
            if trusted_depths:
                depth_consistency = 1.0 - (max(trusted_depths) - min(trusted_depths)) / (max(trusted_depths) + 1)
            elif depths:
                depth_consistency = 1.0 - (max(depths) - min(depths)) / (max(depths) + 1)
            else:
                depth_consistency = 1.0
            
            confidence = calculate_confidence_score(
                unique_observers, 
                unique_implementations,
                depth_consistency
            )
            
            # We already have old_head from the grouping
            
            # Calculate average propagation delay
            valid_delays = [d for d in propagation_delays if d is not None]
            avg_propagation = sum(valid_delays) / len(valid_delays) if valid_delays else 0
            
            normalized_events.append({
                "cluster_id": cluster_id,
                "slot": consensus_slot,
                "new_head_block": new_head,
                "old_head_block": old_head,
                "consensus_depth": int(consensus_depth),  # Ensure integer depth
                "observer_count": unique_observers,
                "unique_implementations": unique_implementations,
                "first_detection": first_seen,
                "last_detection": last_seen,
                "detection_span_seconds": time_span,
                "confidence_score": confidence,
                "avg_propagation_delay": avg_propagation,
                "observer_list": list(set(observers)),  # List of unique observers
                "implementation_list": list(set(implementations)),  # List of unique implementations
                "active_node_count": active_nodes if active_nodes else 100  # Total active nodes at this time
            })
            
            # Map individual events to this cluster
            for i, observer in enumerate(observers):
                event_clusters.append({
                    "cluster_id": cluster_id,
                    "meta_client_name": observer,
                    "reported_depth": depths[i],
                    "detection_time": first_seen + timedelta(seconds=i * 0.001)  # Preserve order
                })
        else:
            # Multiple clusters needed - split by time
            # This is a more complex case that might need further refinement
            # For now, treat as separate events if outside time window
            # In this case, we'll just treat it as one big cluster with lower confidence
            cluster_id = f"{new_head[:8]}_{old_head[:8]}"
            
            # Calculate consensus depth using trusted clients only
            normalization_rules = get_client_normalization_rules()
            trusted_depths = []
            
            # Collect depths from trusted implementations
            for i, impl in enumerate(implementations):
                if impl in normalization_rules and normalization_rules[impl].get("is_trusted", False):
                    if depths[i] is not None:
                        # Already normalized in data_loaders.py, so use directly
                        trusted_depths.append(depths[i])
            
            # If we have trusted depths, use them; otherwise fall back to all depths
            if trusted_depths:
                # Use the most common depth from trusted clients
                depth_counts = {}
                for d in trusted_depths:
                    depth_counts[d] = depth_counts.get(d, 0) + 1
                consensus_depth = max(depth_counts, key=depth_counts.get)
            elif depth_values := [d for d in depths if d is not None]:
                # Fallback: use most common depth from all clients
                depth_counts = {}
                for d in depth_values:
                    depth_counts[d] = depth_counts.get(d, 0) + 1
                consensus_depth = max(depth_counts, key=depth_counts.get)
            else:
                consensus_depth = 0
            
            # Calculate confidence score (lower due to time spread)
            unique_observers = len(set(observers))
            unique_implementations = len(set(implementations))
            # Use trusted depths for consistency calculation
            if trusted_depths:
                depth_consistency = 1.0 - (max(trusted_depths) - min(trusted_depths)) / (max(trusted_depths) + 1)
            elif depths:
                depth_consistency = 1.0 - (max(depths) - min(depths)) / (max(depths) + 1)
            else:
                depth_consistency = 1.0
            
            # Reduce confidence due to time spread
            confidence = calculate_confidence_score(
                unique_observers, 
                unique_implementations,
                depth_consistency * 0.5  # Penalty for time spread
            )
            
            # Calculate average propagation delay
            valid_delays = [d for d in propagation_delays if d is not None]
            avg_propagation = sum(valid_delays) / len(valid_delays) if valid_delays else 0
            
            normalized_events.append({
                "cluster_id": cluster_id,
                "slot": consensus_slot,
                "new_head_block": new_head,
                "old_head_block": old_head,
                "consensus_depth": int(consensus_depth),  # Ensure integer depth
                "observer_count": unique_observers,
                "unique_implementations": unique_implementations,
                "first_detection": first_seen,
                "last_detection": last_seen,
                "detection_span_seconds": time_span,
                "confidence_score": confidence,
                "avg_propagation_delay": avg_propagation,
                "observer_list": list(set(observers)),
                "implementation_list": list(set(implementations)),
                "active_node_count": active_nodes if active_nodes else 100  # Total active nodes at this time
            })
            
            # Map individual events to this cluster
            for i, observer in enumerate(observers):
                event_clusters.append({
                    "cluster_id": cluster_id,
                    "meta_client_name": observer,
                    "reported_depth": depths[i],
                    "detection_time": first_seen + timedelta(seconds=i * 0.001)
                })
    
    # Create DataFrames
    normalized_df = pl.DataFrame(normalized_events)
    clusters_df = pl.DataFrame(event_clusters)
    
    return normalized_df, clusters_df

def calculate_confidence_score(
    observer_count: int,
    implementation_count: int,
    depth_consistency: float
) -> float:
    """
    Calculate confidence score for a reorg event cluster.
    
    Args:
        observer_count: Number of unique nodes observing the event
        implementation_count: Number of unique client implementations
        depth_consistency: Consistency of reported depths (0-1)
    
    Returns:
        Confidence score between 0 and 1
    """
    # Weight factors
    observer_weight = 0.4
    implementation_weight = 0.3
    consistency_weight = 0.3
    
    # Observer score (logarithmic scale)
    if observer_count >= 10:
        observer_score = 1.0
    elif observer_count >= 5:
        observer_score = 0.9
    elif observer_count >= 3:
        observer_score = 0.7
    elif observer_count >= 2:
        observer_score = 0.5
    else:
        observer_score = 0.3
    
    # Implementation diversity score
    if implementation_count >= 4:
        impl_score = 1.0
    elif implementation_count >= 3:
        impl_score = 0.8
    elif implementation_count >= 2:
        impl_score = 0.6
    else:
        impl_score = 0.4
    
    # Calculate weighted score
    confidence = (
        observer_weight * observer_score +
        implementation_weight * impl_score +
        consistency_weight * depth_consistency
    )
    
    return round(confidence, 3)

def split_by_time_window(
    events: List[Tuple],
    start_time: any,
    window_seconds: int
) -> List[List[Tuple]]:
    """
    Split events into clusters based on time windows.
    
    This is a placeholder for more sophisticated time-based clustering.
    """
    # Simplified implementation - would need proper time handling
    return [events]

def get_reorg_consensus_over_time(
    df: pl.DataFrame,
    time_bucket: str = "1h",
    min_observers: int = 1
) -> pl.DataFrame:
    """
    Analyze reorg consensus over time, showing how many nodes saw each reorg.
    
    Args:
        df: Normalized reorg events DataFrame
        time_bucket: Time aggregation bucket (e.g., "1h", "10m")
        min_observers: Minimum number of observers to include
    
    Returns:
        DataFrame with reorg consensus metrics over time
    """
    # Filter by minimum observers
    df = df.filter(pl.col("observer_count") >= min_observers)
    
    # Convert time bucket string to truncation
    if time_bucket == "1h":
        truncate_to = "hour"
    elif time_bucket == "10m":
        truncate_to = "10m"
    elif time_bucket == "1d":
        truncate_to = "day"
    else:
        truncate_to = "hour"
    
    # Aggregate by time bucket and depth
    consensus_df = df.group_by([
        pl.col("first_detection").dt.truncate(truncate_to).alias("time_bucket"),
        pl.col("consensus_depth").round().alias("depth")
    ]).agg([
        pl.col("observer_count").mean().alias("avg_observers"),
        pl.col("observer_count").max().alias("max_observers"),
        pl.col("cluster_id").count().alias("reorg_count"),
        pl.col("confidence_score").mean().alias("avg_confidence"),
        pl.col("unique_implementations").mean().alias("avg_implementations")
    ])
    
    # Add percentage of total nodes (assuming we know total node count)
    # This would need to be calculated based on total active nodes at that time
    consensus_df = consensus_df.with_columns([
        (pl.col("avg_observers") / 100 * 100).round(1).alias("observer_percentage")  # Placeholder
    ])
    
    return consensus_df.sort(["time_bucket", "depth"])

def identify_significant_reorgs(
    df: pl.DataFrame,
    min_depth: int = 2,
    min_observer_percentage: float = 0.5,
    total_nodes: int = 100
) -> pl.DataFrame:
    """
    Identify significant reorgs based on depth and observer consensus.
    
    Args:
        df: Normalized reorg events DataFrame
        min_depth: Minimum depth to consider significant
        min_observer_percentage: Minimum percentage of nodes that must observe it
        total_nodes: Total number of nodes in the network
    
    Returns:
        DataFrame of significant reorg events
    """
    min_observers = int(total_nodes * min_observer_percentage)
    
    significant = df.filter(
        (pl.col("consensus_depth") >= min_depth) &
        (pl.col("observer_count") >= min_observers)
    )
    
    # Add severity score
    significant = significant.with_columns([
        (
            pl.col("consensus_depth") * 0.3 +
            (pl.col("observer_count") / total_nodes) * 10 * 0.7
        ).alias("severity_score")
    ])
    
    return significant.sort("severity_score", descending=True)