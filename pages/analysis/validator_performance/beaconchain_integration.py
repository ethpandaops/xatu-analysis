"""BeaconChain API integration for validator performance analysis."""
import streamlit as st
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from shared import BeaconchainClient


def fetch_beaconchain_stats(
    client: BeaconchainClient,
    pubkey_to_index: Dict[str, int],
    time_range: Optional[Tuple[datetime, datetime]],
    excluded_ranges: List[Dict[str, Any]],
    max_validators: int = 50
) -> Dict[str, Any]:
    """Fetch validator statistics from BeaconChain API.
    
    Args:
        client: BeaconchainClient instance
        pubkey_to_index: Mapping of validator pubkeys to indices
        time_range: Tuple of (start_date, end_date) for the query
        excluded_ranges: List of date ranges to exclude from results
        max_validators: Maximum number of validators to fetch (default: 50)
        
    Returns:
        Dictionary containing fetched stats data and metadata
    """
    # Get ALL validator indices
    all_indices = list(pubkey_to_index.values())
    
    # Calculate start_day and end_day based on time range
    # BeaconChain API uses epoch days where day 1 = Dec 1, 2020 (mainnet genesis) in UTC
    genesis_date = datetime(2020, 12, 1)  # UTC
    
    if time_range:
        start_date, end_date = time_range
        # Also keep date strings for display
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')
    else:
        # Default to last 7 days
        today = datetime.utcnow()
        end_date = today
        start_date = today - timedelta(days=7)
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')
    
    # Convert to epoch days for the FULL range
    start_day = (start_date - genesis_date).days + 1
    end_day = (end_date - genesis_date).days + 1
    
    # Ensure positive values
    start_day = max(1, start_day)
    end_day = max(1, end_day)
    
    # Collect all stats data
    all_stats_data = []
    unfiltered_count = 0
    
    # Process validators individually (stats endpoint requires individual calls)
    # Limit to reasonable number to avoid too many API calls
    max_validators = min(len(all_indices), max_validators)
    
    for i, idx in enumerate(all_indices[:max_validators]):
        # Get stats for the FULL date range
        stats = client.get_validator_stats(idx, start_day=start_day, end_day=end_day)
        if stats:
            for stat in stats:
                # Add validator index if not present
                stat_dict = stat.dict() if hasattr(stat, 'dict') else stat
                if isinstance(stat_dict, dict):
                    stat_dict['validatorindex'] = idx
                    unfiltered_count += 1
                    
                    # Default to including the record
                    should_include = True
                    
                    # Check if we need to filter based on exclusions
                    if excluded_ranges and 'day_start' in stat_dict:
                        day_date_str = stat_dict['day_start']  # Already truncated to YYYY-MM-DD in client
                        
                        # Check if this date falls within any excluded range
                        for exclusion in excluded_ranges:
                            exc_start_str = str(exclusion['start'])
                            exc_end_str = str(exclusion['end'])
                            
                            # Simple string comparison of YYYY-MM-DD dates
                            if exc_start_str <= day_date_str <= exc_end_str:
                                should_include = False
                                break
                    
                    # Add the record if it should be included
                    if should_include:
                        all_stats_data.append(stat_dict)
    
    # Show filtering info if applicable
    if excluded_ranges and unfiltered_count > len(all_stats_data):
        st.info(f"Filtered out {unfiltered_count - len(all_stats_data)} daily records due to date exclusions")
    
    return {
        'all_indices': all_indices,
        'max_validators': max_validators,
        'stats_data': all_stats_data,
        'unfiltered_count': unfiltered_count,
        'filtered_count': unfiltered_count - len(all_stats_data) if unfiltered_count > len(all_stats_data) else 0,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'error': None
    }


