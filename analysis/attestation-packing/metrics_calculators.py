import pandas as pd
import numpy as np

def calculate_first_seen_attestations(df):
    """
    Calculate first_seen_attestations for each block using a rolling window approach.
    Maintains a 65-slot rolling window to track previously seen validator attestations.
    """
    print("🔍 Calculating first seen attestations with rolling window...")
    
    # Sort by block_slot and slot for chronological processing
    df_sorted = df.sort_values(['block_slot', 'slot']).copy()
    
    # Dictionary to track seen attestations: {slot: {validator_index: True}}
    seen_attestations = {}
    
    # Dictionary to store first seen counts per block
    block_first_seen = {}
    
    # Process each attestation chronologically
    for _, row in df_sorted.iterrows():
        block_slot = row['block_slot']
        attestation_slot = row['slot']
        validator_indexes = row['validators']
        
        # Parse validators column if needed
        if isinstance(validator_indexes, str) and validator_indexes.startswith('['):
            import ast
            try:
                validator_indexes = ast.literal_eval(validator_indexes)
            except:
                validator_indexes = []
        elif not isinstance(validator_indexes, list):
            validator_indexes = list(validator_indexes) if hasattr(validator_indexes, '__iter__') else []
        
        # Clean up old slots (keep only last 65 slots)
        current_slots = list(seen_attestations.keys())
        for slot in current_slots:
            if block_slot - slot > 65:
                del seen_attestations[slot]
        
        # Count validators in this attestation not seen before for this slot
        first_seen_count = 0
        for validator_idx in validator_indexes:
            if attestation_slot not in seen_attestations or validator_idx not in seen_attestations[attestation_slot]:
                first_seen_count += 1
                # Initialize the slot dictionary if needed
                if attestation_slot not in seen_attestations:
                    seen_attestations[attestation_slot] = {}
                # Mark this validator as having attested for this slot
                seen_attestations[attestation_slot][validator_idx] = True
        
        # Add to block's first seen count
        if block_slot not in block_first_seen:
            block_first_seen[block_slot] = 0
        block_first_seen[block_slot] += first_seen_count
    
    print(f"✅ Calculated first seen attestations for {len(block_first_seen)} blocks")
    return block_first_seen

def calculate_slot_metrics(group):
    """Calculate metrics for a single block slot."""
    if group.empty:
        return pd.Series({
            'unique_validator_indexes': 0,
            'unique_committees': 0,
            'total_attestations': 0,
            'optimal_inclusion_validators': 0,
            'optimal_inclusion_rate': 0,
            'avg_validators_per_attestation': np.nan,
            'max_validators_per_attestation': np.nan,
            'min_attestation_inclusion_delay': np.nan,
            'avg_attestation_inclusion_delay': np.nan,
            'p50_attestation_inclusion_delay': np.nan,
            'p95_attestation_inclusion_delay': np.nan,
            'max_attestation_inclusion_delay': np.nan,
            'aggregation_efficiency': np.nan,
            'first_seen_attestations': 0,
            'block_slot_start_date_time': pd.NaT
        })

    # Get block_slot from the group's name (since it was the grouping key)
    block_slot = group.name if hasattr(group, 'name') else group['block_slot'].iloc[0]
    
    # Calculate temporary series needed for metrics
    attestation_delay = block_slot - group['slot']

    # Explode validators for unique count
    validators_list = group['validators'].tolist()
    flat_validators = []
    
    for validator_array in validators_list:
        if isinstance(validator_array, (list, np.ndarray)):
            flat_validators.extend(validator_array)
        elif isinstance(validator_array, str) and validator_array.startswith('['):
            import ast
            try:
                parsed = ast.literal_eval(validator_array)
                if isinstance(parsed, list):
                    flat_validators.extend(parsed)
            except:
                pass
    
    all_validators_in_slot = np.unique(np.array(flat_validators))
    unique_validator_count = len(all_validators_in_slot)

    # optimal_inclusion_validators - count unique validators with delay=1
    optimal_inclusion_mask = attestation_delay == 1
    optimal_inclusion_group = group[optimal_inclusion_mask]
    
    optimal_inclusion_validators_list = []
    for validator_array in optimal_inclusion_group['validators'].tolist():
        if isinstance(validator_array, (list, np.ndarray)):
            optimal_inclusion_validators_list.extend(validator_array)
        elif isinstance(validator_array, str) and validator_array.startswith('['):
            import ast
            try:
                parsed = ast.literal_eval(validator_array)
                if isinstance(parsed, list):
                    optimal_inclusion_validators_list.extend(parsed)
            except:
                pass
    
    optimal_inclusion_validators = len(np.unique(np.array(optimal_inclusion_validators_list))) if optimal_inclusion_validators_list else 0
    optimal_inclusion_rate = optimal_inclusion_validators / unique_validator_count if unique_validator_count > 0 else 0

    num_signatures = group['validators'].apply(len)
    total_attestations_count = len(group)

    metrics = {
        'unique_validator_indexes': unique_validator_count,
        'unique_committees': group['committee_index'].nunique(),
        'total_attestations': total_attestations_count,
        'optimal_inclusion_validators': optimal_inclusion_validators,
        'optimal_inclusion_rate': optimal_inclusion_rate,
        'avg_validators_per_attestation': num_signatures.mean(),
        'max_validators_per_attestation': num_signatures.max(),
        'min_attestation_inclusion_delay': attestation_delay.min(),
        'avg_attestation_inclusion_delay': attestation_delay.mean(),
        'p50_attestation_inclusion_delay': attestation_delay.quantile(0.50),
        'p95_attestation_inclusion_delay': attestation_delay.quantile(0.95),
        'max_attestation_inclusion_delay': attestation_delay.max(),
        'first_seen_attestations': 0,  # Will be populated separately
        'block_slot_start_date_time': group['block_slot_start_date_time'].iloc[0]
    }

    # Derived metric
    if total_attestations_count > 0:
        metrics['aggregation_efficiency'] = unique_validator_count / total_attestations_count
    else:
        metrics['aggregation_efficiency'] = np.nan

    return pd.Series(metrics)

