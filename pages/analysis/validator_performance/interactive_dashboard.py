"""Interactive dashboard for validator performance analysis."""
import streamlit as st
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from shared.config import get_supported_networks
from pages.analysis.validator_performance.config_utils import (
    parse_validator_pubkeys, 
    format_pubkey_for_display, 
    get_validator_summary_text
)
from pages.analysis.validator_performance.data_loaders import load_validator_indices
from pages.analysis.validator_performance.session_state import (
    store_validator_mappings, 
    get_valid_validators, 
    get_excluded_validators,
    clear_validator_mappings
)
from shared import BeaconchainClient
import httpx


def get_time_range_from_selection(
    time_range_type: str,
    time_range_value: Optional[str] = None,
    custom_start: Optional[Any] = None,
    custom_end: Optional[Any] = None,
    before_date: Optional[Any] = None,
    after_date: Optional[Any] = None
) -> Optional[tuple[datetime, datetime]]:
    """Convert time range selection into start and end datetime objects.
    
    Args:
        time_range_type: Type of time range ('predefined', 'custom', 'before', 'after')
        time_range_value: Value for predefined ranges
        custom_start: Start date for custom range
        custom_end: End date for custom range
        before_date: Date for 'before' type
        after_date: Date for 'after' type
        
    Returns:
        Tuple of (start_datetime, end_datetime) or None if invalid
    """
    now = datetime.now()
    
    if time_range_type == 'predefined' and time_range_value:
        days_map = {
            'last_24_hours': 1,
            'last_7_days': 7,
            'last_30_days': 30,
            'last_90_days': 90,
            'last_180_days': 180,
            'last_365_days': 365
        }
        
        if time_range_value in days_map:
            days = days_map[time_range_value]
            end_date = now
            start_date = now - timedelta(days=days)
            return (start_date, end_date)
    
    elif time_range_type == 'custom' and custom_start and custom_end:
        # Convert date objects to datetime
        start_datetime = datetime.combine(custom_start, datetime.min.time())
        end_datetime = datetime.combine(custom_end, datetime.max.time())
        return (start_datetime, end_datetime)
    
    elif time_range_type == 'before' and before_date:
        # 30 days before the specified date
        end_datetime = datetime.combine(before_date, datetime.max.time())
        start_datetime = end_datetime - timedelta(days=30)
        return (start_datetime, end_datetime)
    
    elif time_range_type == 'after' and after_date:
        # 30 days after the specified date
        start_datetime = datetime.combine(after_date, datetime.min.time())
        end_datetime = start_datetime + timedelta(days=30)
        return (start_datetime, end_datetime)
    
    return None


def initialize_session_state():
    """Initialize all validator_performance_ prefixed session state variables."""
    if 'validator_performance_network' not in st.session_state:
        st.session_state['validator_performance_network'] = 'mainnet'
    
    if 'validator_performance_time_range' not in st.session_state:
        st.session_state['validator_performance_time_range'] = {
            'type': 'predefined',
            'value': 'last_7_days',
            'custom_start': None,
            'custom_end': None,
            'before_date': None,
            'after_date': None
        }
    
    if 'validator_performance_validator_pubkeys' not in st.session_state:
        st.session_state['validator_performance_validator_pubkeys'] = []
    
    if 'validator_performance_last_config' not in st.session_state:
        st.session_state['validator_performance_last_config'] = None
    
    if 'validator_performance_data_loaded' not in st.session_state:
        st.session_state['validator_performance_data_loaded'] = False
    
    if 'validator_performance_api_test_results' not in st.session_state:
        st.session_state['validator_performance_api_test_results'] = None