def process_beaconchain_data(stats_data: List[Dict[str, Any]], pubkey_to_index: Dict[str, int]) -> Dict[str, Any]:
    """Process BeaconChain statistics data for display.
    
    Args:
        stats_data: List of validator statistics dictionaries
        pubkey_to_index: Mapping of validator pubkeys to indices
        
    Returns:
        Dictionary containing processed data including validator groups and aggregated metrics
    """
    # Create reverse mapping from index to pubkey
    index_to_pubkey = {v: k for k, v in pubkey_to_index.items()}
    
    # Group by validator
    validator_groups = {}
    for stat in stats_data:
        idx = stat.get('validatorindex', 0)
        if idx not in validator_groups:
            validator_groups[idx] = []
        validator_groups[idx].append(stat)
    
    # Calculate totals across all validators
    total_validators = len(validator_groups)
    total_records = len(stats_data)
    
    # Sum up all stats
    overall_proposed = sum(s.get('proposed_blocks', 0) for s in stats_data)
    overall_missed_blocks = sum(s.get('missed_blocks', 0) for s in stats_data)
    overall_missed_attestations = sum(s.get('missed_attestations', 0) for s in stats_data)
    overall_missed_sync = sum(s.get('missed_sync', 0) for s in stats_data)
    overall_participated_sync = sum(s.get('participated_sync', 0) for s in stats_data)
    overall_orphaned_blocks = sum(s.get('orphaned_blocks', 0) for s in stats_data)
    overall_orphaned_attestations = sum(s.get('orphaned_attestations', 0) for s in stats_data)
    overall_orphaned_sync = sum(s.get('orphaned_sync', 0) for s in stats_data)
    overall_attester_slashings = sum(s.get('attester_slashings', 0) for s in stats_data)
    overall_proposer_slashings = sum(s.get('proposer_slashings', 0) for s in stats_data)
    overall_deposits = sum(s.get('deposits', 0) for s in stats_data)
    overall_withdrawals = sum(s.get('withdrawals', 0) for s in stats_data)
    overall_deposits_amount = sum(s.get('deposits_amount', 0) for s in stats_data) / 1e9
    overall_withdrawals_amount = sum(s.get('withdrawals_amount', 0) for s in stats_data) / 1e9
    
    # Calculate total balance change across all validators
    total_balance_change = 0
    for idx, validator_stats in validator_groups.items():
        sorted_stats = sorted(validator_stats, key=lambda x: x.get('day', 0))
        if sorted_stats:
            first_balance = sorted_stats[0].get('start_balance', 0) / 1e9 if sorted_stats[0].get('start_balance') else 0
            last_balance = sorted_stats[-1].get('end_balance', 0) / 1e9 if sorted_stats[-1].get('end_balance') else 0
            total_balance_change += (last_balance - first_balance)
    
    return {
        'index_to_pubkey': index_to_pubkey,
        'validator_groups': validator_groups,
        'total_validators': total_validators,
        'total_records': total_records,
        'overall_stats': {
            'proposed': overall_proposed,
            'missed_blocks': overall_missed_blocks,
            'missed_attestations': overall_missed_attestations,
            'missed_sync': overall_missed_sync,
            'participated_sync': overall_participated_sync,
            'orphaned_blocks': overall_orphaned_blocks,
            'orphaned_attestations': overall_orphaned_attestations,
            'orphaned_sync': overall_orphaned_sync,
            'attester_slashings': overall_attester_slashings,
            'proposer_slashings': overall_proposer_slashings,
            'deposits': overall_deposits,
            'withdrawals': overall_withdrawals,
            'deposits_amount': overall_deposits_amount,
            'withdrawals_amount': overall_withdrawals_amount,
            'total_balance_change': total_balance_change
        }
    }


