"""
Configuration utilities for attestation packing analysis
"""
import streamlit as st


def get_metric_info(metric_name):
    """Get human-readable title and description for metrics."""
    metric_info = {
        "unique_validator_indexes": {
            "title": "Unique Validators Per Block",
            "subtitle": "Total number of unique validators that submitted attestations included in each block. Higher values indicate better validator participation and network health."
        },
        "first_seen_attestations": {
            "title": "Fresh Attestations",
            "subtitle": "Number of attestations the client included in the block that had never been seen before. Measures how much 'new' attestation data each block contributes to the chain."
        },
        "avg_attestation_inclusion_delay": {
            "title": "Average Inclusion Delay",
            "subtitle": "Average number of slots between when an attestation was supposed to be included (slot + 1) and when it actually appeared in a block. Lower is better for network efficiency."
        },
        "optimal_inclusion_rate": {
            "title": "Optimal Inclusion Rate",
            "subtitle": "Percentage of validators whose attestations were included with just 1-slot delay (optimal timing). Higher rates indicate better network performance and proposer efficiency."
        },
        "min_attestation_inclusion_delay": {
            "title": "Minimum Inclusion Delay",
            "subtitle": "The shortest delay for any attestation in the block. Shows the best-case inclusion performance for that block."
        },
        "p50_attestation_inclusion_delay": {
            "title": "Median Inclusion Delay",
            "subtitle": "The middle value (50th percentile) of all inclusion delays in the block. Provides a robust measure of typical inclusion performance."
        },
        "p95_attestation_inclusion_delay": {
            "title": "95th Percentile Inclusion Delay",
            "subtitle": "The delay below which 95% of attestations fall. Helps identify outliers and worst-case inclusion scenarios."
        },
        "max_attestation_inclusion_delay": {
            "title": "Maximum Inclusion Delay",
            "subtitle": "The longest delay for any attestation in the block. Shows worst-case inclusion performance and potential network issues."
        },
        "aggregation_efficiency": {
            "title": "Aggregation Efficiency",
            "subtitle": "Ratio of unique validators to total attestations. Higher values mean better aggregation - fewer attestation objects needed to represent the same validator participation."
        },
        "total_attestations": {
            "title": "Total Attestations",
            "subtitle": "Total number of attestation objects included in each block. Lower numbers (with same validator participation) indicate better aggregation."
        },
        "avg_validators_per_attestation": {
            "title": "Average Validators Per Attestation",
            "subtitle": "Average number of validators represented by each attestation object. Higher values indicate better signature aggregation efficiency."
        },
        "optimal_inclusion_validators": {
            "title": "Optimal Inclusion Validators",
            "subtitle": "Number of validators whose attestations were included with optimal 1-slot delay. Measures absolute count (not percentage) of well-included validators."
        }
    }
    
    return metric_info.get(metric_name, {
        "title": metric_name.replace('_', ' ').title(),
        "subtitle": "No description available for this metric."
    })