def render_validator_input() -> List[str]:
    """Render text area for validator pubkeys with validation feedback.
    
    Returns:
        List of valid validator pubkeys
    """
    st.subheader("Validator Public Keys")
    
    # Help text
    st.caption("Enter validator public keys, one per line. Supports bulk paste of 100+ validators.")
    
    # Text area for input
    raw_input = st.text_area(
        "Validator Pubkeys",
        height=200,
        placeholder="0x1234567890abcdef...\n0xabcdef1234567890...\n...",
        help="Paste your validator public keys here, one per line. Both 0x-prefixed and non-prefixed formats are accepted.",
        label_visibility="collapsed"
    )
    
    # Parse and validate input
    if raw_input.strip():
        valid_pubkeys, errors = parse_validator_pubkeys(raw_input)
        
        # Show validation results
        col1, col2 = st.columns([3, 1])
        
        with col1:
            if valid_pubkeys:
                st.success(f"✓ {len(valid_pubkeys)} valid validator(s)")
            else:
                st.info("No valid validators found")
        
        with col2:
            if errors:
                with st.expander(f"{len(errors)} issue(s)", expanded=False):
                    for error in errors:
                        st.warning(error)
        
        return valid_pubkeys
    else:
        st.info("👆 Paste validator public keys above to get started")
        return []


def render_configuration_sidebar() -> Dict[str, Any]:
    """Render sidebar with network, date range, and validator input.
    
    Returns:
        Configuration dictionary with network, time_range, validator_pubkeys, and config_changed flag
    """
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Network selection (limited to mainnet for now)
        networks = ['mainnet']  # Only mainnet supported for now due to Rated API limitation
        network = st.selectbox(
            "Network",
            options=networks,
            index=0,  # Always mainnet
            help="Select the Ethereum network to analyze (currently only mainnet is supported)"
        )
        
        # Time range configuration
        st.subheader("Time Range")
        time_range_type = st.radio(
            "Time Range Type",
            options=['predefined', 'custom', 'before', 'after'],
            format_func=lambda x: {
                'predefined': 'Predefined Range',
                'custom': 'Custom Range',
                'before': 'Before Date',
                'after': 'After Date'
            }[x],
            index=['predefined', 'custom', 'before', 'after'].index(
                st.session_state['validator_performance_time_range']['type']
            )
        )
        
        time_range_value = None
        custom_start = None
        custom_end = None
        before_date = None
        after_date = None
        
        if time_range_type == 'predefined':
            time_range_value = st.selectbox(
                "Select Range",
                options=[
                    'last_24_hours', 'last_7_days', 'last_30_days',
                    'last_90_days', 'last_180_days', 'last_365_days'
                ],
                format_func=lambda x: {
                    'last_24_hours': 'Last 24 Hours',
                    'last_7_days': 'Last 7 Days',
                    'last_30_days': 'Last 30 Days',
                    'last_90_days': 'Last 90 Days',
                    'last_180_days': 'Last 180 Days',
                    'last_365_days': 'Last 365 Days'
                }[x],
                index=['last_24_hours', 'last_7_days', 'last_30_days',
                       'last_90_days', 'last_180_days', 'last_365_days'].index(
                    st.session_state['validator_performance_time_range'].get('value', 'last_7_days')
                )
            )
        elif time_range_type == 'custom':
            col1, col2 = st.columns(2)
            with col1:
                custom_start = st.date_input(
                    "Start Date",
                    value=st.session_state['validator_performance_time_range'].get('custom_start') or 
                          datetime.now().date() - timedelta(days=7)
                )
            with col2:
                custom_end = st.date_input(
                    "End Date",
                    value=st.session_state['validator_performance_time_range'].get('custom_end') or 
                          datetime.now().date()
                )
        elif time_range_type == 'before':
            before_date = st.date_input(
                "Before Date",
                value=st.session_state['validator_performance_time_range'].get('before_date') or 
                      datetime.now().date()
            )
        elif time_range_type == 'after':
            after_date = st.date_input(
                "After Date",
                value=st.session_state['validator_performance_time_range'].get('after_date') or 
                      datetime.now().date() - timedelta(days=30)
            )
        
        # Validator input
        validator_pubkeys = render_validator_input()
        
        # Configuration summary
        st.divider()
        st.subheader("Configuration Summary")
        st.info(f"**Network:** {network}")
        
        # Time range summary
        time_range_config = {
            'type': time_range_type,
            'value': time_range_value,
            'custom_start': custom_start,
            'custom_end': custom_end,
            'before_date': before_date,
            'after_date': after_date
        }
        
        time_range_desc = get_time_range_from_selection(
            time_range_type,
            time_range_value,
            custom_start,
            custom_end,
            before_date,
            after_date
        )
        if time_range_desc:
            start, end = time_range_desc
            st.info(f"**Time Range:** {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}")
        
        # Validator summary
        st.info(f"**Validators:** {len(validator_pubkeys)} selected")
        
        # Load data button
        st.divider()
        load_button = st.button(
            "Load Data",
            type="primary",
            use_container_width=True,
            disabled=len(validator_pubkeys) == 0,
            help="Data loading will be implemented in future updates" if len(validator_pubkeys) > 0 else "Select at least one validator"
        )
        
        if load_button and len(validator_pubkeys) > 0:
            # Set a flag to indicate loading was initiated
            st.session_state['validator_performance_loading_initiated'] = True
            st.rerun()
        
        # Check if configuration changed
        current_config = {
            'network': network,
            'time_range': time_range_config,
            'validator_pubkeys': validator_pubkeys
        }
        
        config_changed = current_config != st.session_state['validator_performance_last_config']
        
        # Update session state
        st.session_state['validator_performance_network'] = network
        st.session_state['validator_performance_time_range'] = time_range_config
        st.session_state['validator_performance_validator_pubkeys'] = validator_pubkeys
        st.session_state['validator_performance_last_config'] = current_config
        
        if config_changed:
            st.session_state['validator_performance_data_loaded'] = False
            st.session_state['validator_performance_loading_initiated'] = False
            st.session_state['validator_performance_api_test_results'] = None
            clear_validator_mappings()
        
        return {
            'network': network,
            'time_range': time_range_config,
            'validator_pubkeys': validator_pubkeys,
            'config_changed': config_changed
        }