def render_beaconchain_section(test_results: Dict[str, Any], pubkey_to_index: Dict[str, int]) -> None:
    """Render the BeaconChain statistics section of the dashboard.
    
    Args:
        test_results: Results from BeaconChain API fetch
        pubkey_to_index: Mapping of validator pubkeys to indices
    """
    with st.expander("beaconcha.in - Statistics", expanded=True):
        if test_results.get('error'):
            st.error(f"Error testing Beaconcha.in API: {test_results['error']}")
        else:
            max_validators = test_results.get('max_validators', 0)
            total_indices = len(test_results.get('all_indices', []))
            stats_data = test_results.get('stats_data', [])
            
            if stats_data:
                # Show filtering info if applicable
                filtered_count = test_results.get('filtered_count', 0)
                if filtered_count > 0:
                    st.info(f"Filtered out {filtered_count} daily records due to date exclusions")
                
                # Process the data
                processed_data = process_beaconchain_data(stats_data, pubkey_to_index)
                
                # Show summary
                st.subheader("Summary")
                
                # Display overall metrics
                overall_stats = processed_data['overall_stats']
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Validators", processed_data['total_validators'])
                    st.metric("Proposed Blocks", f"{overall_stats['proposed']:,}")
                    st.metric("Deposits", f"{overall_stats['deposits']:,}")
                with col2:
                    st.metric("Missed Blocks", f"{overall_stats['missed_blocks']:,}")
                    st.metric("Missed Attestations", f"{overall_stats['missed_attestations']:,}")
                    st.metric("Total Withdrawals", f"{overall_stats['withdrawals']:,}")
                with col3:
                    st.metric("Sync Participation", f"{overall_stats['participated_sync']:,}")
                    st.metric("Slashings", f"{overall_stats['attester_slashings'] + overall_stats['proposer_slashings']:,}")
                    st.metric("Orphaned Blocks", f"{overall_stats['orphaned_blocks']:,}")
                with col4:
                    st.metric("Orphaned Attestations", f"{overall_stats['orphaned_attestations']:,}")
                    st.metric("Total Withdrawals Amount", f"{overall_stats['withdrawals_amount']:.4f} ETH")
                
                # Per-validator summary in expander
                with st.expander("Per-Validator Summary", expanded=False):
                    agg_data = []
                    index_to_pubkey = processed_data['index_to_pubkey']
                    validator_groups = processed_data['validator_groups']
                    
                    for idx, validator_stats in validator_groups.items():
                        pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                        
                        # Sort by day to get first and last
                        sorted_stats = sorted(validator_stats, key=lambda x: x.get('day', 0))
                        
                        # Sum up stats
                        total_proposed = sum(s.get('proposed_blocks', 0) for s in validator_stats)
                        total_missed_blocks = sum(s.get('missed_blocks', 0) for s in validator_stats)
                        total_missed_attestations = sum(s.get('missed_attestations', 0) for s in validator_stats)
                        total_missed_sync = sum(s.get('missed_sync', 0) for s in validator_stats)
                        total_participated_sync = sum(s.get('participated_sync', 0) for s in validator_stats)
                        total_orphaned_blocks = sum(s.get('orphaned_blocks', 0) for s in validator_stats)
                        total_orphaned_attestations = sum(s.get('orphaned_attestations', 0) for s in validator_stats)
                        total_orphaned_sync = sum(s.get('orphaned_sync', 0) for s in validator_stats)
                        total_attester_slashings = sum(s.get('attester_slashings', 0) for s in validator_stats)
                        total_proposer_slashings = sum(s.get('proposer_slashings', 0) for s in validator_stats)
                        total_deposits = sum(s.get('deposits', 0) for s in validator_stats)
                        total_withdrawals = sum(s.get('withdrawals', 0) for s in validator_stats)
                        total_deposits_amount = sum(s.get('deposits_amount', 0) for s in validator_stats) / 1e9
                        total_withdrawals_amount = sum(s.get('withdrawals_amount', 0) for s in validator_stats) / 1e9
                        
                        # Get first and last balance
                        if sorted_stats:
                            first_balance = sorted_stats[0].get('start_balance', 0) / 1e9 if sorted_stats[0].get('start_balance') else 0
                            last_balance = sorted_stats[-1].get('end_balance', 0) / 1e9 if sorted_stats[-1].get('end_balance') else 0
                            total_change = last_balance - first_balance
                        else:
                            first_balance = last_balance = total_change = 0
                        
                        agg_data.append({
                            'Pubkey': pubkey,
                            'Index': idx,
                            'Days': len(validator_stats),
                            'Initial Balance (ETH)': f"{first_balance:.4f}",
                            'Final Balance (ETH)': f"{last_balance:.4f}",
                            'Total Change (ETH)': f"{total_change:+.6f}",
                            'Proposed': total_proposed,
                            'Missed Blocks': total_missed_blocks,
                            'Missed Attest.': total_missed_attestations,
                            'Missed Sync': total_missed_sync,
                            'Sync Particip.': total_participated_sync,
                            'Orph. Blocks': total_orphaned_blocks,
                            'Orph. Attest.': total_orphaned_attestations,
                            'Orph. Sync': total_orphaned_sync,
                            'Att. Slash.': total_attester_slashings,
                            'Prop. Slash.': total_proposer_slashings,
                            'Deposits': total_deposits,
                            'Withdrawals': total_withdrawals,
                            'Dep. Amt (ETH)': f"{total_deposits_amount:.4f}",
                            'With. Amt (ETH)': f"{total_withdrawals_amount:.4f}"
                        })
                    
                    agg_df = pd.DataFrame(agg_data)
                    st.dataframe(
                        agg_df,
                        height=400,
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Add download button for aggregated data
                    csv = agg_df.to_csv(index=False)
                    st.download_button(
                        label="📥 Download CSV",
                        data=csv,
                        file_name=f"validator_aggregated_stats_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
                
                # Daily breakdown in expander
                with st.expander("Daily Breakdown", expanded=False):
                    # Build detailed table data with ALL fields
                    detailed_data = []
                    index_to_pubkey = processed_data['index_to_pubkey']
                    
                    for stat in stats_data:
                        idx = stat.get('validatorindex', 0)
                        pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                        
                        detailed_data.append({
                            'Pubkey': pubkey,
                            'Index': idx,
                            'Day': stat.get('day', 'N/A'),
                            'Day Start': stat.get('day_start', 'N/A'),
                            'Day End': stat.get('day_end', 'N/A'),
                            'Start Balance (ETH)': f"{stat.get('start_balance', 0) / 1e9:.6f}" if stat.get('start_balance') else "0",
                            'End Balance (ETH)': f"{stat.get('end_balance', 0) / 1e9:.6f}" if stat.get('end_balance') else "0",
                            'Start Eff. Balance': stat.get('start_effective_balance', 0),
                            'End Eff. Balance': stat.get('end_effective_balance', 0),
                            'Min Balance (ETH)': f"{stat.get('min_balance', 0) / 1e9:.6f}" if stat.get('min_balance') is not None and stat.get('min_balance') > 0 else "N/A",
                            'Max Balance (ETH)': f"{stat.get('max_balance', 0) / 1e9:.6f}" if stat.get('max_balance') else "0",
                            'Min Eff. Balance': stat.get('min_effective_balance', 0),
                            'Max Eff. Balance': stat.get('max_effective_balance', 0),
                            'Proposed Blocks': stat.get('proposed_blocks', 0),
                            'Missed Blocks': stat.get('missed_blocks', 0),
                            'Missed Attest.': stat.get('missed_attestations', 0),
                            'Missed Sync': stat.get('missed_sync', 0),
                            'Participated Sync': stat.get('participated_sync', 0),
                            'Orphaned Blocks': stat.get('orphaned_blocks', 0),
                            'Orphaned Attest.': stat.get('orphaned_attestations', 0),
                            'Orphaned Sync': stat.get('orphaned_sync', 0),
                            'Attester Slash.': stat.get('attester_slashings', 0),
                            'Proposer Slash.': stat.get('proposer_slashings', 0),
                            'Deposits': stat.get('deposits', 0),
                            'Deposits Amt (ETH)': f"{stat.get('deposits_amount', 0) / 1e9:.6f}" if stat.get('deposits_amount') else "0",
                            'Withdrawals': stat.get('withdrawals', 0),
                            'Withdrawals Amt (ETH)': f"{stat.get('withdrawals_amount', 0) / 1e9:.6f}" if stat.get('withdrawals_amount') else "0"
                        })
                    
                    detailed_df = pd.DataFrame(detailed_data)
                    
                    # Sort by validator index and day
                    if 'Index' in detailed_df.columns and 'Day' in detailed_df.columns:
                        detailed_df = detailed_df.sort_values(['Index', 'Day'])
                    
                    # Display the dataframe
                    st.dataframe(
                        detailed_df,
                        height=600,
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Add download button for detailed data
                    detailed_csv = detailed_df.to_csv(index=False)
                    st.download_button(
                        label="📥 Download CSV",
                        data=detailed_csv,
                        file_name=f"validator_daily_stats_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
            else:
                st.warning("No stats data available")