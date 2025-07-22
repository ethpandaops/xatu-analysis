import pandas as pd
import numpy as np
from typing import Dict, List, Tuple


def calculate_node_cdf_metrics(attestation_data, committee_data, grouping_column='meta_client_name'):
    """Process pre-computed CDF metrics from ClickHouse."""
    
    # ClickHouse has already computed all metrics - just reformat for compatibility
    if grouping_column == 'meta_client_name':
        # Client-level analysis - data is already grouped correctly
        result_data = attestation_data.copy()
        result_data['group_name'] = result_data['meta_client_name']
        result_data['received_attestations'] = result_data['total_attestations']
        
        # Rename columns to match expected output
        column_mapping = {
            'p50_propagation': 'p50_propagation_time',
            'p90_propagation': 'p90_propagation_time',
            'p95_propagation': 'p95_propagation_time',
            'cdf_area_under_curve': 'cdf_area_under_curve'
        }
        
        for old_col, new_col in column_mapping.items():
            if old_col in result_data.columns:
                result_data[new_col] = result_data[old_col]
        
        # Generate CDF curves from actual percentiles
        cdf_results = result_data.apply(generate_cdf_from_percentiles, axis=1)
        result_data['cdf_times'] = cdf_results.apply(lambda x: x[0] if isinstance(x, tuple) else [])
        result_data['cdf_probabilities'] = cdf_results.apply(lambda x: x[1] if isinstance(x, tuple) else [])
        
    else:
        # Slot-level analysis - need to merge with slot metadata first
        # This is handled by the dashboard when it merges attestation data with slot metadata
        result_data = attestation_data.copy()
        result_data['group_name'] = result_data.get(grouping_column, 'Unknown')
        result_data['received_attestations'] = result_data['total_attestations']
        
        # Use pre-computed metrics from ClickHouse
        column_mapping = {
            'p50_propagation': 'p50_propagation_time',
            'p90_propagation': 'p90_propagation_time', 
            'p95_propagation': 'p95_propagation_time'
        }
        
        for old_col, new_col in column_mapping.items():
            if old_col in result_data.columns:
                result_data[new_col] = result_data[old_col]
        
        # Generate CDF curves from actual percentiles
        cdf_results = result_data.apply(generate_cdf_from_percentiles, axis=1)
        result_data['cdf_times'] = cdf_results.apply(lambda x: x[0] if isinstance(x, tuple) else [])
        result_data['cdf_probabilities'] = cdf_results.apply(lambda x: x[1] if isinstance(x, tuple) else [])
    
    # Add min/max propagation time columns if they exist
    if 'min_propagation' in result_data.columns:
        result_data['min_propagation_time'] = result_data['min_propagation']
    if 'max_propagation' in result_data.columns:
        result_data['max_propagation_time'] = result_data['max_propagation']
    
    # Ensure required columns exist
    required_columns = ['slot', 'group_name', 'expected_attestations', 'received_attestations',
                       'coverage_ratio', 'p50_propagation_time', 'p90_propagation_time', 
                       'cdf_area_under_curve', 'cdf_times', 'cdf_probabilities']
    
    # Add optional columns if they exist
    optional_columns = ['min_propagation_time', 'max_propagation_time', 'min_propagation', 'max_propagation',
                       'p95_propagation_time', 'mean_propagation', 'stddev_propagation']
    
    for col in optional_columns:
        if col in result_data.columns:
            required_columns.append(col)
    
    for col in required_columns:
        if col not in result_data.columns:
            if col == 'p95_propagation_time':
                result_data[col] = result_data.get('p95_propagation', result_data.get('p90_propagation_time', 0))
            else:
                result_data[col] = 0 if col != 'cdf_times' and col != 'cdf_probabilities' else []
    
    return result_data[required_columns]


def generate_cdf_from_percentiles(row):
    """Generate CDF data points from actual percentiles."""
    # Start with min value
    percentile_mapping = [(0.00, row.get('min_propagation', 0))]
    
    # Add all percentiles from 2% to 98% (every 2%)
    for i in range(2, 100, 2):
        col_name = f'p{i:02d}_propagation'
        value = row.get(col_name, row.get(f'p{i:02d}_propagation_time', 0))
        percentile_mapping.append((i/100, value))
    
    # Add max value
    percentile_mapping.append((1.00, row.get('max_propagation', 0)))
    
    # Filter out missing values and sort by time
    valid_points = [(prob, time) for prob, time in percentile_mapping if not pd.isna(time) and time > 0]
    
    if len(valid_points) < 2:
        return [], []
    
    # Sort by time value
    valid_points.sort(key=lambda x: x[1])
    
    # Separate into probabilities and times
    probabilities = [p[0] for p in valid_points]
    times = [p[1] for p in valid_points]
    
    return times, probabilities