def render_main_content(config: Dict[str, Any]):
    """Render main dashboard area with configuration summary.
    
    Args:
        config: Configuration dictionary from sidebar
    """
    # Main header
    st.title("Validator Performance")
    st.markdown("Analyze the performance of Ethereum validators over time.")
    
    # Configuration overview in columns
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Network", config['network'].title())
    
    with col2:
        time_range_desc = get_time_range_from_selection(
            config['time_range']['type'],
            config['time_range'].get('value'),
            config['time_range'].get('custom_start'),
            config['time_range'].get('custom_end'),
            config['time_range'].get('before_date'),
            config['time_range'].get('after_date')
        )
        if time_range_desc:
            start, end = time_range_desc
            days = (end - start).days
            st.metric("Time Range", f"{days} days")
    
    with col3:
        st.metric("Validators", len(config['validator_pubkeys']))
    
    # Validator summary
    if config['validator_pubkeys']:
        st.divider()
        st.subheader("Validators")
        
        # Get validator status if data has been loaded
        pubkey_to_index = get_valid_validators()
        excluded_pubkeys = get_excluded_validators()
        
        # Expandable list of validators with counts
        found_count = sum(1 for pk in config['validator_pubkeys'] if pk in pubkey_to_index)
        excluded_count = sum(1 for pk in config['validator_pubkeys'] if pk in excluded_pubkeys)
        
        expander_text = "View validator list"
        if pubkey_to_index or excluded_pubkeys:  # If data has been loaded
            expander_text = f"View validator list ({found_count} found, {excluded_count} excluded)"
        
        with st.expander(expander_text, expanded=False):
            for i, pubkey in enumerate(config['validator_pubkeys']):
                if pubkey in pubkey_to_index:
                    st.text(f"{i+1}. {pubkey} (index: {pubkey_to_index[pubkey]})")
                elif pubkey in excluded_pubkeys:
                    st.text(f"{i+1}. {pubkey} (not found)")
                else:
                    st.text(f"{i+1}. {pubkey}")
                
                if i >= 99:  # Show max 100 validators
                    st.text(f"... and {len(config['validator_pubkeys']) - 100} more")
                    break
    
    # Data loading section
    st.divider()
    
    if not config['validator_pubkeys']:
        st.info("Select validators in the sidebar to begin analysis")
    elif not st.session_state['validator_performance_data_loaded']:
        # Check if loading was initiated
        if st.session_state.get('validator_performance_loading_initiated', False):
            # Perform the actual data loading
            network = config['network']
            validator_pubkeys = config['validator_pubkeys']
            
            # Load validator indices from ClickHouse
            with st.spinner("Loading validator indices..."):
                pubkey_to_index, missing_pubkeys = load_validator_indices(validator_pubkeys, network)
            
            # Display warnings for missing pubkeys in an expandable section
            if missing_pubkeys:
                st.warning(f"{len(missing_pubkeys)} validator(s) not found in database and will be excluded")
            
            # Store results in session state
            store_validator_mappings(pubkey_to_index, missing_pubkeys)
            
            # Display success/error message
            if pubkey_to_index:
                st.success(f"Successfully loaded {len(pubkey_to_index)} validator(s)")
                
                # Test BeaconchainClient with stats endpoint
                with st.spinner("Testing Beaconcha.in API..."):
                    try:
                        # Create client
                        client = BeaconchainClient()
                        
                        # Get ALL validator indices
                        all_indices = list(pubkey_to_index.values())
                        
                        # Get configured time range
                        time_range_config = st.session_state.get('validator_performance_time_range', {})
                        time_range = get_time_range_from_selection(
                            time_range_config.get('type', 'predefined'),
                            time_range_config.get('value'),
                            time_range_config.get('custom_start'),
                            time_range_config.get('custom_end'),
                            time_range_config.get('before_date'),
                            time_range_config.get('after_date')
                        )
                        
                        # Calculate start_day and end_day based on time range
                        # BeaconChain API uses epoch days where day 1 = Dec 1, 2020 (mainnet genesis)
                        genesis_date = datetime(2020, 12, 1)
                        
                        if time_range:
                            start_date, end_date = time_range
                            # Convert to epoch days
                            start_day = (start_date - genesis_date).days + 1
                            end_day = (end_date - genesis_date).days + 1
                            
                            # Ensure positive values
                            start_day = max(1, start_day)
                            end_day = max(1, end_day)
                            
                            # Also keep date strings for display
                            start_date_str = start_date.strftime('%Y-%m-%d')
                            end_date_str = end_date.strftime('%Y-%m-%d')
                        else:
                            # Default to last 7 days
                            today = datetime.now()
                            end_day = (today - genesis_date).days + 1
                            start_day = end_day - 7
                            start_day = max(1, start_day)
                            
                            # Calculate actual dates for display
                            start_date = genesis_date + timedelta(days=start_day - 1)
                            end_date = genesis_date + timedelta(days=end_day - 1)
                            start_date_str = start_date.strftime('%Y-%m-%d')
                            end_date_str = end_date.strftime('%Y-%m-%d')
                        
                        # Collect all stats data
                        all_stats_data = []
                        
                        # Process validators individually (stats endpoint requires individual calls)
                        # Limit to reasonable number to avoid too many API calls
                        max_validators = min(len(all_indices), 50)  # Limit to 50 validators
                        
                        for i, idx in enumerate(all_indices[:max_validators]):
                            stats = client.get_validator_stats(idx, start_day=start_day, end_day=end_day)
                            if stats:
                                for stat in stats:
                                    # Add validator index if not present
                                    stat_dict = stat.dict() if hasattr(stat, 'dict') else stat
                                    if isinstance(stat_dict, dict):
                                        stat_dict['validatorindex'] = idx
                                        all_stats_data.append(stat_dict)
                            
                            # Show progress
                            if (i + 1) % 10 == 0:
                                st.caption(f"Processed {i + 1}/{max_validators} validators...")
                        
                        # Store results in session state
                        st.session_state['validator_performance_api_test_results'] = {
                            'all_indices': all_indices,
                            'max_validators': max_validators,
                            'stats_data': all_stats_data,
                            'start_day': start_day,
                            'end_day': end_day,
                            'start_date': start_date_str,
                            'end_date': end_date_str,
                            'error': None
                        }
                        
                        # Close the client
                        client.close()
                        
                    except Exception as e:
                        st.session_state['validator_performance_api_test_results'] = {
                            'all_indices': all_indices if 'all_indices' in locals() else [],
                            'max_validators': max_validators if 'max_validators' in locals() else 0,
                            'stats_data': [],
                            'start_date': start_date_str if 'start_date_str' in locals() else None,
                            'end_date': end_date_str if 'end_date_str' in locals() else None,
                            'error': str(e)
                        }
                
                # Mark data as loaded
                st.session_state['validator_performance_data_loaded'] = True
                st.session_state['validator_performance_loading_initiated'] = False
                st.rerun()
            else:
                st.error("No valid validators found. Please check your validator pubkeys.")
                st.session_state['validator_performance_loading_initiated'] = False
        else:
            st.info("Click 'Load Data' in the sidebar to fetch validator performance data")
    else:
        # Data has been loaded - show summary
        pubkey_to_index = get_valid_validators()
        excluded_pubkeys = get_excluded_validators()
        
        st.success(f"{len(pubkey_to_index)} validator(s) found, {len(excluded_pubkeys)} excluded")
        
        # Display API test results if available
        if st.session_state.get('validator_performance_api_test_results'):
            test_results = st.session_state['validator_performance_api_test_results']
            
            with st.expander("beaconcha.in", expanded=True):
                if test_results.get('error'):
                    st.error(f"Error testing Beaconcha.in API: {test_results['error']}")
                else:
                    max_validators = test_results.get('max_validators', 0)
                    total_indices = len(test_results.get('all_indices', []))
                    stats_data = test_results.get('stats_data', [])
                    
                    if stats_data:
                        import pandas as pd
                        
                        # Create reverse mapping from index to pubkey
                        index_to_pubkey = {v: k for k, v in pubkey_to_index.items()}
                        
                        # Group by validator
                        validator_groups = {}
                        for stat in stats_data:
                            idx = stat.get('validatorindex', 0)
                            if idx not in validator_groups:
                                validator_groups[idx] = []
                            validator_groups[idx].append(stat)
                        
                        # Show summary
                        st.subheader("Summary")
                        
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
                        
                        # Display overall metrics
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("Total Validators", total_validators)
                            st.metric("Proposed Blocks", f"{overall_proposed:,}")
                            st.metric("Deposits", f"{overall_deposits:,}")
                        with col2:
                            st.metric("Missed Blocks", f"{overall_missed_blocks:,}")
                            st.metric("Missed Attestations", f"{overall_missed_attestations:,}")
                            st.metric("Total Withdrawals", f"{overall_withdrawals:,}")
                        with col3:
                            st.metric("Sync Participation", f"{overall_participated_sync:,}")
                            st.metric("Slashings", f"{overall_attester_slashings + overall_proposer_slashings:,}")
                            st.metric("Orphaned Blocks", f"{overall_orphaned_blocks:,}")
                        with col4:
                            st.metric("Orphaned Attestations", f"{overall_orphaned_attestations:,}")
                            st.metric("Total Withdrawals Amount", f"{overall_withdrawals_amount:.4f} ETH")
                            st.metric("", "")  # Empty placeholder
                        
                        # Per-validator summary in expander
                        with st.expander("Per-Validator Summary", expanded=False):
                            agg_data = []
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
                                file_name=f"validator_aggregated_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv"
                            )
                        
                        # Daily breakdown in expander
                        with st.expander("Daily Breakdown (All Fields)", expanded=False):
                            # Build detailed table data with ALL fields
                            detailed_data = []
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
                                    'Min Balance (ETH)': f"{stat.get('min_balance', 0) / 1e9:.6f}" if stat.get('min_balance') else "0",
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
                                file_name=f"validator_daily_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv"
                            )
                    else:
                        st.warning("No stats data available")
        
        # Test Rated API (only available for mainnet)
        current_network = st.session_state.get('validator_performance_network', 'mainnet')
        if st.session_state.get('validator_performance_data_loaded') and pubkey_to_index and current_network == 'mainnet':
            with st.expander("rated.network", expanded=True):
                with st.spinner("Testing Rated API..."):
                    try:
                        # Check if API key is set
                        import os
                        if not os.getenv('RATED_API_KEY'):
                            st.error("RATED_API_KEY environment variable not set. Please set it to use Rated API.")
                            st.info("Get your API key from https://www.rated.network/")
                        else:
                            # Get list of validator indices (max 10 for testing)
                            limited_indices = list(pubkey_to_index.values())[:10]
                            
                            # Get configured time range
                            time_range_config = st.session_state.get('validator_performance_time_range', {})
                            from_date = None
                            to_date = None
                            
                            # Get time range from configuration
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
                                from_date = start_date.date() if isinstance(start_date, datetime) else start_date
                                to_date = end_date.date() if isinstance(end_date, datetime) else end_date
                                
                                # Validate dates aren't in the future
                                today = datetime.now().date()
                                if to_date > today:
                                    st.warning(f"End date {to_date} is in the future. Adjusting to today ({today})")
                                    to_date = today
                                if from_date > today:
                                    st.warning(f"Start date {from_date} is in the future. Adjusting to 7 days ago")
                                    from_date = today - timedelta(days=7)
                                
                            
                            # Call Rated API v1 directly with httpx
                            url = "https://api.rated.network/v1/eth/validators/effectiveness"
                            
                            # Build params - indices need to be added as multiple params
                            params = {
                                "limit": 1000,
                                "sortOrder": "asc",
                                "groupBy": "validator"
                            }
                            
                            # Add dates if provided
                            if from_date:
                                params["fromDate"] = from_date.strftime('%Y-%m-%d')
                            if to_date:
                                params["toDate"] = to_date.strftime('%Y-%m-%d')
                            
                            headers = {
                                "Authorization": f"Bearer {os.getenv('RATED_API_KEY')}"
                            }
                            
                            
                            # Make the request
                            with httpx.Client() as client:
                                try:
                                    # Build URL with indices as multiple query params
                                    # httpx doesn't handle list params well, so we'll build it manually
                                    indices_params = "&".join([f"indices={idx}" for idx in limited_indices])
                                    full_url = f"{url}?{indices_params}"
                                    
                                    response = client.get(full_url, params=params, headers=headers, timeout=30.0)
                                    response.raise_for_status()
                                    
                                    data = response.json()
                                    
                                    # Check the response structure - v1 API returns data in results array
                                    if isinstance(data, dict) and "results" in data and data["results"]:
                                        results = data["results"]
                                        
                                        # Group by validator
                                        validators_data = {}
                                        for result in results:
                                            vid = result.get("validatorIndex", 0)
                                            if vid not in validators_data:
                                                validators_data[vid] = []
                                            validators_data[vid].append(result)
                                        
                                        # Show summary
                                        st.subheader("Summary")
                                        
                                        # Calculate aggregated metrics
                                        total_validators = len(validators_data)
                                        total_records = len(results)
                                        
                                        # Calculate averages and totals
                                        sum_validator_eff = sum(r.get("validatorEffectiveness", 0) for r in results)
                                        sum_attester_eff = sum(r.get("attesterEffectiveness", 0) for r in results)
                                        sum_uptime = sum(r.get("uptime", 0) for r in results)
                                        sum_correctness = sum(r.get("avgCorrectness", 0) for r in results)
                                        sum_inclusion_delay = sum(r.get("avgInclusionDelay", 0) for r in results)
                                        
                                        avg_validator_eff = sum_validator_eff / total_records if total_records > 0 else 0
                                        avg_attester_eff = sum_attester_eff / total_records if total_records > 0 else 0
                                        avg_uptime = sum_uptime / total_records if total_records > 0 else 0
                                        avg_correctness = sum_correctness / total_records if total_records > 0 else 0
                                        avg_inclusion_delay = sum_inclusion_delay / total_records if total_records > 0 else 0
                                        
                                        # Count proposer effectiveness records
                                        proposer_records = [r for r in results if r.get("proposerEffectiveness") is not None]
                                        avg_proposer_eff = sum(r.get("proposerEffectiveness", 0) for r in proposer_records) / len(proposer_records) if proposer_records else 0
                                        
                                        # Display summary metrics
                                        col1, col2, col3, col4 = st.columns(4)
                                        with col1:
                                            st.metric("Total Validators", total_validators)
                                            st.metric("Avg Validator Effectiveness", f"{avg_validator_eff:.2f}%")
                                        with col2:
                                            st.metric("Avg Attester Effectiveness", f"{avg_attester_eff:.2f}%")
                                            st.metric("Avg Uptime", f"{avg_uptime * 100:.2f}%")
                                        with col3:
                                            st.metric("Avg Correctness", f"{avg_correctness * 100:.2f}%")
                                            st.metric("Avg Inclusion Delay", f"{avg_inclusion_delay:.2f}")
                                        with col4:
                                            if proposer_records:
                                                st.metric("Avg Proposer Effectiveness", f"{avg_proposer_eff:.2f}%")
                                        
                                        # Detailed table in expander
                                        with st.expander("Effectiveness Data by Validator", expanded=False):
                                            # Create a table view
                                            import pandas as pd
                                            
                                            # Create reverse mapping from index to pubkey
                                            index_to_pubkey = {v: k for k, v in pubkey_to_index.items()}
                                            
                                            # Build table data
                                            table_data = []
                                            for result in results:
                                                idx = result.get("validatorIndex", 0)
                                                pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                                                
                                                table_data.append({
                                                    'Pubkey': pubkey,
                                                    'Index': idx,
                                                    'Start Date': result.get("startDate", "N/A"),
                                                    'End Date': result.get("endDate", "N/A"),
                                                    'Validator Eff (%)': f"{result.get('validatorEffectiveness', 0):.2f}",
                                                    'Attester Eff (%)': f"{result.get('attesterEffectiveness', 0):.2f}",
                                                    'Proposer Eff (%)': f"{result.get('proposerEffectiveness', 0):.2f}" if result.get('proposerEffectiveness') else "N/A",
                                                    'Uptime (%)': f"{result.get('uptime', 0) * 100:.2f}",
                                                    'Avg Correctness (%)': f"{result.get('avgCorrectness', 0) * 100:.2f}",
                                                    'Avg Inclusion Delay': f"{result.get('avgInclusionDelay', 0):.2f}",
                                                    'Sum Inclusion Delay': result.get('sumInclusionDelay', 0),
                                                    'Start Day': result.get('startDay', 'N/A'),
                                                    'End Day': result.get('endDay', 'N/A')
                                                })
                                            
                                            df = pd.DataFrame(table_data)
                                            
                                            # Display the dataframe
                                            st.dataframe(
                                                df,
                                                height=400,
                                                use_container_width=True,
                                                hide_index=True
                                            )
                                            
                                            # Add download button
                                            csv = df.to_csv(index=False)
                                            st.download_button(
                                                label="📥 Download CSV",
                                                data=csv,
                                                file_name=f"validator_effectiveness_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                                mime="text/csv"
                                            )
                                    else:
                                        st.warning("No effectiveness data returned from API")
                                        
                                except httpx.HTTPStatusError as e:
                                    st.error(f"Rated API Error: HTTP {e.response.status_code}")
                                    st.error(f"Error response: {e.response.text}")
                                except Exception as e:
                                    st.error(f"Unexpected error: {type(e).__name__}: {str(e)}")
                    except Exception as e:
                        st.error(f"Error in Rated API test: {type(e).__name__}: {str(e)}")


def run_dashboard():
    """Main dashboard entry point."""
    # Page configuration
    st.set_page_config(
        page_title="Validator Performance - Xatu Analysis",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Initialize session state
    initialize_session_state()
    
    # Render sidebar and get configuration
    config = render_configuration_sidebar()
    
    # Render main content
    render_main_content(config)