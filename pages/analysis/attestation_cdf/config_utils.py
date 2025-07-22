from datetime import timedelta


def get_metric_info(metric_name):
    """Get human-readable info for CDF metrics."""
    metric_info = {
        "propagation_time_p50": {
            "title": "Median Propagation Time",
            "subtitle": "Time for 50% of attestations to arrive at node",
            "unit": "ms",
            "format": ".1f"
        },
        "propagation_time_p90": {
            "title": "90th Percentile Propagation",
            "subtitle": "Time for 90% of attestations to reach node",
            "unit": "ms", 
            "format": ".1f"
        },
        "attestation_coverage": {
            "title": "Attestation Coverage",
            "subtitle": "Percentage of expected attestations received",
            "unit": "%",
            "format": ".1f"
        },
        "cdf_area_under_curve": {
            "title": "CDF Area Under Curve",
            "subtitle": "Overall propagation efficiency metric",
            "unit": "ratio",
            "format": ".3f"
        },
        "execution_payload_gas_used": {
            "title": "Gas Used",
            "subtitle": "Total gas used in block execution",
            "unit": "gas",
            "format": ".2e"
        },
        "p50_propagation_time": {
            "title": "Median Propagation Time",
            "subtitle": "Time for 50% of attestations to arrive at node",
            "unit": "ms",
            "format": ".1f"
        },
        "p90_propagation_time": {
            "title": "90th Percentile Propagation",
            "subtitle": "Time for 90% of attestations to reach node",
            "unit": "ms",
            "format": ".1f"
        },
        "coverage_ratio": {
            "title": "Coverage Ratio",
            "subtitle": "Ratio of received to expected attestations",
            "unit": "ratio",
            "format": ".3f"
        }
    }
    return metric_info.get(metric_name, {
        "title": metric_name.replace('_', ' ').title(),
        "subtitle": "No description available for this metric.",
        "unit": "",
        "format": ".2f"
    })


def get_default_time_ranges():
    """Get default time range options."""
    return {
        "Last 1 Hour": timedelta(hours=1),
        "Last 6 Hours": timedelta(hours=6),
        "Last 24 Hours": timedelta(hours=24),
        "Last 3 Days": timedelta(days=3),
        "Last Week": timedelta(days=7)
    }


def get_supported_networks():
    """Get supported network options.""" 
    return ["mainnet", "holesky", "sepolia"]


def get_grouping_options():
    """Get available data grouping options for missed slot analysis."""
    return {
        "client_type": "Client Type (meta_client_name)",
        "slot": "Individual Slot"
    }


def get_data_source_options():
    """Get available attestation data source options."""
    return {
        "beacon_api": {
            "name": "Beacon Node API Events", 
            "table": "beacon_api_eth_v1_events_attestation",
            "description": "Attestations captured via beacon node API events",
            "use_case": "Node-specific attestation processing, API timing analysis"
        },
        "gossip": {
            "name": "P2P Gossip Network",
            "table": "libp2p_gossipsub_beacon_attestation",
            "description": "Attestations as seen propagating through the P2P gossip network",
            "use_case": "Network propagation analysis, timing studies"
        }
    }