def aggregate_cdf_across_conditions(cdf_data, slot_metadata, condition_columns):
    """Aggregate pre-computed CDF metrics across different conditions."""
    
    # Since ClickHouse already computed metrics, this is much simpler
    # cdf_data already contains the slot-level metrics we need
    
    aggregated_results = []
    
    for condition_col in condition_columns:
        # Map UI condition names to actual column names
        column_mapping = {
            'is_mev': 'is_mev',
            'block_seen': 'block_seen', 
            'is_canonical': 'is_canonical',
            'proposer_entity': 'proposer_entity'
        }
        
        actual_column = column_mapping.get(condition_col, condition_col)
        
        # Check if the condition exists in slot metadata or cdf_data
        if actual_column in cdf_data.columns:
            condition_data = cdf_data
        elif actual_column in slot_metadata.columns:
            # Merge with slot metadata to get the condition
            condition_data = cdf_data.merge(slot_metadata[['slot', actual_column]], on='slot', how='left')
        else:
            continue
            
        for condition_value, group_data in condition_data.groupby(actual_column):
            
            # Aggregate metrics using ClickHouse pre-computed values
            aggregated = {
                'condition_type': condition_col,
                'condition_value': condition_value,
                'total_slots': group_data['slot'].nunique(),
                'avg_p50_propagation': group_data['p50_propagation_time'].mean(),
                'avg_p90_propagation': group_data['p90_propagation_time'].mean(),
                'avg_coverage_ratio': group_data['coverage_ratio'].mean(),
                'avg_auc': group_data['cdf_area_under_curve'].mean(),
            }
            
            # Create representative CDF curve from aggregated metrics
            if not group_data.empty:
                avg_p50 = aggregated['avg_p50_propagation']
                avg_p90 = aggregated['avg_p90_propagation']
                
                if not pd.isna(avg_p50) and not pd.isna(avg_p90):
                    # For aggregated data, we only have p50 and p90
                    # Create a simple CDF with just these two points
                    aggregated['combined_cdf_times'] = [0, avg_p50, avg_p90, avg_p90 * 1.2]
                    aggregated['combined_cdf_probabilities'] = [0.0, 0.5, 0.9, 1.0]
                else:
                    aggregated['combined_cdf_times'] = []
                    aggregated['combined_cdf_probabilities'] = []
            else:
                aggregated['combined_cdf_times'] = []
                aggregated['combined_cdf_probabilities'] = []
            
            aggregated_results.append(aggregated)
    
    return pd.DataFrame(aggregated_results)


def calculate_comparative_metrics(cdf_data_1, cdf_data_2, comparison_name):
    """Calculate metrics comparing two pre-computed CDF datasets."""
    
    # Work with ClickHouse pre-computed metrics
    metrics = {
        'comparison_name': comparison_name,
        'dataset_1_slots': cdf_data_1['slot'].nunique() if not cdf_data_1.empty else 0,
        'dataset_2_slots': cdf_data_2['slot'].nunique() if not cdf_data_2.empty else 0,
    }
    
    # Calculate differences using pre-computed metrics
    if not cdf_data_1.empty and not cdf_data_2.empty:
        metrics.update({
            'p50_difference': cdf_data_1['p50_propagation_time'].mean() - cdf_data_2['p50_propagation_time'].mean(),
            'p90_difference': cdf_data_1['p90_propagation_time'].mean() - cdf_data_2['p90_propagation_time'].mean(),
            'coverage_difference': cdf_data_1['coverage_ratio'].mean() - cdf_data_2['coverage_ratio'].mean(),
            'auc_difference': cdf_data_1['cdf_area_under_curve'].mean() - cdf_data_2['cdf_area_under_curve'].mean()
        })
    else:
        metrics.update({
            'p50_difference': np.nan,
            'p90_difference': np.nan,
            'coverage_difference': np.nan,
            'auc_difference': np.nan
        })
    
    return metrics