"""
Metric discovery and data lineage tracking for multi-metric performance analysis.

This module provides dynamic metric discovery and clear explanations of data transformations.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class MetricInfo:
    """Information about a metric including its type and characteristics."""
    
    def __init__(self, name: str, data: pd.Series):
        self.name = name
        self.dtype = str(data.dtype)
        self.count = len(data)
        self.non_null_count = data.notna().sum()
        self.unique_count = data.nunique()
        self.is_numeric = pd.api.types.is_numeric_dtype(data)
        self.is_categorical = pd.api.types.is_categorical_dtype(data) or (self.unique_count < 20 and not self.is_numeric)
        self.is_temporal = pd.api.types.is_datetime64_any_dtype(data)
        
        if self.is_numeric:
            self.min = data.min()
            self.max = data.max()
            self.mean = data.mean()
            self.std = data.std()
            self.percentiles = {
                'p25': data.quantile(0.25),
                'p50': data.quantile(0.50),
                'p75': data.quantile(0.75),
                'p90': data.quantile(0.90),
                'p95': data.quantile(0.95),
                'p99': data.quantile(0.99)
            }
            # Determine natural bucket size
            self.suggested_bucket_size = self._calculate_bucket_size(data)
        else:
            self.min = self.max = self.mean = self.std = None
            self.percentiles = {}
            self.suggested_bucket_size = None
            
        # Infer metric category based on name patterns
        self.category = self._infer_category()
        self.unit = self._infer_unit()
        
    def _calculate_bucket_size(self, data: pd.Series) -> Optional[float]:
        """Calculate a sensible bucket size for numeric data."""
        if not self.is_numeric or self.unique_count < 10:
            return None
            
        data_range = self.max - self.min
        if data_range == 0:
            return None
            
        # Aim for 10-20 buckets
        raw_bucket_size = data_range / 15
        
        # Round to nice numbers
        if raw_bucket_size > 1_000_000:
            return round(raw_bucket_size / 1_000_000) * 1_000_000
        elif raw_bucket_size > 100_000:
            return round(raw_bucket_size / 100_000) * 100_000
        elif raw_bucket_size > 10_000:
            return round(raw_bucket_size / 10_000) * 10_000
        elif raw_bucket_size > 1_000:
            return round(raw_bucket_size / 1_000) * 1_000
        elif raw_bucket_size > 100:
            return round(raw_bucket_size / 100) * 100
        elif raw_bucket_size > 10:
            return round(raw_bucket_size / 10) * 10
        else:
            return round(raw_bucket_size, 2)
            
    def _infer_category(self) -> str:
        """Infer metric category from name."""
        name_lower = self.name.lower()
        
        if 'gas' in name_lower:
            return 'Gas/Execution'
        elif 'time' in name_lower or 'propagation' in name_lower or 'gossip' in name_lower:
            return 'Timing/Latency'
        elif 'attestation' in name_lower:
            return 'Attestations'
        elif 'blob' in name_lower:
            return 'Blobs/Data'
        elif 'slot' in name_lower or 'epoch' in name_lower:
            return 'Chain Progress'
        elif 'client' in name_lower or 'implementation' in name_lower:
            return 'Client Info'
        elif 'geo' in name_lower or 'continent' in name_lower:
            return 'Geographic'
        else:
            return 'Other'
            
    def _infer_unit(self) -> str:
        """Infer metric unit from name."""
        name_lower = self.name.lower()
        
        if 'gas' in name_lower and 'utilization' not in name_lower:
            return 'gas'
        elif 'utilization' in name_lower:
            return '%'
        elif 'time' in name_lower or 'propagation' in name_lower or 'gossip' in name_lower:
            return 'ms'
        elif 'count' in name_lower or 'blob' in name_lower:
            return 'count'
        elif 'slot' in name_lower or 'epoch' in name_lower or 'distance' in name_lower:
            return 'slots'
        else:
            return ''


def discover_metrics(df: pd.DataFrame, exclude_columns: List[str] = None) -> Dict[str, MetricInfo]:
    """
    Discover all available metrics in a DataFrame.
    
    Args:
        df: DataFrame to analyze
        exclude_columns: Columns to exclude from discovery
        
    Returns:
        Dictionary mapping metric names to MetricInfo objects
    """
    exclude_columns = exclude_columns or ['slot_start_date_time', 'bucket_start', 'bucket_end']
    
    metrics = {}
    for col in df.columns:
        if col not in exclude_columns and not col.startswith('_'):
            try:
                metrics[col] = MetricInfo(col, df[col])
            except Exception as e:
                logger.warning(f"Could not analyze metric {col}: {e}")
                
    return metrics


class DataLineageTracker:
    """Track and explain data transformations."""
    
    def __init__(self):
        self.steps = []
        self.warnings = []
        self.current_record_count = None
        self.original_record_count = None
        
    def set_initial_state(self, df: pd.DataFrame, description: str = "Raw data loaded"):
        """Set the initial data state."""
        self.original_record_count = len(df)
        self.current_record_count = len(df)
        self.steps.append({
            'type': 'initial',
            'description': description,
            'record_count': len(df),
            'columns': list(df.columns)
        })
        
    def add_filter(self, description: str, records_before: int, records_after: int):
        """Add a filtering step."""
        self.current_record_count = records_after
        removed = records_before - records_after
        pct_removed = (removed / records_before * 100) if records_before > 0 else 0
        
        self.steps.append({
            'type': 'filter',
            'description': description,
            'records_before': records_before,
            'records_after': records_after,
            'records_removed': removed,
            'percent_removed': pct_removed
        })
        
        if pct_removed > 50:
            self.warnings.append(f"⚠️ Filter '{description}' removed {pct_removed:.1f}% of data")
            
    def add_aggregation(self, description: str, group_by: List[str], agg_function: str, 
                       records_before: int, records_after: int, is_two_stage: bool = False):
        """Add an aggregation step."""
        self.current_record_count = records_after
        
        step = {
            'type': 'aggregation',
            'description': description,
            'group_by': group_by,
            'agg_function': agg_function,
            'records_before': records_before,
            'records_after': records_after,
            'reduction_factor': records_before / records_after if records_after > 0 else 0,
            'is_two_stage': is_two_stage
        }
        
        self.steps.append(step)
        
    def add_sampling(self, description: str, sample_size: int, original_size: int, method: str = "random"):
        """Add a sampling step."""
        self.current_record_count = sample_size
        sample_pct = (sample_size / original_size * 100) if original_size > 0 else 0
        
        self.steps.append({
            'type': 'sampling',
            'description': description,
            'method': method,
            'original_size': original_size,
            'sample_size': sample_size,
            'sample_percentage': sample_pct
        })
        
        self.warnings.append(f"📊 Data sampled: showing {sample_pct:.1f}% of records ({sample_size:,} of {original_size:,})")
        
    def add_bucketing(self, metric: str, bucket_size: float, num_buckets: int):
        """Add a bucketing step."""
        self.steps.append({
            'type': 'bucketing',
            'description': f"Created {num_buckets} buckets for {metric}",
            'metric': metric,
            'bucket_size': bucket_size,
            'num_buckets': num_buckets
        })
        
    def generate_explanation(self) -> str:
        """Generate a human-readable explanation of the data transformations."""
        if not self.steps:
            return "No data transformations applied."
            
        explanation_parts = []
        
        # Initial data
        if self.steps[0]['type'] == 'initial':
            explanation_parts.append(f"Starting with {self.original_record_count:,} records")
            
        # Process each step
        for i, step in enumerate(self.steps[1:], 1):
            if step['type'] == 'filter':
                explanation_parts.append(
                    f"{i}. {step['description']} → {step['records_after']:,} records "
                    f"({step['records_removed']:,} removed, {step['percent_removed']:.1f}% filtered out)"
                )
                
            elif step['type'] == 'aggregation':
                if step['is_two_stage']:
                    explanation_parts.append(
                        f"{i}. Two-stage aggregation: First {step['agg_function']} per slot, "
                        f"then {step['description']} → {step['records_after']:,} records"
                    )
                else:
                    group_desc = ", ".join(step['group_by']) if step['group_by'] else "all data"
                    explanation_parts.append(
                        f"{i}. Aggregated by {group_desc} using {step['agg_function']} → "
                        f"{step['records_after']:,} records (reduction factor: {step['reduction_factor']:.1f}x)"
                    )
                    
            elif step['type'] == 'sampling':
                explanation_parts.append(
                    f"{i}. {step['description']} using {step['method']} sampling → "
                    f"{step['sample_size']:,} records ({step['sample_percentage']:.1f}% sample)"
                )
                
            elif step['type'] == 'bucketing':
                explanation_parts.append(
                    f"{i}. {step['description']} with bucket size {step['bucket_size']:,}"
                )
                
        # Final summary
        if self.current_record_count and self.original_record_count:
            final_pct = (self.current_record_count / self.original_record_count * 100)
            explanation_parts.append(
                f"\nFinal dataset: {self.current_record_count:,} records "
                f"({final_pct:.1f}% of original)"
            )
            
        return "\n".join(explanation_parts)
        
    def get_warnings(self) -> List[str]:
        """Get all warnings generated during processing."""
        return self.warnings


def format_bucket_size(value: float, unit: str = '') -> str:
    """Format bucket size for display."""
    if unit == 'gas' and value >= 1_000_000:
        return f"{value/1_000_000:.1f}M gas"
    elif unit == 'gas' and value >= 1_000:
        return f"{value/1_000:.1f}K gas"
    elif unit == 'ms' and value >= 1_000:
        return f"{value/1_000:.1f}s"
    elif unit == '%':
        return f"{value:.1f}%"
    else:
        return f"{value:,.0f}{' ' + unit if unit else ''}"