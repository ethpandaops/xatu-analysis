"""Performance summary module for validator performance analysis.

This module provides functions to analyze validator performance data from multiple sources
(BeaconChain, Rated.network) and generate performance summaries with critical issue detection.
"""
import streamlit as st
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# Performance thresholds
THRESHOLDS = {
    'min_attestation_inclusion_rate': 95.0,  # >95%
    'min_attestation_correctness_rate': 98.0,  # >98%
    'min_block_production_rate': 95.0,  # >95%
    'min_balance_eth': 31.95,  # Minimum balance in ETH
    'max_allowed_slashings': 0  # No slashings allowed
}


def analyze_beaconchain_data(stats_data: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Extract BeaconChain data analysis logic.
    
    Analyzes daily stats from BeaconChain API to aggregate validator performance metrics.
    
    Args:
        stats_data: List of daily stats from BeaconChain API
        
    Returns:
        Dictionary mapping validator index to aggregated stats including:
        - missed_blocks: Total missed blocks
        - missed_attestations: Total missed attestations  
        - missed_sync: Total missed sync committee duties
        - proposed_blocks: Total proposed blocks
        - slashings: Total slashing events
        - days: Number of days analyzed
        - start_balance: First recorded balance
        - end_balance: Last recorded balance
        - lowest_balance: Lowest balance recorded
    """
    bc_validator_stats = {}
    
    for stat in stats_data:
        idx = stat.get('validatorindex', 0)
        if idx not in bc_validator_stats:
            bc_validator_stats[idx] = {
                'missed_blocks': 0,
                'missed_attestations': 0,
                'missed_sync': 0,
                'proposed_blocks': 0,
                'slashings': 0,
                'days': 0,
                'start_balance': None,
                'end_balance': None,
                'lowest_balance': float('inf')
            }
        
        # Aggregate daily stats
        bc_validator_stats[idx]['missed_blocks'] += stat.get('missed_blocks', 0)
        bc_validator_stats[idx]['missed_attestations'] += stat.get('missed_attestations', 0)
        bc_validator_stats[idx]['missed_sync'] += stat.get('missed_sync', 0)
        bc_validator_stats[idx]['proposed_blocks'] += stat.get('proposed_blocks', 0)
        bc_validator_stats[idx]['slashings'] += (
            stat.get('attester_slashings', 0) + stat.get('proposer_slashings', 0)
        )
        bc_validator_stats[idx]['days'] += 1
        
        # Track first start balance
        if bc_validator_stats[idx]['start_balance'] is None and stat.get('start_balance') is not None:
            bc_validator_stats[idx]['start_balance'] = stat.get('start_balance')
        
        # Keep the most recent end balance
        if stat.get('end_balance') is not None:
            bc_validator_stats[idx]['end_balance'] = stat.get('end_balance')
        
        # Track lowest of start and end balances
        if stat.get('start_balance') is not None and stat.get('start_balance') > 0:
            bc_validator_stats[idx]['lowest_balance'] = min(
                bc_validator_stats[idx]['lowest_balance'], 
                stat.get('start_balance')
            )
        if stat.get('end_balance') is not None and stat.get('end_balance') > 0:
            bc_validator_stats[idx]['lowest_balance'] = min(
                bc_validator_stats[idx]['lowest_balance'], 
                stat.get('end_balance')
            )
    
    return bc_validator_stats


def analyze_rated_data(effectiveness_data: Dict[int, List[Dict[str, Any]]]) -> Dict[int, Dict[str, Any]]:
    """Extract Rated data analysis logic.
    
    Analyzes effectiveness data from Rated.network API to calculate average performance metrics.
    
    Args:
        effectiveness_data: Dictionary mapping validator index to list of daily effectiveness records
        
    Returns:
        Dictionary mapping validator index to aggregated stats including:
        - avg_effectiveness: Average validator effectiveness
        - avg_attester_effectiveness: Average attester effectiveness
        - avg_proposer_effectiveness: Average proposer effectiveness (only for days with duties)
        - total_proposer_duties: Number of days with proposer duties
        - avg_uptime: Average uptime percentage
        - avg_correctness: Average attestation correctness
        - avg_inclusion_delay: Average inclusion delay in slots
        - days: Number of days analyzed
    """
    rated_validator_stats = {}
    
    for idx, records in effectiveness_data.items():
        total_days = len(records)
        
        if total_days == 0:
            continue
            
        # Calculate average effectiveness
        avg_effectiveness = sum(r.get('validatorEffectiveness', 0) for r in records) / total_days
        avg_attester_effectiveness = sum(r.get('attesterEffectiveness', 0) for r in records) / total_days
        
        # Calculate proposer effectiveness only for days with proposer duties
        proposer_days = [r for r in records if r.get('proposerEffectiveness') is not None]
        avg_proposer_effectiveness = (
            sum(r.get('proposerEffectiveness', 0) for r in proposer_days) / len(proposer_days) 
            if proposer_days else 0
        )
        total_proposer_duties = len(proposer_days)
        
        # Calculate other metrics
        avg_uptime = sum(r.get('uptime', 0) for r in records) / total_days
        avg_correctness = sum(r.get('avgCorrectness', 0) for r in records) / total_days
        avg_inclusion_delay = sum(r.get('avgInclusionDelay', 0) for r in records) / total_days
        
        rated_validator_stats[idx] = {
            'avg_effectiveness': avg_effectiveness,
            'avg_attester_effectiveness': avg_attester_effectiveness,
            'avg_proposer_effectiveness': avg_proposer_effectiveness,
            'total_proposer_duties': total_proposer_duties,
            'avg_uptime': avg_uptime,
            'avg_correctness': avg_correctness,
            'avg_inclusion_delay': avg_inclusion_delay,
            'days': total_days
        }
    
    return rated_validator_stats


def check_critical_issues(
    bc_validator_stats: Dict[int, Dict[str, Any]], 
    rated_validator_stats: Dict[int, Dict[str, Any]], 
    index_to_pubkey: Dict[int, str]
) -> List[Dict[str, Any]]:
    """Extract critical issues logic from analyzed data.
    
    Checks validator performance against defined thresholds to identify critical issues.
    
    Args:
        bc_validator_stats: Analyzed BeaconChain validator stats
        rated_validator_stats: Analyzed Rated.network validator stats
        index_to_pubkey: Mapping of validator index to pubkey
        
    Returns:
        List of critical issues, each containing:
        - Validator: Validator pubkey
        - Index: Validator index
        - Issue: Description of the issue
        - Value: Current value
        - Threshold: Required threshold
        - Status: Issue severity ('Critical' or 'Below Threshold')
    """
    critical_data = []
    
    # Check for slashings (not allowed)
    for idx, stats in bc_validator_stats.items():
        if stats['slashings'] > THRESHOLDS['max_allowed_slashings']:
            pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
            critical_data.append({
                'Validator': pubkey,
                'Index': idx,
                'Issue': 'Slashing Event',
                'Value': f"{stats['slashings']} slashing(s)",
                'Threshold': 'Not allowed',
                'Status': 'Critical'
            })
    
    # Check minimum balance (31.95 ETH) using start/end balance data
    for idx, stats in bc_validator_stats.items():
        # Check if we have valid balance data
        if stats['lowest_balance'] != float('inf'):
            lowest_balance_eth = stats['lowest_balance'] / 1e9
            if lowest_balance_eth < THRESHOLDS['min_balance_eth']:
                pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                critical_data.append({
                    'Validator': pubkey,
                    'Index': idx,
                    'Issue': 'Below Minimum Balance',
                    'Value': f"{lowest_balance_eth:.3f} ETH",
                    'Threshold': f"≥{THRESHOLDS['min_balance_eth']} ETH",
                    'Status': 'Critical'
                })
        # Alternative check using end balance if available
        elif stats['end_balance'] is not None:
            end_balance_eth = stats['end_balance'] / 1e9
            if end_balance_eth < THRESHOLDS['min_balance_eth']:
                pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                critical_data.append({
                    'Validator': pubkey,
                    'Index': idx,
                    'Issue': 'Below Minimum Balance',
                    'Value': f"{end_balance_eth:.3f} ETH",
                    'Threshold': f"≥{THRESHOLDS['min_balance_eth']} ETH",
                    'Status': 'Critical'
                })
    
    # Check attestation inclusion rate using uptime (>95%)
    for idx, stats in rated_validator_stats.items():
        uptime_pct = stats['avg_uptime'] * 100  # Convert from decimal to percentage
        if uptime_pct < THRESHOLDS['min_attestation_inclusion_rate']:
            pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
            critical_data.append({
                'Validator': pubkey,
                'Index': idx,
                'Issue': 'Low Attestation Inclusion Rate',
                'Value': f"{uptime_pct:.1f}%",
                'Threshold': f">{THRESHOLDS['min_attestation_inclusion_rate']}%",
                'Status': 'Below Threshold'
            })
    
    # Check attestation correctness rate (>98%)
    for idx, stats in rated_validator_stats.items():
        correctness_pct = stats['avg_correctness'] * 100
        if correctness_pct < THRESHOLDS['min_attestation_correctness_rate']:
            pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
            critical_data.append({
                'Validator': pubkey,
                'Index': idx,
                'Issue': 'Low Attestation Correctness',
                'Value': f"{correctness_pct:.1f}%",
                'Threshold': f">{THRESHOLDS['min_attestation_correctness_rate']}%",
                'Status': 'Below Threshold'
            })
    
    # Check block production effectiveness (>95%)
    for idx, stats in rated_validator_stats.items():
        # Only check if validator had proposer duties
        if stats.get('total_proposer_duties', 0) > 0 and stats['avg_proposer_effectiveness'] < THRESHOLDS['min_block_production_rate']:
            pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
            critical_data.append({
                'Validator': pubkey,
                'Index': idx,
                'Issue': 'Low Block Production Rate',
                'Value': f"{stats['avg_proposer_effectiveness']:.1f}%",
                'Threshold': f">{THRESHOLDS['min_block_production_rate']}%",
                'Status': 'Below Threshold'
            })
    
    return critical_data


def calculate_aggregate_metrics(
    bc_validator_stats: Dict[int, Dict[str, Any]], 
    rated_validator_stats: Dict[int, Dict[str, Any]],
    attestation_results: Optional[List[Dict[str, Any]]] = None,
    proposal_results: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Extract aggregate metrics calculation from multiple data sources.
    
    Calculates aggregate performance metrics across all validators.
    
    Args:
        bc_validator_stats: Analyzed BeaconChain validator stats
        rated_validator_stats: Analyzed Rated.network validator stats
        attestation_results: Optional list of attestation performance data
        proposal_results: Optional list of proposal performance data
        
    Returns:
        Dictionary containing aggregate metrics:
        - beaconchain_metrics: Aggregated BeaconChain metrics
        - rated_metrics: Aggregated Rated.network effectiveness metrics
        - attestation_metrics: Aggregated attestation performance metrics
        - proposal_metrics: Aggregated proposal performance metrics
    """
    metrics = {}
    
    # BeaconChain totals
    if bc_validator_stats:
        bc_total_missed_blocks = sum(stats.get('missed_blocks', 0) for stats in bc_validator_stats.values())
        bc_total_missed_attestations = sum(stats.get('missed_attestations', 0) for stats in bc_validator_stats.values())
        bc_total_missed_sync = sum(stats.get('missed_sync', 0) for stats in bc_validator_stats.values())
        bc_total_slashings = sum(stats.get('slashings', 0) for stats in bc_validator_stats.values())
        bc_total_proposed = sum(stats.get('proposed_blocks', 0) for stats in bc_validator_stats.values())
        
        metrics['beaconchain_metrics'] = {
            'total_proposed_blocks': bc_total_proposed,
            'total_missed_blocks': bc_total_missed_blocks,
            'total_missed_attestations': bc_total_missed_attestations,
            'total_missed_sync': bc_total_missed_sync,
            'total_slashings': bc_total_slashings
        }
    
    # Rated.network averages
    if rated_validator_stats:
        all_effectiveness = []
        all_uptime = []
        all_correctness = []
        all_inclusion_delay = []
        
        for idx, stats in rated_validator_stats.items():
            all_effectiveness.append(stats['avg_effectiveness'])
            all_uptime.append(stats['avg_uptime'])
            all_correctness.append(stats['avg_correctness'])
            all_inclusion_delay.append(stats['avg_inclusion_delay'])
        
        if all_effectiveness:
            metrics['rated_metrics'] = {
                'avg_validator_effectiveness': sum(all_effectiveness) / len(all_effectiveness),
                'avg_uptime': sum(all_uptime) / len(all_uptime) * 100,
                'avg_correctness': sum(all_correctness) / len(all_correctness) * 100,
                'avg_inclusion_delay': sum(all_inclusion_delay) / len(all_inclusion_delay)
            }
    
    # Attestation metrics
    if attestation_results:
        total_attest_days = len(attestation_results)
        avg_att_eff = sum(r.get("attesterEffectiveness", 0) for r in attestation_results) / total_attest_days if total_attest_days > 0 else 0
        total_att_missed = sum(r.get("sumMissedAttestations", 0) for r in attestation_results)
        total_att_wrong_head = sum(r.get("sumWrongHeadVotes", 0) for r in attestation_results)
        total_att_wrong_target = sum(r.get("sumWrongTargetVotes", 0) for r in attestation_results)
        total_att_late_head = sum(r.get("sumLateHeadVotes", 0) for r in attestation_results)
        
        metrics['attestation_metrics'] = {
            'avg_attester_effectiveness': avg_att_eff,
            'total_missed': total_att_missed,
            'total_wrong_head': total_att_wrong_head,
            'total_wrong_target': total_att_wrong_target,
            'total_late_head': total_att_late_head
        }
    
    # Proposal metrics
    if proposal_results:
        total_prop_duties = sum(r.get("proposerDutiesCount", 0) for r in proposal_results)
        total_prop_proposed = sum(r.get("proposedCount", 0) for r in proposal_results)
        total_prop_empty = sum(r.get("executionProposedEmptyCount", 0) for r in proposal_results)
        prop_effectiveness = (total_prop_proposed / total_prop_duties * 100) if total_prop_duties > 0 else 0
        
        metrics['proposal_metrics'] = {
            'total_duties': total_prop_duties,
            'total_proposed': total_prop_proposed,
            'effectiveness': prop_effectiveness,
            'total_empty': total_prop_empty,
            'empty_rate': (total_prop_empty / total_prop_proposed * 100) if total_prop_proposed > 0 else 0,
            'total_missed': total_prop_duties - total_prop_proposed
        }
    
    return metrics


def render_performance_summary(
    pubkey_to_index: Dict[str, int],
    beaconchain_results: Optional[Dict[str, Any]] = None,
    effectiveness_data: Optional[Dict[int, List[Dict[str, Any]]]] = None,
    attestation_data: Optional[List[Dict[str, Any]]] = None,
    proposal_data: Optional[List[Dict[str, Any]]] = None
) -> None:
    """Main function that orchestrates the performance summary rendering.
    
    Analyzes data from multiple sources and renders a comprehensive performance summary
    using Streamlit components.
    
    Args:
        pubkey_to_index: Mapping of validator pubkey to index
        beaconchain_results: Optional BeaconChain API results containing 'stats_data'
        effectiveness_data: Optional Rated.network effectiveness data by validator
        attestation_data: Optional attestation performance data
        proposal_data: Optional proposal performance data
    """
    # Check if we have any data
    has_beaconchain = beaconchain_results and 'stats_data' in beaconchain_results
    has_rated = effectiveness_data is not None
    
    if not has_beaconchain and not has_rated:
        st.warning("No performance data available to summarize.")
        return
    
    # Create reverse mapping for index to pubkey
    index_to_pubkey = {idx: pubkey for pubkey, idx in pubkey_to_index.items()}
    
    # Analyze data from different sources
    bc_validator_stats = {}
    if has_beaconchain:
        bc_validator_stats = analyze_beaconchain_data(beaconchain_results['stats_data'])
    
    rated_validator_stats = {}
    if has_rated:
        rated_validator_stats = analyze_rated_data(effectiveness_data)
    
    # Calculate aggregated performance metrics
    st.markdown("### 🎯 Aggregated Performance")
    
    # Calculate aggregate values
    total_validators = len(set(list(bc_validator_stats.keys()) + list(rated_validator_stats.keys())))
    
    # Total slashings
    total_slashings = sum(stats.get('slashings', 0) for stats in bc_validator_stats.values())
    
    # Minimum balance across all validators
    min_balance_eth = float('inf')
    validators_with_balance = 0
    for stats in bc_validator_stats.values():
        if stats['lowest_balance'] != float('inf'):
            min_balance_eth = min(min_balance_eth, stats['lowest_balance'] / 1e9)
            validators_with_balance += 1
        elif stats['end_balance'] is not None:
            min_balance_eth = min(min_balance_eth, stats['end_balance'] / 1e9)
            validators_with_balance += 1
    
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
    
    # Display the aggregated metrics
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Slashings
        slashing_status = "❌" if total_slashings > 0 else "✅"
        st.metric(
            "Total Slashings",
            f"{slashing_status} {total_slashings}",
            delta=f"Threshold: 0" if total_slashings > 0 else None,
            delta_color="inverse" if total_slashings > 0 else "off",
            help="Total slashing events across all validators. Must be 0."
        )
        
        # Minimum Balance
        if min_balance_eth is not None:
            balance_status = "❌" if min_balance_eth < THRESHOLDS['min_balance_eth'] else "✅"
            st.metric(
                "Minimum Balance",
                f"{balance_status} {min_balance_eth:.4f} ETH",
                delta=f"Threshold: ≥{THRESHOLDS['min_balance_eth']} ETH" if min_balance_eth < THRESHOLDS['min_balance_eth'] else None,
                delta_color="inverse" if min_balance_eth < THRESHOLDS['min_balance_eth'] else "off",
                help="Lowest balance found across all validators"
            )
        else:
            st.metric(
                "Minimum Balance",
                "⚠️ No data",
                help="Balance data not available"
            )
    
    with col2:
        # Attestation Inclusion Rate (Uptime)
        if avg_uptime_pct is not None:
            uptime_status = "❌" if avg_uptime_pct < THRESHOLDS['min_attestation_inclusion_rate'] else "✅"
            st.metric(
                "Attestation Inclusion Rate",
                f"{uptime_status} {avg_uptime_pct:.1f}%",
                delta=f"Threshold: >{THRESHOLDS['min_attestation_inclusion_rate']}%" if avg_uptime_pct < THRESHOLDS['min_attestation_inclusion_rate'] else None,
                delta_color="inverse" if avg_uptime_pct < THRESHOLDS['min_attestation_inclusion_rate'] else "off",
                help="Average uptime across all validators (from rated.network). Percentage of epochs where validators performed at least one duty."
            )
        else:
            st.metric(
                "Attestation Inclusion Rate",
                "⚠️ No data",
                help="rated.network data not available"
            )
        
        # Attestation Correctness
        if avg_correctness_pct is not None:
            correctness_status = "❌" if avg_correctness_pct < THRESHOLDS['min_attestation_correctness_rate'] else "✅"
            st.metric(
                "Attestation Correctness",
                f"{correctness_status} {avg_correctness_pct:.1f}%",
                delta=f"Threshold: >{THRESHOLDS['min_attestation_correctness_rate']}%" if avg_correctness_pct < THRESHOLDS['min_attestation_correctness_rate'] else None,
                delta_color="inverse" if avg_correctness_pct < THRESHOLDS['min_attestation_correctness_rate'] else "off",
                help="Average correctness of attestations across all validators (from rated.network). Measures accuracy of source, target, and head votes."
            )
        else:
            st.metric(
                "Attestation Correctness",
                "⚠️ No data",
                help="rated.network data not available"
            )
    
    with col3:
        # Block Production
        if avg_block_production_pct is not None:
            production_status = "❌" if avg_block_production_pct < THRESHOLDS['min_block_production_rate'] else "✅"
            st.metric(
                "Block Production Rate",
                f"{production_status} {avg_block_production_pct:.1f}%",
                delta=f"Threshold: >{THRESHOLDS['min_block_production_rate']}%" if avg_block_production_pct < THRESHOLDS['min_block_production_rate'] else None,
                delta_color="inverse" if avg_block_production_pct < THRESHOLDS['min_block_production_rate'] else "off",
                help=f"Average block production rate for validators with proposer duties (from rated.network). Based on {len(validators_with_proposer_duties)} validator(s) with duties."
            )
        elif rated_validator_stats:
            st.metric(
                "Block Production Rate",
                "➖ No duties",
                help="No validators had block proposal duties in this period"
            )
        else:
            st.metric(
                "Block Production Rate",
                "⚠️ No data",
                help="rated.network data not available"
            )
    
    # Check for validators with missing balance data
    validators_missing_balance = sum(
        1 for stats in bc_validator_stats.values() 
        if stats['lowest_balance'] == float('inf') and stats['end_balance'] is None
    )
    if validators_missing_balance > 0:
        st.info(
            f"**Note:** Balance data unavailable for {validators_missing_balance} validator(s). "
            "Minimum balance requirement could not be verified for these validators."
        )
    
    # Calculate aggregate metrics
    aggregate_metrics = calculate_aggregate_metrics(
        bc_validator_stats, 
        rated_validator_stats,
        attestation_data,
        proposal_data
    )
    
    # Display detailed performance metrics
    st.markdown("### 📊 Detailed Performance Metrics")
    
    # BeaconChain metrics
    if 'beaconchain_metrics' in aggregate_metrics:
        st.markdown("#### beaconcha.in Data")
        col1, col2, col3, col4 = st.columns(4)
        bc_metrics = aggregate_metrics['beaconchain_metrics']
        
        with col1:
            st.metric("Proposed Blocks", f"{bc_metrics['total_proposed_blocks']:,}")
            st.metric("Missed Blocks", f"{bc_metrics['total_missed_blocks']:,}")
        with col2:
            st.metric("Missed Attestations", f"{bc_metrics['total_missed_attestations']:,}")
            st.metric("Missed Sync", f"{bc_metrics['total_missed_sync']:,}")
        with col3:
            st.metric("Total Slashings", f"{bc_metrics['total_slashings']:,}")
    
    # Rated.network effectiveness metrics
    if 'rated_metrics' in aggregate_metrics:
        st.markdown("#### rated.network Effectiveness")
        col1, col2, col3, col4 = st.columns(4)
        rated_metrics = aggregate_metrics['rated_metrics']
        
        with col1:
            st.metric(
                "Avg Validator Effectiveness", 
                f"{rated_metrics['avg_validator_effectiveness']:.2f}%",
                help="Average validator effectiveness across all validators"
            )
        with col2:
            st.metric(
                "Avg Uptime", 
                f"{rated_metrics['avg_uptime']:.2f}%",
                help="Average uptime percentage"
            )
        with col3:
            st.metric(
                "Avg Correctness", 
                f"{rated_metrics['avg_correctness']:.2f}%",
                help="Average attestation correctness"
            )
        with col4:
            st.metric(
                "Avg Inclusion Delay", 
                f"{rated_metrics['avg_inclusion_delay']:.2f}",
                help="Average inclusion delay in slots"
            )
    
    # Attestation performance metrics
    if 'attestation_metrics' in aggregate_metrics:
        st.markdown("#### Attestation Performance")
        col1, col2, col3, col4 = st.columns(4)
        att_metrics = aggregate_metrics['attestation_metrics']
        
        with col1:
            st.metric(
                "Avg Attester Effectiveness", 
                f"{att_metrics['avg_attester_effectiveness']:.2f}%",
                help="Average effectiveness across all attestations"
            )
            st.metric(
                "Total Missed", 
                f"{att_metrics['total_missed']:,}",
                help="Total missed attestations"
            )
        with col2:
            st.metric(
                "Wrong Head Votes", 
                f"{att_metrics['total_wrong_head']:,}",
                help="Attestations with incorrect head vote"
            )
        with col3:
            st.metric(
                "Wrong Target Votes", 
                f"{att_metrics['total_wrong_target']:,}",
                help="Attestations with incorrect target checkpoint"
            )
            st.metric(
                "Late Head Votes", 
                f"{att_metrics['total_late_head']:,}",
                help="Attestations submitted late but voting correctly"
            )
        with col4:
            pass
    
    # Block proposal performance metrics
    if 'proposal_metrics' in aggregate_metrics:
        st.markdown("#### Block Proposal Performance")
        col1, col2, col3, col4 = st.columns(4)
        prop_metrics = aggregate_metrics['proposal_metrics']
        
        with col1:
            st.metric(
                "Total Duties", 
                f"{prop_metrics['total_duties']:,}",
                help="Times randomly selected to propose blocks"
            )
            st.metric(
                "Blocks Proposed", 
                f"{prop_metrics['total_proposed']:,}",
                help="Successfully proposed blocks"
            )
        with col2:
            st.metric(
                "Effectiveness", 
                f"{prop_metrics['effectiveness']:.1f}%",
                help="Percentage of assigned blocks successfully proposed. Target: 100%"
            )
        with col3:
            st.metric(
                "Empty Blocks", 
                f"{prop_metrics['total_empty']:,}",
                help="Blocks proposed without execution payload"
            )
            if prop_metrics['total_proposed'] > 0:
                st.metric(
                    "Empty Rate", 
                    f"{prop_metrics['empty_rate']:.1f}%",
                    help="Percentage of proposed blocks that were empty"
                )
        with col4:
            st.metric(
                "Missed Proposals", 
                f"{prop_metrics['total_missed']:,}",
                help="Failed to propose when selected (severe issue)"
            )
    
    st.caption("[beaconcha.in](https://beaconcha.in) | [rated.network](https://www.rated.network)")