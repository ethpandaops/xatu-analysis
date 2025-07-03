"""Report generation module for validator performance analysis.

This module provides functions to generate comprehensive markdown reports from validator
performance data collected from multiple sources (BeaconChain, Rated.network, etc.).
"""
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from pages.analysis.validator_performance.performance_summary import (
    analyze_beaconchain_data,
    analyze_rated_data,
    calculate_aggregate_metrics,
    THRESHOLDS
)
from pages.analysis.validator_performance.time_utils import (
    get_time_range_from_selection
)


def generate_markdown_report(
    current_network: str,
    pubkey_to_index: Dict[str, int],
    time_range_config: Dict[str, Any],
    excluded_ranges: List[Dict[str, str]],
    beaconchain_results: Optional[Dict[str, Any]] = None,
    effectiveness_data: Optional[Dict[int, List[Dict[str, Any]]]] = None,
    attestation_data: Optional[List[Dict[str, Any]]] = None,
    proposal_data: Optional[List[Dict[str, Any]]] = None
) -> str:
    """Generate a comprehensive markdown report of validator performance analysis.
    
    Args:
        current_network: The network being analyzed (e.g., 'mainnet', 'goerli')
        pubkey_to_index: Mapping of validator pubkey to index
        time_range_config: Time range configuration dictionary
        excluded_ranges: List of excluded date ranges
        beaconchain_results: Optional BeaconChain API results
        effectiveness_data: Optional Rated.network effectiveness data by validator
        attestation_data: Optional attestation performance data
        proposal_data: Optional proposal performance data
        
    Returns:
        Complete markdown report as a string
    """
    report = []
    
    # Generate header section
    header_section = _generate_header_section(
        current_network, 
        len(pubkey_to_index), 
        time_range_config, 
        excluded_ranges
    )
    report.extend(header_section)
    
    # Add performance requirements
    requirements_section = _generate_requirements_section()
    report.extend(requirements_section)
    
    # Analyze data
    has_beaconchain = beaconchain_results and 'stats_data' in beaconchain_results
    has_rated = effectiveness_data is not None
    
    # Create reverse mapping for index to pubkey
    index_to_pubkey = {idx: pubkey for pubkey, idx in pubkey_to_index.items()}
    
    # Analyze data from different sources
    bc_validator_stats = {}
    if has_beaconchain:
        bc_validator_stats = analyze_beaconchain_data(beaconchain_results['stats_data'])
    
    rated_validator_stats = {}
    if has_rated:
        rated_validator_stats = analyze_rated_data(effectiveness_data)
    
    # Check for validators with missing balance data
    validators_missing_balance = sum(
        1 for stats in bc_validator_stats.values() 
        if stats['lowest_balance'] == float('inf') and stats['end_balance'] is None
    )
    
    # Generate aggregated performance section
    findings_section = _generate_findings_section(bc_validator_stats, rated_validator_stats, validators_missing_balance)
    report.extend(findings_section)
    
    # Calculate aggregate metrics
    aggregate_metrics = calculate_aggregate_metrics(
        bc_validator_stats,
        rated_validator_stats,
        attestation_data,
        proposal_data
    )
    
    # Generate aggregate metrics section
    aggregate_section = _generate_aggregate_metrics_section(
        aggregate_metrics.get('beaconchain_metrics'),
        aggregate_metrics.get('rated_metrics'),
        aggregate_metrics.get('attestation_metrics'),
        aggregate_metrics.get('proposal_metrics')
    )
    report.extend(aggregate_section)
    
    # Generate detailed analysis section
    report.append("## Detailed Analysis\n")
    
    # Prepare data for per-validator table
    attestation_validators_data = {}
    proposal_validators_data = {}
    
    # Process attestation data if available
    if attestation_data:
        for record in attestation_data:
            idx = record.get('validatorIndex')
            if idx is not None:
                if idx not in attestation_validators_data:
                    attestation_validators_data[idx] = []
                attestation_validators_data[idx].append(record)
    
    # Process proposal data if available
    if proposal_data:
        for record in proposal_data:
            idx = record.get('validatorIndex')
            if idx is not None:
                if idx not in proposal_validators_data:
                    proposal_validators_data[idx] = []
                proposal_validators_data[idx].append(record)
    
    # Get all validator indices
    all_validator_indices = set(list(bc_validator_stats.keys()) + list(rated_validator_stats.keys()))
    all_validator_indices.update(attestation_validators_data.keys())
    all_validator_indices.update(proposal_validators_data.keys())
    
    # Generate per-validator table
    validator_table = _generate_per_validator_table(
        all_validator_indices,
        index_to_pubkey,
        bc_validator_stats,
        rated_validator_stats,
        attestation_validators_data,
        proposal_validators_data
    )
    report.extend(validator_table)
    
    # Add metrics explanation at the end
    metrics_explanation = _generate_metrics_explanation()
    report.extend(metrics_explanation)
    
    # Add footer
    report.append("\n---\n")
    report.append("*This report was generated by the Xatu Analysis Validator Performance Dashboard*")
    
    return "\n".join(report)


def _generate_header_section(
    network: str, 
    validator_count: int, 
    time_range_config: Dict[str, Any], 
    excluded_ranges: List[Dict[str, str]]
) -> List[str]:
    """Generate the header section of the report.
    
    Args:
        network: Network name
        validator_count: Number of validators analyzed
        time_range_config: Time range configuration
        excluded_ranges: List of excluded date ranges
        
    Returns:
        List of report lines for the header section
    """
    section = []
    
    # Header
    section.append("# Validator Performance Analysis Report")
    section.append("\n## Configuration")
    section.append(f"- **Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    section.append(f"- **Network**: {network}")
    section.append(f"- **Validators Analyzed**: {validator_count}")
    
    # Time range info
    time_range = get_time_range_from_selection(
        time_range_config.get('type', 'predefined'),
        time_range_config.get('value'),
        time_range_config.get('custom_start'),
        time_range_config.get('custom_end'),
        time_range_config.get('before_date'),
        time_range_config.get('after_date')
    )
    if time_range:
        start_date, end_date = time_range
        section.append(f"- **Time Range**: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    
    # Add excluded date ranges if any
    if excluded_ranges:
        exclusions_text = ", ".join([
            f"{exc['start']} to {exc['end']}" 
            for exc in excluded_ranges
        ])
        section.append(f"- **Excluded Date Ranges**: {exclusions_text}")
    
    section.append("\n")
    
    return section


def _generate_metrics_explanation() -> List[str]:
    """Generate the metrics explanation section.
    
    Returns:
        List of report lines explaining the metrics
    """
    section = []
    
    section.append("## Understanding Rated.network Metrics\n")
    section.append("### Core Performance Metrics")
    section.append("- **Validator Effectiveness**: The Rated model of validator performance, combining attester (97% weight) and proposer (3% weight) effectiveness")
    section.append("- **Attester Effectiveness**: Measures how well a validator performs attestation duties, including participation rate and inclusion speed")
    section.append("- **Proposer Effectiveness**: Success rate when selected to propose blocks (ratio of successful proposals to total proposal duties)")
    section.append("- **Inclusion Delay**: Average distance (in slots) between when an attestation is expected and when it's actually included on-chain")
    section.append("- **Correctness**: Average accuracy of source, target, and head votes in attestations")
    section.append("- **Uptime**: Percentage of epochs where the validator performed at least one duty\n")
    
    section.append("### Vote Accuracy Components")
    section.append("- **Source Vote**: Voting for the correct justified checkpoint")
    section.append("- **Target Vote**: Voting for the correct epoch boundary block")
    section.append("- **Head Vote**: Voting for the correct head of the chain\n")
    
    section.append("### Additional Metrics")
    section.append("- **Participation Rate**: Number of epochs with included attestations divided by total active epochs")
    section.append("- **Proposal Miss Rate**: Failed block proposals divided by total proposal slots attributed")
    section.append("- **Slashings**: Severe protocol violations resulting in penalties and forced exit\n")
    
    return section


def _generate_requirements_section() -> List[str]:
    """Generate the performance requirements section.
    
    Returns:
        List of report lines explaining performance requirements
    """
    section = []
    
    section.append("## Performance Requirements\n")
    section.append("### Aggregate Performance Metrics")
    section.append("Validators must maintain the following aggregate average performance metrics:")
    section.append(f"- **Attestation Inclusion Rate**: >{THRESHOLDS['min_attestation_inclusion_rate']}% (based on rated.network uptime)")
    section.append(f"- **Attestation Correctness Rate**: >{THRESHOLDS['min_attestation_correctness_rate']}%")
    section.append(f"- **Block Production**: >{THRESHOLDS['min_block_production_rate']}%\n")
    
    section.append("### Minimum Balance & Slashings")
    section.append(f"- **Minimum Balance**: Each individual validator must maintain a minimum balance of {THRESHOLDS['min_balance_eth']} ETH")
    section.append("- **Slashing Events**: Not allowed and considered critical\n")
    
    return section


def _generate_findings_section(
    bc_validator_stats: Dict[int, Dict[str, Any]],
    rated_validator_stats: Dict[int, Dict[str, Any]],
    validators_missing_balance: int
) -> List[str]:
    """Generate the aggregated performance section showing all threshold metrics.
    
    Args:
        bc_validator_stats: Analyzed BeaconChain validator stats
        rated_validator_stats: Analyzed Rated.network validator stats
        validators_missing_balance: Number of validators with missing balance data
        
    Returns:
        List of report lines for the aggregated performance section
    """
    section = []
    
    section.append("## Aggregated Performance\n")
    
    # Calculate aggregate values
    total_slashings = sum(stats.get('slashings', 0) for stats in bc_validator_stats.values()) if bc_validator_stats else 0
    
    # Minimum balance across all validators
    min_balance_eth = float('inf')
    for stats in bc_validator_stats.values():
        if stats['lowest_balance'] != float('inf'):
            min_balance_eth = min(min_balance_eth, stats['lowest_balance'] / 1e9)
        elif stats['end_balance'] is not None:
            min_balance_eth = min(min_balance_eth, stats['end_balance'] / 1e9)
    
    if min_balance_eth == float('inf'):
        min_balance_eth = None
    
    # Average uptime (attestation inclusion rate)
    avg_uptime_pct = None
    if rated_validator_stats:
        avg_uptime_pct = sum(stats['avg_uptime'] * 100 for stats in rated_validator_stats.values()) / len(rated_validator_stats)
    
    # Average correctness
    avg_correctness_pct = None
    if rated_validator_stats:
        avg_correctness_pct = sum(stats['avg_correctness'] * 100 for stats in rated_validator_stats.values()) / len(rated_validator_stats)
    
    # Average block production rate
    avg_block_production_pct = None
    validators_with_proposer_duties = [stats for stats in rated_validator_stats.values() if stats.get('total_proposer_duties', 0) > 0]
    if validators_with_proposer_duties:
        avg_block_production_pct = sum(stats['avg_proposer_effectiveness'] for stats in validators_with_proposer_duties) / len(validators_with_proposer_duties)
    
    # Create table
    section.append("| Metric | Value | Threshold | Status | Source |")
    section.append("|--------|-------|-----------|--------|--------|")
    
    # Slashings
    slashing_status = "✅ Pass" if total_slashings == 0 else "❌ Fail"
    section.append(f"| Total Slashings | {total_slashings} | 0 | {slashing_status} | beaconcha.in |")
    
    # Minimum Balance
    if min_balance_eth is not None:
        balance_status = "✅ Pass" if min_balance_eth >= THRESHOLDS['min_balance_eth'] else "❌ Fail"
        section.append(f"| Minimum Balance | {min_balance_eth:.4f} ETH | ≥{THRESHOLDS['min_balance_eth']} ETH | {balance_status} | beaconcha.in |")
    else:
        section.append(f"| Minimum Balance | No data | ≥{THRESHOLDS['min_balance_eth']} ETH | ⚠️ N/A | beaconcha.in |")
    
    # Attestation Inclusion Rate
    if avg_uptime_pct is not None:
        uptime_status = "✅ Pass" if avg_uptime_pct > THRESHOLDS['min_attestation_inclusion_rate'] else "❌ Fail"
        section.append(f"| Attestation Inclusion Rate | {avg_uptime_pct:.1f}% | >{THRESHOLDS['min_attestation_inclusion_rate']}% | {uptime_status} | rated.network (uptime) |")
    else:
        section.append(f"| Attestation Inclusion Rate | No data | >{THRESHOLDS['min_attestation_inclusion_rate']}% | ⚠️ N/A | rated.network (uptime) |")
    
    # Attestation Correctness
    if avg_correctness_pct is not None:
        correctness_status = "✅ Pass" if avg_correctness_pct > THRESHOLDS['min_attestation_correctness_rate'] else "❌ Fail"
        section.append(f"| Attestation Correctness | {avg_correctness_pct:.1f}% | >{THRESHOLDS['min_attestation_correctness_rate']}% | {correctness_status} | rated.network |")
    else:
        section.append(f"| Attestation Correctness | No data | >{THRESHOLDS['min_attestation_correctness_rate']}% | ⚠️ N/A | rated.network |")
    
    # Block Production
    if avg_block_production_pct is not None:
        production_status = "✅ Pass" if avg_block_production_pct > THRESHOLDS['min_block_production_rate'] else "❌ Fail"
        section.append(f"| Block Production Rate | {avg_block_production_pct:.1f}% | >{THRESHOLDS['min_block_production_rate']}% | {production_status} | rated.network ({len(validators_with_proposer_duties)} validator(s) with duties) |")
    elif rated_validator_stats:
        section.append(f"| Block Production Rate | No duties | >{THRESHOLDS['min_block_production_rate']}% | ➖ N/A | rated.network |")
    else:
        section.append(f"| Block Production Rate | No data | >{THRESHOLDS['min_block_production_rate']}% | ⚠️ N/A | rated.network |")
    
    section.append("")
    
    if validators_missing_balance > 0:
        section.append(
            f"**Note:** Balance data unavailable for {validators_missing_balance} validator(s). "
            "Minimum balance requirement could not be verified for these validators.\n"
        )
    
    return section


def _generate_aggregate_metrics_section(
    bc_stats: Optional[Dict[str, Any]],
    rated_stats: Optional[Dict[str, Any]],
    attestation_stats: Optional[Dict[str, Any]],
    proposal_stats: Optional[Dict[str, Any]]
) -> List[str]:
    """Generate the aggregate performance metrics section.
    
    Args:
        bc_stats: BeaconChain aggregate statistics
        rated_stats: Rated.network aggregate statistics
        attestation_stats: Attestation aggregate statistics
        proposal_stats: Proposal aggregate statistics
        
    Returns:
        List of report lines for the aggregate metrics section
    """
    section = []
    
    section.append("## Detailed Performance Metrics\n")
    
    # BeaconChain metrics
    if bc_stats:
        section.append("### beaconcha.in Data\n")
        section.append(f"- **Proposed Blocks**: {bc_stats['total_proposed_blocks']:,}")
        section.append(f"- **Missed Blocks**: {bc_stats['total_missed_blocks']:,}")
        section.append(f"- **Missed Attestations**: {bc_stats['total_missed_attestations']:,}")
        section.append(f"- **Missed Sync**: {bc_stats['total_missed_sync']:,}")
        section.append(f"- **Total Slashings**: {bc_stats['total_slashings']:,}")
        section.append("")
    
    # Rated.network metrics
    if rated_stats:
        section.append("### rated.network Effectiveness\n")
        section.append(f"- **Avg Validator Effectiveness**: {rated_stats['avg_validator_effectiveness']:.2f}%")
        section.append(f"- **Avg Uptime**: {rated_stats['avg_uptime']:.2f}%")
        section.append(f"- **Avg Correctness**: {rated_stats['avg_correctness']:.2f}%")
        section.append(f"- **Avg Inclusion Delay**: {rated_stats['avg_inclusion_delay']:.2f}")
        section.append("")
    
    # Attestation metrics
    if attestation_stats:
        section.append("### Attestation Performance\n")
        section.append(f"- **Avg Attester Effectiveness**: {attestation_stats['avg_attester_effectiveness']:.2f}%")
        section.append(f"- **Total Missed**: {attestation_stats['total_missed']:,}")
        section.append(f"- **Wrong Head Votes**: {attestation_stats['total_wrong_head']:,}")
        section.append(f"- **Wrong Target Votes**: {attestation_stats['total_wrong_target']:,}")
        section.append(f"- **Late Head Votes**: {attestation_stats['total_late_head']:,}")
        section.append("")
    
    # Proposal metrics
    if proposal_stats:
        section.append("### Block Proposal Performance\n")
        section.append(f"- **Total Duties**: {proposal_stats['total_duties']:,}")
        section.append(f"- **Blocks Proposed**: {proposal_stats['total_proposed']:,}")
        section.append(f"- **Effectiveness**: {proposal_stats['effectiveness']:.1f}%")
        section.append(f"- **Empty Blocks**: {proposal_stats['total_empty']:,}")
        if proposal_stats['total_proposed'] > 0:
            section.append(f"- **Empty Rate**: {proposal_stats['empty_rate']:.1f}%")
        section.append(f"- **Missed Proposals**: {proposal_stats['total_missed']:,}")
        section.append("")
    
    return section


def _generate_per_validator_table(
    all_validator_indices: set,
    index_to_pubkey: Dict[int, str],
    bc_validator_stats: Dict[int, Dict[str, Any]],
    rated_validator_stats: Dict[int, Dict[str, Any]],
    attestation_validators_data: Dict[int, List[Dict[str, Any]]],
    proposal_validators_data: Dict[int, List[Dict[str, Any]]]
) -> List[str]:
    """Generate the per-validator performance table.
    
    Args:
        all_validator_indices: Set of all validator indices to include
        index_to_pubkey: Mapping of validator index to pubkey
        bc_validator_stats: BeaconChain stats by validator
        rated_validator_stats: Rated.network stats by validator
        attestation_validators_data: Attestation data by validator
        proposal_validators_data: Proposal data by validator
        
    Returns:
        List of report lines for the per-validator table
    """
    section = []
    
    section.append("### Per-Validator Performance\n")
    section.append(
        "| Validator Pubkey | Index | Val Eff % | Att Eff % | Prop Eff % | Uptime % | "
        "Correctness % | Incl Delay | Missed Att | Missed Blocks | Missed Sync | "
        "Proposed | Slashings | Days | Min Balance |"
    )
    section.append(
        "|------------------|-------|-----------|-----------|------------|----------|"
        "---------------|------------|------------|---------------|-------------|"
        "----------|-----------|------|-------------|"
    )
    
    for idx in sorted(all_validator_indices):
        pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
        
        # Get stats from all sources
        bc_stats = bc_validator_stats.get(idx, {})
        rated_stats = rated_validator_stats.get(idx, {})
        
        # Get attestation aggregates if available
        att_effectiveness = "N/A"
        if idx in attestation_validators_data:
            att_records = attestation_validators_data[idx]
            if att_records:
                avg_att_eff = sum(r.get('attesterEffectiveness', 0) for r in att_records) / len(att_records)
                att_effectiveness = f"{avg_att_eff:.1f}"
        
        # Get proposal effectiveness if available
        prop_effectiveness = "N/A"
        if idx in proposal_validators_data:
            prop_records = proposal_validators_data[idx]
            if prop_records:
                total_duties = sum(r.get('proposerDutiesCount', 0) for r in prop_records)
                total_proposed = sum(r.get('proposedCount', 0) for r in prop_records)
                if total_duties > 0:
                    prop_effectiveness = f"{(total_proposed / total_duties * 100):.1f}"
        
        # Format all metrics
        val_effectiveness = f"{rated_stats.get('avg_effectiveness', 0):.1f}" if rated_stats else "N/A"
        uptime = f"{rated_stats.get('avg_uptime', 0)*100:.1f}" if rated_stats else "N/A"
        correctness = f"{rated_stats.get('avg_correctness', 0)*100:.1f}" if rated_stats else "N/A"
        incl_delay = f"{rated_stats.get('avg_inclusion_delay', 0):.2f}" if rated_stats else "N/A"
        
        missed_att = bc_stats.get('missed_attestations', 0) if bc_stats else 0
        missed_blocks = bc_stats.get('missed_blocks', 0) if bc_stats else 0
        missed_sync = bc_stats.get('missed_sync', 0) if bc_stats else 0
        proposed = bc_stats.get('proposed_blocks', 0) if bc_stats else 0
        slashings = bc_stats.get('slashings', 0) if bc_stats else 0
        days = max(bc_stats.get('days', 0), rated_stats.get('days', 0)) if (bc_stats or rated_stats) else 0
        
        # Calculate minimum balance from bc_stats
        min_balance = "N/A"
        if bc_stats:
            lowest_balance = bc_stats.get('lowest_balance', float('inf'))
            if lowest_balance != float('inf') and lowest_balance > 0:
                min_balance = f"{lowest_balance / 1e9:.4f}"
            else:
                # Try start/end balance if lowest_balance not available
                balances = []
                if bc_stats.get('start_balance') and bc_stats.get('start_balance') > 0:
                    balances.append(bc_stats.get('start_balance'))
                if bc_stats.get('end_balance') and bc_stats.get('end_balance') > 0:
                    balances.append(bc_stats.get('end_balance'))
                if balances:
                    min_balance = f"{min(balances) / 1e9:.4f}"
        
        section.append(
            f"| {pubkey} | {idx} | {val_effectiveness} | {att_effectiveness} | "
            f"{prop_effectiveness} | {uptime} | {correctness} | {incl_delay} | "
            f"{missed_att} | {missed_blocks} | {missed_sync} | {proposed} | "
            f"{slashings} | {days} | {min_balance} |"
        )
    
    section.append("")
    
    return section