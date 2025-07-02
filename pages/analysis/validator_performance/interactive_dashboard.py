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
    """Convert time range selection into start and end datetime objects in UTC.
    
    Args:
        time_range_type: Type of time range ('predefined', 'custom', 'before', 'after')
        time_range_value: Value for predefined ranges
        custom_start: Start date for custom range
        custom_end: End date for custom range
        before_date: Date for 'before' type
        after_date: Date for 'after' type
        
    Returns:
        Tuple of (start_datetime, end_datetime) in UTC or None if invalid
    """
    # Use UTC for consistency with APIs
    now = datetime.utcnow()
    
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
        # Convert date objects to datetime in UTC (start of day and end of day in UTC)
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


def split_date_ranges_with_exclusions(
    start_date: datetime, 
    end_date: datetime, 
    excluded_ranges: List[Dict[str, Any]]
) -> List[tuple[datetime, datetime]]:
    """Split a date range into multiple ranges based on excluded date ranges.
    
    Args:
        start_date: Start of the overall date range
        end_date: End of the overall date range
        excluded_ranges: List of excluded date ranges, each with 'start' and 'end' keys
        
    Returns:
        List of (start, end) datetime tuples representing valid date ranges
    """
    if not excluded_ranges:
        return [(start_date, end_date)]
    
    # Sort excluded ranges by start date
    sorted_exclusions = sorted(excluded_ranges, key=lambda x: x['start'])
    
    # Merge overlapping exclusions
    merged_exclusions = []
    for exclusion in sorted_exclusions:
        exc_start = exclusion['start']
        exc_end = exclusion['end']
        
        # Convert to datetime if needed
        if not isinstance(exc_start, datetime):
            exc_start = datetime.combine(exc_start, datetime.min.time())
        if not isinstance(exc_end, datetime):
            exc_end = datetime.combine(exc_end, datetime.max.time())
        
        # Skip if completely outside our range
        if exc_end < start_date or exc_start > end_date:
            continue
            
        # Clip to our range
        exc_start = max(exc_start, start_date)
        exc_end = min(exc_end, end_date)
        
        if merged_exclusions and exc_start <= merged_exclusions[-1][1]:
            # Merge with previous
            merged_exclusions[-1] = (merged_exclusions[-1][0], max(exc_end, merged_exclusions[-1][1]))
        else:
            merged_exclusions.append((exc_start, exc_end))
    
    # Generate valid ranges
    valid_ranges = []
    current_start = start_date
    
    for exc_start, exc_end in merged_exclusions:
        if current_start < exc_start:
            valid_ranges.append((current_start, exc_start - timedelta(seconds=1)))
        current_start = exc_end + timedelta(seconds=1)
    
    # Add final range if needed
    if current_start <= end_date:
        valid_ranges.append((current_start, end_date))
    
    return valid_ranges


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
    
    if 'validator_performance_excluded_ranges' not in st.session_state:
        st.session_state['validator_performance_excluded_ranges'] = []


def render_validator_input() -> List[str]:
    """Render text area for validator pubkeys with validation feedback.
    
    Returns:
        List of valid validator pubkeys
    """
    st.subheader("Validator Public Keys")
    
    # Help text
    st.caption("Enter validator public keys, one per line. Supports bulk paste of 100+ validators.")
    
    # Text area for input with session state key
    raw_input = st.text_area(
        "Validator Pubkeys",
        height=200,
        placeholder="0x1234567890abcdef...\n0xabcdef1234567890...\n...",
        help="Paste your validator public keys here, one per line. Both 0x-prefixed and non-prefixed formats are accepted.",
        label_visibility="collapsed",
        key="validator_performance_pubkeys_input"
    )
    
    # Parse and validate input
    if raw_input and raw_input.strip():
        valid_pubkeys, errors = parse_validator_pubkeys(raw_input)
        
        # Show validation results
        col1, col2 = st.columns([3, 1])
        
        with col1:
            if valid_pubkeys:
                st.success(f"{len(valid_pubkeys)} valid validator(s)")
            else:
                st.info("No valid validators found")
        
        with col2:
            if errors:
                with st.expander(f"{len(errors)} issue(s)", expanded=False):
                    for error in errors:
                        st.warning(error)
        
        return valid_pubkeys
    else:
        # Check if we have pubkeys in session state even if text area appears empty
        if 'validator_performance_pubkeys_input' in st.session_state and st.session_state['validator_performance_pubkeys_input']:
            # Try parsing what's in session state
            stored_input = st.session_state['validator_performance_pubkeys_input']
            if stored_input.strip():
                valid_pubkeys, _ = parse_validator_pubkeys(stored_input)
                if valid_pubkeys:
                    st.info(f"Using {len(valid_pubkeys)} validator(s) from previous input")
                    return valid_pubkeys
        
        st.info("Paste validator public keys above to get started")
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
                    st.session_state['validator_performance_time_range'].get('value') 
                    if st.session_state['validator_performance_time_range'].get('value') in [
                        'last_24_hours', 'last_7_days', 'last_30_days',
                        'last_90_days', 'last_180_days', 'last_365_days'
                    ] else 'last_7_days'
                )
            )
        elif time_range_type == 'custom':
            col1, col2 = st.columns(2)
            with col1:
                custom_start = st.date_input(
                    "Start Date",
                    value=st.session_state['validator_performance_time_range'].get('custom_start') or 
                          datetime.utcnow().date() - timedelta(days=7)
                )
            with col2:
                custom_end = st.date_input(
                    "End Date",
                    value=st.session_state['validator_performance_time_range'].get('custom_end') or 
                          datetime.utcnow().date()
                )
        elif time_range_type == 'before':
            before_date = st.date_input(
                "Before Date",
                value=st.session_state['validator_performance_time_range'].get('before_date') or 
                      datetime.utcnow().date()
            )
        elif time_range_type == 'after':
            after_date = st.date_input(
                "After Date",
                value=st.session_state['validator_performance_time_range'].get('after_date') or 
                      datetime.utcnow().date() - timedelta(days=30)
            )
        
        # Excluded date ranges
        st.divider()
        # Get current time range for limiting exclusion dates
        time_range_dates = get_time_range_from_selection(
            time_range_type,
            time_range_value,
            custom_start,
            custom_end,
            before_date,
            after_date
        )
        
        st.subheader("Excluded Date Ranges")
        st.caption("Optionally exclude specific date ranges from the analysis")
        
        # Add new exclusion
        with st.expander("Add Date Exclusion", expanded=False):
            # Set min/max dates based on selected time range
            if time_range_dates:
                range_start, range_end = time_range_dates
                min_date = range_start.date() if isinstance(range_start, datetime) else range_start
                max_date = range_end.date() if isinstance(range_end, datetime) else range_end
            else:
                # Default to reasonable range if no time range selected
                min_date = datetime.utcnow().date() - timedelta(days=365)
                max_date = datetime.utcnow().date()
            
            col1, col2 = st.columns(2)
            with col1:
                exc_start = st.date_input(
                    "Exclusion Start",
                    key="new_exclusion_start",
                    min_value=min_date,
                    max_value=max_date,
                    value=min_date,
                    help="Start date of the period to exclude (limited to selected time range)"
                )
            with col2:
                exc_end = st.date_input(
                    "Exclusion End",
                    key="new_exclusion_end",
                    min_value=min_date,
                    max_value=max_date,
                    value=min_date,
                    help="End date of the period to exclude (limited to selected time range)"
                )
            
            if st.button("Add Exclusion", use_container_width=True):
                if exc_start and exc_end:
                    if exc_start <= exc_end:
                        new_exclusion = {
                            'start': exc_start,
                            'end': exc_end
                        }
                        if new_exclusion not in st.session_state['validator_performance_excluded_ranges']:
                            st.session_state['validator_performance_excluded_ranges'].append(new_exclusion)
                            # Don't rerun immediately, let the state update naturally
                    else:
                        st.error("Start date must be before or equal to end date")
        
        # Display existing exclusions
        if st.session_state['validator_performance_excluded_ranges']:
            st.write("**Current Exclusions:**")
            for i, exclusion in enumerate(st.session_state['validator_performance_excluded_ranges']):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.text(f"{exclusion['start']} to {exclusion['end']}")
                with col2:
                    if st.button("Remove", key=f"remove_exclusion_{i}"):
                        st.session_state['validator_performance_excluded_ranges'].pop(i)
                        # Don't rerun immediately, let the state update naturally
        else:
            st.info("No date ranges excluded")
        
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
        
        # Excluded ranges summary
        if st.session_state['validator_performance_excluded_ranges']:
            exclusions_text = ", ".join([
                f"{exc['start']} to {exc['end']}" 
                for exc in st.session_state['validator_performance_excluded_ranges']
            ])
            st.info(f"**Excluded Ranges:** {exclusions_text}")
        
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
            # Clean reset - clear all data and force reload
            st.session_state['validator_performance_data_loaded'] = False
            st.session_state['validator_performance_api_test_results'] = None
            clear_validator_mappings()
            # Set a flag to indicate loading was initiated
            st.session_state['validator_performance_loading_initiated'] = True
            st.rerun()
        
        # Check if configuration changed
        current_config = {
            'network': network,
            'time_range': time_range_config,
            'validator_pubkeys': validator_pubkeys,
            'excluded_ranges': st.session_state['validator_performance_excluded_ranges']
        }
        
        # Deep comparison for configuration change detection
        config_changed = False
        last_config = st.session_state.get('validator_performance_last_config')
        
        if last_config is None:
            config_changed = True
        else:
            # Compare each component individually
            if (last_config.get('network') != network or
                last_config.get('time_range') != time_range_config or
                last_config.get('validator_pubkeys') != validator_pubkeys or
                last_config.get('excluded_ranges') != st.session_state['validator_performance_excluded_ranges']):
                config_changed = True
        
        # Update session state
        st.session_state['validator_performance_network'] = network
        st.session_state['validator_performance_time_range'] = time_range_config
        st.session_state['validator_performance_validator_pubkeys'] = validator_pubkeys
        st.session_state['validator_performance_last_config'] = current_config.copy()
        
        if config_changed:
            st.session_state['validator_performance_data_loaded'] = False
            st.session_state['validator_performance_loading_initiated'] = False
            st.session_state['validator_performance_api_test_results'] = None
            clear_validator_mappings()
        
        return {
            'network': network,
            'time_range': time_range_config,
            'validator_pubkeys': validator_pubkeys,
            'excluded_ranges': st.session_state['validator_performance_excluded_ranges'],
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
    
    # Show excluded ranges if any
    excluded_ranges = st.session_state.get('validator_performance_excluded_ranges', [])
    if excluded_ranges:
        st.warning(f"**Note:** {len(excluded_ranges)} date range(s) excluded from analysis")
        with st.expander("View excluded ranges", expanded=False):
            for i, exclusion in enumerate(excluded_ranges):
                st.text(f"{i+1}. {exclusion['start']} to {exclusion['end']}")
    
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
                with st.spinner("Loading data from Beaconcha.in..."):
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
                        
                        # Get excluded ranges for filtering later
                        excluded_ranges = st.session_state.get('validator_performance_excluded_ranges', [])
                        
                        # Collect all stats data
                        all_stats_data = []
                        unfiltered_count = 0
                        
                        # Process validators individually (stats endpoint requires individual calls)
                        # Limit to reasonable number to avoid too many API calls
                        max_validators = min(len(all_indices), 50)  # Limit to 50 validators
                        
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
                        
                        # Store results in session state
                        st.session_state['validator_performance_api_test_results'] = {
                            'all_indices': all_indices,
                            'max_validators': max_validators,
                            'stats_data': all_stats_data,
                            'unfiltered_count': unfiltered_count,
                            'filtered_count': unfiltered_count - len(all_stats_data) if unfiltered_count > len(all_stats_data) else 0,
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
            
            with st.expander("beaconcha.in - Statistics", expanded=True):
                if test_results.get('error'):
                    st.error(f"Error testing Beaconcha.in API: {test_results['error']}")
                else:
                    max_validators = test_results.get('max_validators', 0)
                    total_indices = len(test_results.get('all_indices', []))
                    stats_data = test_results.get('stats_data', [])
                    
                    if stats_data:
                        import pandas as pd
                        
                        # Show filtering info if applicable
                        filtered_count = test_results.get('filtered_count', 0)
                        if filtered_count > 0:
                            st.info(f"Filtered out {filtered_count} daily records due to date exclusions")
                        
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
                                file_name=f"validator_aggregated_stats_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv"
                            )
                        
                        # Daily breakdown in expander
                        with st.expander("Daily Breakdown", expanded=False):
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
                                file_name=f"validator_daily_stats_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv"
                            )
                    else:
                        st.warning("No stats data available")
        
        # Test Rated API (only available for mainnet)
        current_network = st.session_state.get('validator_performance_network', 'mainnet')
        if st.session_state.get('validator_performance_data_loaded') and pubkey_to_index and current_network == 'mainnet':
            with st.expander("rated.network - Effectiveness", expanded=True):
                with st.spinner("Loading data from Rated..."):
                    try:
                        # Check if API key is set
                        import os
                        if not os.getenv('RATED_API_KEY'):
                            st.error("RATED_API_KEY environment variable not set. Please set it to use Rated API.")
                            st.info("Get your API key from https://www.rated.network/")
                        else:
                            # Get list of all validator indices
                            limited_indices = list(pubkey_to_index.values())
                            
                            # Get configured time range
                            time_range_config = st.session_state.get('validator_performance_time_range', {})
                            
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
                            else:
                                # Default to last 7 days
                                end_date = datetime.utcnow()
                                start_date = end_date - timedelta(days=7)
                            
                            # Get excluded ranges for filtering later
                            excluded_ranges = st.session_state.get('validator_performance_excluded_ranges', [])
                            
                            # Call Rated API v1 directly with httpx for the FULL date range
                            url = "https://api.rated.network/v1/eth/validators/effectiveness"
                            
                            headers = {
                                "Authorization": f"Bearer {os.getenv('RATED_API_KEY')}"
                            }
                            
                            # Convert dates for API
                            from_date = start_date.date() if isinstance(start_date, datetime) else start_date
                            to_date = end_date.date() if isinstance(end_date, datetime) else end_date
                            
                            # Validate dates aren't in the future
                            today = datetime.utcnow().date()
                            if to_date > today:
                                st.warning(f"End date {to_date} is in the future. Adjusting to today ({today})")
                                to_date = today
                            if from_date > today:
                                st.warning(f"Start date {from_date} is in the future. Adjusting to 7 days ago")
                                from_date = today - timedelta(days=7)
                            
                            # Build base params for individual validator requests
                            base_params = {
                                "limit": 1000,
                                "sortOrder": "asc",
                                "granularity": "day",  # Get daily data
                                "groupBy": "granularity",  # Group by the granularity level
                                "fromDate": from_date.strftime('%Y-%m-%d'),
                                "toDate": to_date.strftime('%Y-%m-%d')
                            }
                            
                            # Collect all results
                            all_results = []
                            unfiltered_count = 0
                            successful_validators = 0
                            
                            # Rate limiting for Rated API (2 requests per second)
                            import time
                            last_request_time = 0
                            min_interval = 0.5  # 500ms between requests = 2 requests per second
                            
                            # Make individual requests per validator
                            with httpx.Client() as client:
                                for i, idx in enumerate(limited_indices):
                                    try:
                                        # Rate limiting
                                        current_time = time.time()
                                        time_since_last = current_time - last_request_time
                                        if time_since_last < min_interval:
                                            time.sleep(min_interval - time_since_last)
                                        
                                        # Build URL with single validator index
                                        full_url = f"{url}?indices={idx}"
                                        
                                        
                                        # Make request with retry logic for rate limits
                                        max_retries = 3
                                        for retry in range(max_retries):
                                            response = client.get(full_url, params=base_params, headers=headers, timeout=30.0)
                                            
                                            if response.status_code == 429:
                                                # Rate limited - wait and retry
                                                retry_after = int(response.headers.get('Retry-After', '1'))
                                                st.warning(f"Rate limited. Waiting {retry_after} seconds...")
                                                time.sleep(retry_after)
                                                continue
                                            
                                            response.raise_for_status()
                                            break  # Success, exit retry loop
                                        
                                        last_request_time = time.time()
                                        
                                        data = response.json()
                                        
                                        
                                        # Process results for this validator
                                        if isinstance(data, dict) and "results" in data and data["results"]:
                                            successful_validators += 1
                                            for result in data["results"]:
                                                # Add validator index to each result since we're making individual requests
                                                result['validatorIndex'] = idx
                                                
                                                unfiltered_count += 1
                                                
                                                # Get the date from the result
                                                result_date_str = result.get("startDate") or result.get("date")
                                                if result_date_str and excluded_ranges:
                                                    # Parse the date
                                                    result_date = datetime.strptime(result_date_str, '%Y-%m-%d').date()
                                                    
                                                    # Check if this date falls within any excluded range
                                                    is_excluded = False
                                                    for exclusion in excluded_ranges:
                                                        exc_start = exclusion['start']
                                                        exc_end = exclusion['end']
                                                        if exc_start <= result_date <= exc_end:
                                                            is_excluded = True
                                                            break
                                                    
                                                    # Only include if not excluded
                                                    if not is_excluded:
                                                        all_results.append(result)
                                                else:
                                                    # No exclusions or no date found, include it
                                                    all_results.append(result)
                                        
                                            
                                    except httpx.HTTPStatusError as e:
                                        st.error(f"Rated API Error for validator {idx}: HTTP {e.response.status_code}")
                                        continue
                                    except Exception as e:
                                        st.error(f"Error fetching validator {idx}: {type(e).__name__}: {str(e)}")
                                        continue
                                
                                # Show summary info
                                if successful_validators < len(limited_indices):
                                    st.info(f"Found data for {successful_validators}/{len(limited_indices)} validators in Rated")
                                
                                # Show filtering info if applicable
                                if excluded_ranges and unfiltered_count > len(all_results):
                                    st.info(f"Filtered out {unfiltered_count - len(all_results)} daily records due to date exclusions")
                            
                            # Process all collected results
                            if all_results:
                                # Group by validator
                                validators_data = {}
                                for result in all_results:
                                    vid = result.get("validatorIndex", 0)
                                    if vid not in validators_data:
                                        validators_data[vid] = []
                                    validators_data[vid].append(result)
                                
                                # Show summary
                                st.subheader("Summary")
                                
                                # Create reverse mapping from index to pubkey
                                index_to_pubkey = {v: k for k, v in pubkey_to_index.items()}
                                
                                # Calculate aggregated metrics
                                total_validators = len(validators_data)
                                total_days = len(all_results)
                                
                                # Calculate averages across all daily records
                                avg_validator_eff = sum(r.get("validatorEffectiveness", 0) for r in all_results) / total_days if total_days > 0 else 0
                                avg_attester_eff = sum(r.get("attesterEffectiveness", 0) for r in all_results) / total_days if total_days > 0 else 0
                                avg_proposer_eff = sum(r.get("proposerEffectiveness", 0) for r in all_results if r.get("proposerEffectiveness") is not None) / len([r for r in all_results if r.get("proposerEffectiveness") is not None]) if any(r.get("proposerEffectiveness") is not None for r in all_results) else 0
                                avg_uptime = sum(r.get("uptime", 0) for r in all_results) / total_days if total_days > 0 else 0
                                avg_correctness = sum(r.get("avgCorrectness", 0) for r in all_results) / total_days if total_days > 0 else 0
                                avg_inclusion_delay = sum(r.get("avgInclusionDelay", 0) for r in all_results) / total_days if total_days > 0 else 0
                                
                                # Display summary metrics
                                col1, col2, col3, col4 = st.columns(4)
                                with col1:
                                    st.metric("Total Validators", total_validators)
                                    st.metric("Avg Validator Effectiveness", f"{avg_validator_eff:.2f}%")
                                with col2:
                                    st.metric("Avg Attester Effectiveness", f"{avg_attester_eff:.2f}%")
                                    st.metric("Avg Proposer Effectiveness", f"{avg_proposer_eff:.2f}%")
                                with col3:
                                    st.metric("Avg Uptime", f"{avg_uptime * 100:.2f}%")
                                    st.metric("Avg Correctness", f"{avg_correctness * 100:.2f}%")
                                with col4:
                                    st.metric("Avg Inclusion Delay", f"{avg_inclusion_delay:.2f}")
                                
                                # Per-validator summary in expander
                                with st.expander("Per-Validator Summary", expanded=False):
                                    # Aggregate data per validator
                                    import pandas as pd
                                    
                                    agg_data = []
                                    for idx, validator_records in validators_data.items():
                                        pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                                        
                                        # Sort by date to get first and last
                                        sorted_records = sorted(validator_records, key=lambda x: x.get('startDate', ''))
                                        
                                        # Calculate averages for this validator
                                        num_days = len(validator_records)
                                        avg_val_eff = sum(r.get('validatorEffectiveness', 0) for r in validator_records) / num_days if num_days > 0 else 0
                                        avg_att_eff = sum(r.get('attesterEffectiveness', 0) for r in validator_records) / num_days if num_days > 0 else 0
                                        
                                        proposer_days = [r for r in validator_records if r.get('proposerEffectiveness') is not None]
                                        avg_prop_eff = sum(r.get('proposerEffectiveness', 0) for r in proposer_days) / len(proposer_days) if proposer_days else 0
                                        
                                        avg_upt = sum(r.get('uptime', 0) for r in validator_records) / num_days if num_days > 0 else 0
                                        avg_corr = sum(r.get('avgCorrectness', 0) for r in validator_records) / num_days if num_days > 0 else 0
                                        avg_inc_delay = sum(r.get('avgInclusionDelay', 0) for r in validator_records) / num_days if num_days > 0 else 0
                                        total_inc_delay = sum(r.get('sumInclusionDelay', 0) for r in validator_records)
                                        
                                        agg_data.append({
                                            'Pubkey': pubkey,
                                            'Index': idx,
                                            'Days': num_days,
                                            'First Date': sorted_records[0].get('startDate', 'N/A') if sorted_records else 'N/A',
                                            'Last Date': sorted_records[-1].get('startDate', 'N/A') if sorted_records else 'N/A',
                                            'Avg Val Eff (%)': f"{avg_val_eff:.2f}",
                                            'Avg Att Eff (%)': f"{avg_att_eff:.2f}",
                                            'Avg Prop Eff (%)': f"{avg_prop_eff:.2f}" if proposer_days else "N/A",
                                            'Proposer Days': len(proposer_days),
                                            'Avg Uptime (%)': f"{avg_upt * 100:.2f}",
                                            'Avg Correctness (%)': f"{avg_corr * 100:.2f}",
                                            'Avg Inc Delay': f"{avg_inc_delay:.2f}",
                                            'Total Inc Delay': total_inc_delay
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
                                        file_name=f"validator_effectiveness_summary_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
                                        mime="text/csv"
                                    )
                                
                                # Daily breakdown in expander
                                with st.expander("Daily Breakdown", expanded=False):
                                    # Build daily table data
                                    daily_data = []
                                    for result in all_results:
                                        idx = result.get("validatorIndex", 0)
                                        pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                                        
                                        daily_data.append({
                                            'Pubkey': pubkey,
                                            'Index': idx,
                                            'Date': result.get("startDate", "N/A"),
                                            'Validator Eff (%)': f"{result.get('validatorEffectiveness', 0):.2f}",
                                            'Attester Eff (%)': f"{result.get('attesterEffectiveness', 0):.2f}",
                                            'Proposer Eff (%)': f"{result.get('proposerEffectiveness', 0):.2f}" if result.get('proposerEffectiveness') is not None else "N/A",
                                            'Uptime (%)': f"{result.get('uptime', 0) * 100:.2f}",
                                            'Avg Correctness (%)': f"{result.get('avgCorrectness', 0) * 100:.2f}",
                                            'Avg Inclusion Delay': f"{result.get('avgInclusionDelay', 0):.2f}",
                                            'Sum Inclusion Delay': result.get('sumInclusionDelay', 0),
                                            'Missed Attestations': result.get('missedAttestations', 0),
                                            'Wrong Head Votes': result.get('wrongHeadVotes', 0),
                                            'Wrong Target Votes': result.get('wrongTargetVotes', 0),
                                            'Wrong Source Votes': result.get('wrongSourceVotes', 0)
                                        })
                                    
                                    daily_df = pd.DataFrame(daily_data)
                                    
                                    # Sort by validator index and date
                                    if 'Index' in daily_df.columns and 'Date' in daily_df.columns:
                                        daily_df = daily_df.sort_values(['Index', 'Date'])
                                    
                                    # Display the dataframe
                                    st.dataframe(
                                        daily_df,
                                        height=600,
                                        use_container_width=True,
                                        hide_index=True
                                    )
                                    
                                    # Add download button
                                    daily_csv = daily_df.to_csv(index=False)
                                    st.download_button(
                                        label="📥 Download CSV",
                                        data=daily_csv,
                                        file_name=f"validator_effectiveness_daily_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
                                        mime="text/csv"
                                    )
                            else:
                                st.warning("No effectiveness data returned from API")
                    except Exception as e:
                        st.error(f"Error in Rated API test: {type(e).__name__}: {str(e)}")
        
        # Rated Attestations API
        if st.session_state.get('validator_performance_data_loaded') and pubkey_to_index and current_network == 'mainnet':
            with st.expander("rated.network - Attestations", expanded=True):
                with st.spinner("Loading attestation data from Rated..."):
                    try:
                        # Check if API key is set
                        import os
                        if not os.getenv('RATED_API_KEY'):
                            st.error("RATED_API_KEY environment variable not set. Please set it to use Rated API.")
                            st.info("Get your API key from https://www.rated.network/")
                        else:
                            # Get list of all validator indices
                            limited_indices = list(pubkey_to_index.values())
                            
                            # Get configured time range
                            time_range_config = st.session_state.get('validator_performance_time_range', {})
                            
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
                            else:
                                # Default to last 7 days
                                end_date = datetime.utcnow()
                                start_date = end_date - timedelta(days=7)
                            
                            # Get excluded ranges for filtering later
                            excluded_ranges = st.session_state.get('validator_performance_excluded_ranges', [])
                            
                            # Call Rated API v1 directly with httpx for attestations
                            url = "https://api.rated.network/v1/eth/validators"
                            
                            headers = {
                                "Authorization": f"Bearer {os.getenv('RATED_API_KEY')}"
                            }
                            
                            # Convert dates for API
                            from_date = start_date.date() if isinstance(start_date, datetime) else start_date
                            to_date = end_date.date() if isinstance(end_date, datetime) else end_date
                            
                            # Validate dates aren't in the future
                            today = datetime.utcnow().date()
                            if to_date > today:
                                st.warning(f"End date {to_date} is in the future. Adjusting to today ({today})")
                                to_date = today
                            if from_date > today:
                                st.warning(f"Start date {from_date} is in the future. Adjusting to 7 days ago")
                                from_date = today - timedelta(days=7)
                            
                            # Build base params for individual validator requests
                            base_params = {
                                "limit": 1000,
                                "sortOrder": "asc",
                                "granularity": "day",
                                "fromDate": from_date.strftime('%Y-%m-%d'),
                                "toDate": to_date.strftime('%Y-%m-%d')
                            }
                            
                            # Collect all attestation results
                            all_attestation_results = []
                            unfiltered_count = 0
                            successful_validators = 0
                            
                            # Rate limiting for Rated API (2 requests per second)
                            import time
                            last_request_time = 0
                            min_interval = 0.5  # 500ms between requests = 2 requests per second
                            
                            # Make individual requests per validator
                            with httpx.Client() as client:
                                for i, idx in enumerate(limited_indices):
                                    try:
                                        # Rate limiting
                                        current_time = time.time()
                                        time_since_last = current_time - last_request_time
                                        if time_since_last < min_interval:
                                            time.sleep(min_interval - time_since_last)
                                        
                                        # Build URL for attestations endpoint
                                        full_url = f"{url}/{idx}/attestations"
                                        
                                        
                                        # Make request with retry logic for rate limits
                                        max_retries = 3
                                        for retry in range(max_retries):
                                            response = client.get(full_url, params=base_params, headers=headers, timeout=30.0)
                                            
                                            if response.status_code == 429:
                                                # Rate limited - wait and retry
                                                retry_after = int(response.headers.get('Retry-After', '1'))
                                                st.warning(f"Rate limited. Waiting {retry_after} seconds...")
                                                time.sleep(retry_after)
                                                continue
                                            
                                            response.raise_for_status()
                                            break  # Success, exit retry loop
                                        
                                        last_request_time = time.time()
                                        
                                        data = response.json()
                                        
                                        # Process results for this validator
                                        if isinstance(data, dict) and "results" in data and data["results"]:
                                            successful_validators += 1
                                            # Results are directly in array for attestations endpoint
                                            results_data = data["results"]
                                            
                                            
                                            for result in results_data:
                                                # Validator index is already in the result
                                                # result['validator_index'] = idx  # Already has validatorIndex
                                                unfiltered_count += 1
                                                
                                                # Get the date from the result
                                                result_date_str = result.get("date") or result.get("startDate")
                                                if result_date_str and excluded_ranges:
                                                    # Parse the date
                                                    result_date = datetime.strptime(result_date_str, '%Y-%m-%d').date()
                                                    
                                                    # Check if this date falls within any excluded range
                                                    is_excluded = False
                                                    for exclusion in excluded_ranges:
                                                        exc_start = exclusion['start']
                                                        exc_end = exclusion['end']
                                                        if exc_start <= result_date <= exc_end:
                                                            is_excluded = True
                                                            break
                                                    
                                                    # Only include if not excluded
                                                    if not is_excluded:
                                                        all_attestation_results.append(result)
                                                else:
                                                    # No exclusions or no date found, include it
                                                    all_attestation_results.append(result)
                                        
                                            
                                    except httpx.HTTPStatusError as e:
                                        st.error(f"Rated API Error for validator {idx}: HTTP {e.response.status_code}")
                                        continue
                                    except Exception as e:
                                        st.error(f"Error fetching validator {idx}: {type(e).__name__}: {str(e)}")
                                        continue
                                
                                # Show summary info
                                if successful_validators < len(limited_indices):
                                    st.info(f"Found attestation data for {successful_validators}/{len(limited_indices)} validators in Rated")
                                
                                # Show filtering info if applicable
                                if excluded_ranges and unfiltered_count > len(all_attestation_results):
                                    st.info(f"Filtered out {unfiltered_count - len(all_attestation_results)} daily records due to date exclusions")
                            
                            # Process all collected attestation results
                            if all_attestation_results:
                                # Group by validator
                                attestation_validators_data = {}
                                for result in all_attestation_results:
                                    vid = result.get("validatorIndex", 0)
                                    if vid not in attestation_validators_data:
                                        attestation_validators_data[vid] = []
                                    attestation_validators_data[vid].append(result)
                                
                                # Show summary
                                st.subheader("Summary")
                                
                                # Create reverse mapping from index to pubkey
                                index_to_pubkey = {v: k for k, v in pubkey_to_index.items()}
                                
                                # Calculate aggregated metrics
                                total_validators = len(attestation_validators_data)
                                total_days = len(all_attestation_results)
                                
                                # Calculate averages across all daily records
                                avg_attester_effectiveness = sum(r.get("attesterEffectiveness", 0) for r in all_attestation_results) / total_days if total_days > 0 else 0
                                avg_correctness = sum(r.get("avgCorrectness", 0) for r in all_attestation_results) / total_days if total_days > 0 else 0
                                avg_inclusion_delay = sum(r.get("avgInclusionDelay", 0) for r in all_attestation_results) / total_days if total_days > 0 else 0
                                total_missed = sum(r.get("sumMissedAttestations", 0) for r in all_attestation_results)
                                total_wrong_head = sum(r.get("sumWrongHeadVotes", 0) for r in all_attestation_results)
                                total_wrong_target = sum(r.get("sumWrongTargetVotes", 0) for r in all_attestation_results)
                                total_late_head = sum(r.get("sumLateHeadVotes", 0) for r in all_attestation_results)
                                
                                # Display summary metrics
                                col1, col2, col3, col4 = st.columns(4)
                                with col1:
                                    st.metric("Total Validators", total_validators)
                                    st.metric("Avg Attester Effectiveness", f"{avg_attester_effectiveness:.2f}%")
                                with col2:
                                    st.metric("Avg Correctness", f"{avg_correctness * 100:.2f}%")
                                    st.metric("Avg Inclusion Delay", f"{avg_inclusion_delay:.2f}")
                                with col3:
                                    st.metric("Total Missed Attestations", f"{total_missed:,}")
                                    st.metric("Total Wrong Head Votes", f"{total_wrong_head:,}")
                                with col4:
                                    st.metric("Total Wrong Target Votes", f"{total_wrong_target:,}")
                                    st.metric("Total Late Head Votes", f"{total_late_head:,}")
                                
                                # Per-validator summary in expander
                                with st.expander("Per-Validator Attestation Summary", expanded=False):
                                    # Aggregate data per validator
                                    import pandas as pd
                                    
                                    agg_data = []
                                    for idx, validator_records in attestation_validators_data.items():
                                        pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                                        
                                        # Sort by date to get first and last
                                        sorted_records = sorted(validator_records, key=lambda x: x.get('date', x.get('startDate', '')))
                                        
                                        # Calculate aggregates for this validator
                                        num_days = len(validator_records)
                                        avg_att_eff = sum(r.get('attesterEffectiveness', 0) for r in validator_records) / num_days if num_days > 0 else 0
                                        avg_corr = sum(r.get('avgCorrectness', 0) for r in validator_records) / num_days if num_days > 0 else 0
                                        avg_inc_del = sum(r.get('avgInclusionDelay', 0) for r in validator_records) / num_days if num_days > 0 else 0
                                        total_assignments = sum(r.get('totalAttestationAssignments', 0) for r in validator_records)
                                        total_attestations = sum(r.get('totalAttestations', 0) for r in validator_records)
                                        total_missed = sum(r.get('sumMissedAttestations', 0) for r in validator_records)
                                        total_wrong_head = sum(r.get('sumWrongHeadVotes', 0) for r in validator_records)
                                        total_wrong_target = sum(r.get('sumWrongTargetVotes', 0) for r in validator_records)
                                        total_late_head = sum(r.get('sumLateHeadVotes', 0) for r in validator_records)
                                        
                                        agg_data.append({
                                            'Pubkey': pubkey,
                                            'Index': idx,
                                            'Days': num_days,
                                            'First Date': sorted_records[0].get('date', sorted_records[0].get('startDate', 'N/A')) if sorted_records else 'N/A',
                                            'Last Date': sorted_records[-1].get('date', sorted_records[-1].get('startDate', 'N/A')) if sorted_records else 'N/A',
                                            'Avg Att Eff (%)': f"{avg_att_eff:.2f}",
                                            'Avg Correctness (%)': f"{avg_corr * 100:.2f}",
                                            'Avg Inc Delay': f"{avg_inc_del:.2f}",
                                            'Total Assignments': total_assignments,
                                            'Total Attestations': total_attestations,
                                            'Total Missed': total_missed,
                                            'Wrong Head': total_wrong_head,
                                            'Wrong Target': total_wrong_target,
                                            'Late Head': total_late_head
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
                                        file_name=f"validator_attestation_summary_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
                                        mime="text/csv"
                                    )
                                
                                # Daily breakdown in expander
                                with st.expander("Daily Attestation Breakdown", expanded=False):
                                    # Build daily table data
                                    daily_data = []
                                    for result in all_attestation_results:
                                        idx = result.get("validatorIndex", 0)
                                        pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                                        
                                        daily_data.append({
                                            'Pubkey': pubkey,
                                            'Index': idx,
                                            'Date': result.get("date", result.get("startDate", "N/A")),
                                            'Attester Eff (%)': f"{result.get('attesterEffectiveness', 0):.2f}",
                                            'Correctness (%)': f"{result.get('avgCorrectness', 0) * 100:.2f}",
                                            'Avg Inc Delay': f"{result.get('avgInclusionDelay', 0):.2f}",
                                            'Sum Inc Delay': result.get('sumInclusionDelay', 0),
                                            'Assignments': result.get('totalAttestationAssignments', 0),
                                            'Attestations': result.get('totalAttestations', 0),
                                            'Unique Attest': result.get('totalUniqueAttestations', 0),
                                            'Missed': result.get('sumMissedAttestations', 0),
                                            'Correct Head': result.get('sumCorrectHead', 0),
                                            'Correct Target': result.get('sumCorrectTarget', 0),
                                            'Correct Source': result.get('sumCorrectSource', 0),
                                            'Wrong Head': result.get('sumWrongHeadVotes', 0),
                                            'Wrong Target': result.get('sumWrongTargetVotes', 0),
                                            'Late Head': result.get('sumLateHeadVotes', 0),
                                            'Late Target': result.get('sumLateTargetVotes', 0),
                                            'Late Source': result.get('sumLateSourceVotes', 0),
                                            'Uptime': f"{result.get('uptime', 0) * 100:.1f}%"
                                        })
                                    
                                    daily_df = pd.DataFrame(daily_data)
                                    
                                    # Sort by validator index and date
                                    if 'Index' in daily_df.columns and 'Date' in daily_df.columns:
                                        daily_df = daily_df.sort_values(['Index', 'Date'])
                                    
                                    # Display the dataframe
                                    st.dataframe(
                                        daily_df,
                                        height=600,
                                        use_container_width=True,
                                        hide_index=True
                                    )
                                    
                                    # Add download button
                                    daily_csv = daily_df.to_csv(index=False)
                                    st.download_button(
                                        label="📥 Download CSV",
                                        data=daily_csv,
                                        file_name=f"validator_attestation_daily_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
                                        mime="text/csv"
                                    )
                            else:
                                st.warning("No attestation data returned from API")
                    except Exception as e:
                        st.error(f"Error in Rated Attestations API: {type(e).__name__}: {str(e)}")
        
        # Rated Proposals API
        if st.session_state.get('validator_performance_data_loaded') and pubkey_to_index and current_network == 'mainnet':
            with st.expander("rated.network - Proposals", expanded=True):
                with st.spinner("Loading proposal data from Rated..."):
                    try:
                        # Check if API key is set
                        import os
                        if not os.getenv('RATED_API_KEY'):
                            st.error("RATED_API_KEY environment variable not set. Please set it to use Rated API.")
                            st.info("Get your API key from https://www.rated.network/")
                        else:
                            # Get list of all validator indices
                            limited_indices = list(pubkey_to_index.values())
                            
                            # Get configured time range
                            time_range_config = st.session_state.get('validator_performance_time_range', {})
                            
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
                            else:
                                # Default to last 7 days
                                end_date = datetime.utcnow()
                                start_date = end_date - timedelta(days=7)
                            
                            # Get excluded ranges for filtering later
                            excluded_ranges = st.session_state.get('validator_performance_excluded_ranges', [])
                            
                            # Call Rated API v1 directly with httpx for proposals
                            url = "https://api.rated.network/v1/eth/validators"
                            
                            headers = {
                                "Authorization": f"Bearer {os.getenv('RATED_API_KEY')}"
                            }
                            
                            # Convert dates for API
                            from_date = start_date.date() if isinstance(start_date, datetime) else start_date
                            to_date = end_date.date() if isinstance(end_date, datetime) else end_date
                            
                            # Validate dates aren't in the future
                            today = datetime.utcnow().date()
                            if to_date > today:
                                st.warning(f"End date {to_date} is in the future. Adjusting to today ({today})")
                                to_date = today
                            if from_date > today:
                                st.warning(f"Start date {from_date} is in the future. Adjusting to 7 days ago")
                                from_date = today - timedelta(days=7)
                            
                            # Build base params for individual validator requests
                            base_params = {
                                "limit": 1000,
                                "sortOrder": "asc",
                                "granularity": "day",
                                "fromDate": from_date.strftime('%Y-%m-%d'),
                                "toDate": to_date.strftime('%Y-%m-%d')
                            }
                            
                            # Collect all proposal results
                            all_proposal_results = []
                            unfiltered_count = 0
                            successful_validators = 0
                            
                            # Rate limiting for Rated API (2 requests per second)
                            import time
                            last_request_time = 0
                            min_interval = 0.5  # 500ms between requests = 2 requests per second
                            
                            # Make individual requests per validator
                            with httpx.Client() as client:
                                for i, idx in enumerate(limited_indices):
                                    try:
                                        # Rate limiting
                                        current_time = time.time()
                                        time_since_last = current_time - last_request_time
                                        if time_since_last < min_interval:
                                            time.sleep(min_interval - time_since_last)
                                        
                                        # Build URL for proposals endpoint
                                        full_url = f"{url}/{idx}/proposals"
                                        
                                        
                                        # Make request with retry logic for rate limits
                                        max_retries = 3
                                        for retry in range(max_retries):
                                            response = client.get(full_url, params=base_params, headers=headers, timeout=30.0)
                                            
                                            if response.status_code == 429:
                                                # Rate limited - wait and retry
                                                retry_after = int(response.headers.get('Retry-After', '1'))
                                                st.warning(f"Rate limited. Waiting {retry_after} seconds...")
                                                time.sleep(retry_after)
                                                continue
                                            
                                            response.raise_for_status()
                                            break  # Success, exit retry loop
                                        
                                        last_request_time = time.time()
                                        
                                        data = response.json()
                                        
                                        # Process results for this validator
                                        if isinstance(data, dict) and "results" in data and data["results"]:
                                            successful_validators += 1
                                            # Results are directly in array for proposals endpoint
                                            results_data = data["results"]
                                            
                                            
                                            for result in results_data:
                                                # Validator index is already in the result as validatorIndex
                                                unfiltered_count += 1
                                                
                                                # Get the date from the result
                                                result_date_str = result.get("date") or result.get("startDate")
                                                if result_date_str and excluded_ranges:
                                                    # Parse the date
                                                    result_date = datetime.strptime(result_date_str, '%Y-%m-%d').date()
                                                    
                                                    # Check if this date falls within any excluded range
                                                    is_excluded = False
                                                    for exclusion in excluded_ranges:
                                                        exc_start = exclusion['start']
                                                        exc_end = exclusion['end']
                                                        if exc_start <= result_date <= exc_end:
                                                            is_excluded = True
                                                            break
                                                    
                                                    # Only include if not excluded
                                                    if not is_excluded:
                                                        all_proposal_results.append(result)
                                                else:
                                                    # No exclusions or no date found, include it
                                                    all_proposal_results.append(result)
                                        
                                            
                                    except httpx.HTTPStatusError as e:
                                        st.error(f"Rated API Error for validator {idx}: HTTP {e.response.status_code}")
                                        continue
                                    except Exception as e:
                                        st.error(f"Error fetching validator {idx}: {type(e).__name__}: {str(e)}")
                                        continue
                                
                                # Show summary info
                                if successful_validators < len(limited_indices):
                                    st.info(f"Found proposal data for {successful_validators}/{len(limited_indices)} validators in Rated")
                                
                                # Show filtering info if applicable
                                if excluded_ranges and unfiltered_count > len(all_proposal_results):
                                    st.info(f"Filtered out {unfiltered_count - len(all_proposal_results)} daily records due to date exclusions")
                            
                            # Process all collected proposal results
                            if all_proposal_results:
                                # Group by validator
                                proposal_validators_data = {}
                                for result in all_proposal_results:
                                    vid = result.get("validatorIndex", 0)
                                    if vid not in proposal_validators_data:
                                        proposal_validators_data[vid] = []
                                    proposal_validators_data[vid].append(result)
                                
                                # Show summary
                                st.subheader("Summary")
                                
                                # Create reverse mapping from index to pubkey
                                index_to_pubkey = {v: k for k, v in pubkey_to_index.items()}
                                
                                # Calculate aggregated metrics
                                total_validators = len(proposal_validators_data)
                                total_days = len(all_proposal_results)
                                
                                # Calculate totals across all records
                                total_duties = sum(r.get("proposerDutiesCount", 0) for r in all_proposal_results)
                                total_proposed = sum(r.get("proposedCount", 0) for r in all_proposal_results)
                                total_empty_proposals = sum(r.get("executionProposedEmptyCount", 0) for r in all_proposal_results)
                                
                                # Calculate effectiveness
                                proposal_effectiveness = (total_proposed / total_duties * 100) if total_duties > 0 else 0
                                empty_proposal_rate = (total_empty_proposals / total_proposed * 100) if total_proposed > 0 else 0
                                
                                # Display summary metrics
                                col1, col2, col3, col4 = st.columns(4)
                                with col1:
                                    st.metric("Total Validators", total_validators)
                                    st.metric("Total Proposer Duties", f"{total_duties:,}")
                                with col2:
                                    st.metric("Total Blocks Proposed", f"{total_proposed:,}")
                                    st.metric("Proposal Effectiveness", f"{proposal_effectiveness:.1f}%")
                                with col3:
                                    st.metric("Empty Blocks Proposed", f"{total_empty_proposals:,}")
                                    st.metric("Empty Block Rate", f"{empty_proposal_rate:.1f}%")
                                with col4:
                                    st.metric("Missed Proposals", f"{total_duties - total_proposed:,}")
                                    if total_duties > 0:
                                        st.metric("Miss Rate", f"{((total_duties - total_proposed) / total_duties * 100):.1f}%")
                                
                                # Per-validator summary in expander
                                with st.expander("Per-Validator Proposal Summary", expanded=False):
                                    # Aggregate data per validator
                                    import pandas as pd
                                    
                                    agg_data = []
                                    for idx, validator_records in proposal_validators_data.items():
                                        pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                                        
                                        # Sort by date to get first and last
                                        sorted_records = sorted(validator_records, key=lambda x: x.get('date', x.get('startDate', '')))
                                        
                                        # Calculate aggregates for this validator
                                        num_days = len(validator_records)
                                        total_duties = sum(r.get('proposerDutiesCount', 0) for r in validator_records)
                                        total_proposed = sum(r.get('proposedCount', 0) for r in validator_records)
                                        total_empty = sum(r.get('executionProposedEmptyCount', 0) for r in validator_records)
                                        
                                        effectiveness = (total_proposed / total_duties * 100) if total_duties > 0 else 0
                                        empty_rate = (total_empty / total_proposed * 100) if total_proposed > 0 else 0
                                        
                                        agg_data.append({
                                            'Pubkey': pubkey,
                                            'Index': idx,
                                            'Days': num_days,
                                            'First Date': sorted_records[0].get('date', sorted_records[0].get('startDate', 'N/A')) if sorted_records else 'N/A',
                                            'Last Date': sorted_records[-1].get('date', sorted_records[-1].get('startDate', 'N/A')) if sorted_records else 'N/A',
                                            'Total Duties': total_duties,
                                            'Blocks Proposed': total_proposed,
                                            'Missed': total_duties - total_proposed,
                                            'Effectiveness (%)': f"{effectiveness:.1f}",
                                            'Empty Blocks': total_empty,
                                            'Empty Rate (%)': f"{empty_rate:.1f}" if total_proposed > 0 else "N/A"
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
                                        file_name=f"validator_proposal_summary_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
                                        mime="text/csv"
                                    )
                                
                                # Daily breakdown in expander
                                with st.expander("Daily Proposal Breakdown", expanded=False):
                                    # Build daily table data
                                    daily_data = []
                                    for result in all_proposal_results:
                                        idx = result.get("validatorIndex", 0)
                                        pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                                        
                                        duties = result.get('proposerDutiesCount', 0)
                                        proposed = result.get('proposedCount', 0)
                                        
                                        daily_data.append({
                                            'Pubkey': pubkey,
                                            'Index': idx,
                                            'Date': result.get("date", result.get("startDate", "N/A")),
                                            'Proposer Duties': duties,
                                            'Blocks Proposed': proposed,
                                            'Missed': duties - proposed,
                                            'Effectiveness (%)': f"{(proposed / duties * 100):.1f}" if duties > 0 else "N/A",
                                            'Empty Blocks': result.get('executionProposedEmptyCount', 0),
                                            'Empty Rate (%)': f"{(result.get('executionProposedEmptyCount', 0) / proposed * 100):.1f}" if proposed > 0 else "N/A",
                                            'Day': result.get('day', 'N/A'),
                                            'Hour': result.get('hour', 'N/A')
                                        })
                                    
                                    daily_df = pd.DataFrame(daily_data)
                                    
                                    # Sort by validator index and date
                                    if 'Index' in daily_df.columns and 'Date' in daily_df.columns:
                                        daily_df = daily_df.sort_values(['Index', 'Date'])
                                    
                                    # Display the dataframe
                                    st.dataframe(
                                        daily_df,
                                        height=600,
                                        use_container_width=True,
                                        hide_index=True
                                    )
                                    
                                    # Add download button
                                    daily_csv = daily_df.to_csv(index=False)
                                    st.download_button(
                                        label="📥 Download CSV",
                                        data=daily_csv,
                                        file_name=f"validator_proposal_daily_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
                                        mime="text/csv"
                                    )
                            else:
                                st.warning("No proposal data returned from API")
                    except Exception as e:
                        st.error(f"Error in Rated Proposals API: {type(e).__name__}: {str(e)}")
        
        # Combined Analysis Summary
        if st.session_state.get('validator_performance_data_loaded') and pubkey_to_index:
            beaconchain_results = st.session_state.get('validator_performance_api_test_results')
            
            # Check if we have data from both sources
            has_beaconchain = beaconchain_results and beaconchain_results.get('stats_data', [])
            has_rated = 'all_results' in locals() and all_results
            
            if has_beaconchain or has_rated:
                st.divider()
                st.header("Performance Analysis Summary")
                
                # Create reverse mapping for pubkeys
                index_to_pubkey = {v: k for k, v in pubkey_to_index.items()}
                
                # Analyze BeaconChain data
                bc_validator_stats = {}
                if has_beaconchain:
                    for stat in beaconchain_results.get('stats_data', []):
                        idx = stat.get('validatorindex', 0)
                        if idx not in bc_validator_stats:
                            bc_validator_stats[idx] = {
                                'missed_blocks': 0,
                                'missed_attestations': 0,
                                'missed_sync': 0,
                                'proposed_blocks': 0,
                                'slashings': 0,
                                'days': 0
                            }
                        bc_validator_stats[idx]['missed_blocks'] += stat.get('missed_blocks', 0)
                        bc_validator_stats[idx]['missed_attestations'] += stat.get('missed_attestations', 0)
                        bc_validator_stats[idx]['missed_sync'] += stat.get('missed_sync', 0)
                        bc_validator_stats[idx]['proposed_blocks'] += stat.get('proposed_blocks', 0)
                        bc_validator_stats[idx]['slashings'] += stat.get('attester_slashings', 0) + stat.get('proposer_slashings', 0)
                        bc_validator_stats[idx]['days'] += 1
                
                # Analyze Rated data
                rated_validator_stats = {}
                if has_rated and 'validators_data' in locals():
                    for idx, records in validators_data.items():
                        total_days = len(records)
                        avg_effectiveness = sum(r.get('validatorEffectiveness', 0) for r in records) / total_days if total_days > 0 else 0
                        avg_uptime = sum(r.get('uptime', 0) for r in records) / total_days if total_days > 0 else 0
                        avg_correctness = sum(r.get('avgCorrectness', 0) for r in records) / total_days if total_days > 0 else 0
                        avg_inclusion_delay = sum(r.get('avgInclusionDelay', 0) for r in records) / total_days if total_days > 0 else 0
                        
                        rated_validator_stats[idx] = {
                            'avg_effectiveness': avg_effectiveness,
                            'avg_uptime': avg_uptime,
                            'avg_correctness': avg_correctness,
                            'avg_inclusion_delay': avg_inclusion_delay,
                            'days': total_days
                        }
                
                # Performance Categories based on Rated docs
                st.subheader("Key Findings")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("### 🚨 Critical Issues")
                    critical_data = []
                    
                    # Check for slashings
                    for idx, stats in bc_validator_stats.items():
                        if stats['slashings'] > 0:
                            pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                            critical_data.append({
                                'Validator': pubkey,
                                'Index': idx,
                                'Issue': 'Slashing Event',
                                'Details': f"{stats['slashings']} slashing(s)",
                                'Threshold': 'Any occurrence'
                            })
                    
                    # Check for very low effectiveness (< 90%)
                    for idx, stats in rated_validator_stats.items():
                        if stats['avg_effectiveness'] < 90:
                            pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                            critical_data.append({
                                'Validator': pubkey,
                                'Index': idx,
                                'Issue': 'Low Effectiveness',
                                'Details': f"{stats['avg_effectiveness']:.1f}%",
                                'Threshold': '<90%'
                            })
                    
                    if critical_data:
                        import pandas as pd
                        critical_df = pd.DataFrame(critical_data)
                        st.dataframe(
                            critical_df,
                            height=min(300, 50 + len(critical_data) * 35),
                            use_container_width=True,
                            hide_index=True
                        )
                        st.caption("**Thresholds**: Slashings = Any occurrence | Effectiveness < 90%")
                    else:
                        st.success("No critical issues found")
                
                with col2:
                    st.markdown("### ⚠️ Performance Concerns")
                    concerns_data = []
                    
                    # Check for high missed attestations (> 1% of total attestations)
                    # Ethereum has ~225 attestation duties per day (32 slots per epoch * 225 epochs per day / 32 slots per attestation)
                    ATTESTATIONS_PER_DAY = 225
                    for idx, stats in bc_validator_stats.items():
                        total_attestation_duties = stats['days'] * ATTESTATIONS_PER_DAY
                        miss_rate = (stats['missed_attestations'] / total_attestation_duties * 100) if total_attestation_duties > 0 else 0
                        if miss_rate > 1:
                            pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                            concerns_data.append({
                                'Validator': pubkey,
                                'Index': idx,
                                'Concern': 'High Attestation Miss Rate',
                                'Value': f"{miss_rate:.1f}%",
                                'Threshold': '>1%'
                            })
                    
                    # Check for low uptime (< 99%)
                    for idx, stats in rated_validator_stats.items():
                        if stats['avg_uptime'] < 0.99:
                            pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                            concerns_data.append({
                                'Validator': pubkey,
                                'Index': idx,
                                'Concern': 'Low Uptime',
                                'Value': f"{stats['avg_uptime']*100:.1f}%",
                                'Threshold': '<99%'
                            })
                    
                    if concerns_data:
                        import pandas as pd
                        concerns_df = pd.DataFrame(concerns_data)
                        st.dataframe(
                            concerns_df,
                            height=min(300, 50 + len(concerns_data) * 35),
                            use_container_width=True,
                            hide_index=True
                        )
                        st.caption("**Thresholds**: Attestation miss rate >1% of total attestations | Uptime <99%")
                    else:
                        st.info("No major performance concerns")
                
                # Aggregated Metrics Summary
                st.divider()
                st.subheader("Aggregated Performance Metrics")
                
                # Calculate aggregate metrics from all data sources
                
                # BeaconChain totals
                bc_total_missed_blocks = sum(stats.get('missed_blocks', 0) for stats in bc_validator_stats.values()) if bc_validator_stats else 0
                bc_total_missed_attestations = sum(stats.get('missed_attestations', 0) for stats in bc_validator_stats.values()) if bc_validator_stats else 0
                bc_total_missed_sync = sum(stats.get('missed_sync', 0) for stats in bc_validator_stats.values()) if bc_validator_stats else 0
                bc_total_slashings = sum(stats.get('slashings', 0) for stats in bc_validator_stats.values()) if bc_validator_stats else 0
                bc_total_proposed = sum(stats.get('proposed_blocks', 0) for stats in bc_validator_stats.values()) if bc_validator_stats else 0
                
                # Rated effectiveness averages
                if rated_validator_stats:
                    avg_validator_effectiveness = sum(stats['avg_effectiveness'] for stats in rated_validator_stats.values()) / len(rated_validator_stats)
                    avg_uptime = sum(stats['avg_uptime'] for stats in rated_validator_stats.values()) / len(rated_validator_stats) * 100
                    avg_correctness = sum(stats['avg_correctness'] for stats in rated_validator_stats.values()) / len(rated_validator_stats) * 100
                    avg_inclusion_delay = sum(stats['avg_inclusion_delay'] for stats in rated_validator_stats.values()) / len(rated_validator_stats)
                else:
                    avg_validator_effectiveness = avg_uptime = avg_correctness = avg_inclusion_delay = 0
                
                # Display aggregated metrics
                st.markdown("### beaconcha.in Data")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Proposed Blocks", f"{bc_total_proposed:,}", 
                             help="Successfully proposed blocks when selected")
                    st.metric("Missed Blocks", f"{bc_total_missed_blocks:,}", 
                             help="Failed to propose when selected by protocol")
                with col2:
                    st.metric("Missed Attestations", f"{bc_total_missed_attestations:,}",
                             help="Failed to submit attestation when assigned to committee")
                    st.metric("Missed Sync", f"{bc_total_missed_sync:,}",
                             help="Failed sync committee participation when selected")
                with col3:
                    st.metric("Total Slashings", f"{bc_total_slashings:,}",
                             help="Severe protocol violations resulting in penalties and ejection")
                with col4:
                    pass  # Empty for alignment
                
                if rated_validator_stats:
                    st.markdown("### rated.network Effectiveness")
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Avg Validator Effectiveness", f"{avg_validator_effectiveness:.2f}%",
                                 help="Weighted average of attester (97%) and proposer (3%) effectiveness. Target: >95%")
                    with col2:
                        st.metric("Avg Uptime", f"{avg_uptime:.2f}%",
                                 help="Percentage of epochs where validator performed at least one duty. Target: >99%")
                    with col3:
                        st.metric("Avg Correctness", f"{avg_correctness:.2f}%",
                                 help="Percentage of correct attestations (head, source, target). Target: >99%")
                    with col4:
                        st.metric("Avg Inclusion Delay", f"{avg_inclusion_delay:.2f}",
                                 help="Average slots between attestation and on-chain inclusion. Target: 1.0")
                
                # Attestations summary if available
                if 'all_attestation_results' in locals() and all_attestation_results:
                    st.markdown("### Attestation Performance")
                    total_att_missed = sum(r.get("sumMissedAttestations", 0) for r in all_attestation_results)
                    total_att_wrong_head = sum(r.get("sumWrongHeadVotes", 0) for r in all_attestation_results)
                    total_att_wrong_target = sum(r.get("sumWrongTargetVotes", 0) for r in all_attestation_results)
                    total_att_late_head = sum(r.get("sumLateHeadVotes", 0) for r in all_attestation_results)
                    avg_att_effectiveness = sum(r.get("attesterEffectiveness", 0) for r in all_attestation_results) / len(all_attestation_results) if all_attestation_results else 0
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Avg Attester Effectiveness", f"{avg_att_effectiveness:.2f}%",
                                 help="Measures how well validator performed attestation duties. Target: >95%")
                    with col2:
                        st.metric("Total Missed", f"{total_att_missed:,}",
                                 help="Attestations not submitted when assigned")
                        st.metric("Wrong Head Votes", f"{total_att_wrong_head:,}",
                                 help="Attestations voting for incorrect chain head")
                    with col3:
                        st.metric("Wrong Target Votes", f"{total_att_wrong_target:,}",
                                 help="Attestations with incorrect target checkpoint")
                        st.metric("Late Head Votes", f"{total_att_late_head:,}",
                                 help="Attestations submitted late but voting correctly")
                    with col4:
                        pass
                
                # Proposals summary if available
                if 'all_proposal_results' in locals() and all_proposal_results:
                    st.markdown("### Block Proposal Performance")
                    total_prop_duties = sum(r.get("proposerDutiesCount", 0) for r in all_proposal_results)
                    total_prop_proposed = sum(r.get("proposedCount", 0) for r in all_proposal_results)
                    total_prop_empty = sum(r.get("executionProposedEmptyCount", 0) for r in all_proposal_results)
                    prop_effectiveness = (total_prop_proposed / total_prop_duties * 100) if total_prop_duties > 0 else 0
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Total Duties", f"{total_prop_duties:,}",
                                 help="Times randomly selected to propose blocks")
                        st.metric("Blocks Proposed", f"{total_prop_proposed:,}",
                                 help="Successfully proposed blocks")
                    with col2:
                        st.metric("Effectiveness", f"{prop_effectiveness:.1f}%",
                                 help="Percentage of assigned blocks successfully proposed. Target: 100%")
                    with col3:
                        st.metric("Empty Blocks", f"{total_prop_empty:,}",
                                 help="Blocks proposed without execution payload")
                        if total_prop_proposed > 0:
                            st.metric("Empty Rate", f"{(total_prop_empty/total_prop_proposed*100):.1f}%",
                                     help="Percentage of proposed blocks that were empty")
                    with col4:
                        st.metric("Missed Proposals", f"{total_prop_duties - total_prop_proposed:,}",
                                 help="Failed to propose when selected (severe issue)")
                
                st.caption("[beaconcha.in](https://beaconcha.in) | [rated.network](https://www.rated.network)")
                
                # Generate markdown report
                def generate_markdown_report():
                    """Generate a comprehensive markdown report of the analysis."""
                    report = []
                    
                    # Header
                    report.append("# Validator Performance Analysis Report")
                    report.append(f"\n**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
                    report.append(f"**Network**: {current_network}")
                    report.append(f"**Validators Analyzed**: {len(pubkey_to_index)}")
                    
                    # Time range info
                    time_range_config = st.session_state.get('validator_performance_time_range', {})
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
                        report.append(f"**Time Range**: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
                    
                    report.append("\n---\n")
                    
                    # Metrics Interpretation - moved to the beginning for context
                    report.append("## Metrics Interpretation\n")
                    report.append("### BeaconChain Metrics")
                    report.append("- **Missed Blocks**: Validator failed to propose a block when selected by the protocol")
                    report.append("- **Missed Attestations**: Failed to submit an attestation when assigned to a committee")
                    report.append("- **Missed Sync**: Failed to participate in sync committee duties when selected")
                    report.append("- **Slashings**: Severe protocol violations (e.g., double voting) resulting in penalties and ejection\n")
                    
                    report.append("### Rated Metrics")
                    report.append("#### Effectiveness Scores")
                    report.append("- **Validator Effectiveness**: Weighted average of attester (97%) and proposer (3%) effectiveness. Target: >95%")
                    report.append("- **Attester Effectiveness**: Measures attestation performance including correctness and inclusion speed. Target: >95%")
                    report.append("- **Proposer Effectiveness**: Percentage of assigned blocks successfully proposed. Target: 100%")
                    report.append("- **Uptime**: Percentage of epochs where validator performed at least one duty. Target: >99%\n")
                    
                    report.append("#### Attestation Metrics")
                    report.append("- **Correctness**: Percentage of attestations with correct head, source, and target votes. Target: >99%")
                    report.append("- **Inclusion Delay**: Average number of slots between attestation and on-chain inclusion. Target: 1.0")
                    report.append("- **Wrong Head/Target Votes**: Attestations voting for incorrect chain head or target checkpoint")
                    report.append("- **Late Head Votes**: Attestations submitted after optimal time but still voting correctly\n")
                    
                    report.append("#### Proposal Metrics")
                    report.append("- **Proposer Duties**: Number of times selected to propose blocks (random selection)")
                    report.append("- **Empty Blocks**: Blocks proposed without execution payload (no transactions)")
                    report.append("- **Missed Proposals**: Failed to propose when selected (severe performance issue)\n")
                    
                    # First analyze the data exactly like the dashboard does
                    # Analyze BeaconChain data
                    bc_validator_stats = {}
                    if has_beaconchain:
                        for stat in beaconchain_results.get('stats_data', []):
                            idx = stat.get('validatorindex', 0)
                            if idx not in bc_validator_stats:
                                bc_validator_stats[idx] = {
                                    'missed_blocks': 0,
                                    'missed_attestations': 0,
                                    'missed_sync': 0,
                                    'proposed_blocks': 0,
                                    'slashings': 0,
                                    'days': 0
                                }
                            bc_validator_stats[idx]['missed_blocks'] += stat.get('missed_blocks', 0)
                            bc_validator_stats[idx]['missed_attestations'] += stat.get('missed_attestations', 0)
                            bc_validator_stats[idx]['missed_sync'] += stat.get('missed_sync', 0)
                            bc_validator_stats[idx]['proposed_blocks'] += stat.get('proposed_blocks', 0)
                            bc_validator_stats[idx]['slashings'] += stat.get('attester_slashings', 0) + stat.get('proposer_slashings', 0)
                            bc_validator_stats[idx]['days'] += 1
                    
                    # Analyze Rated data
                    rated_validator_stats = {}
                    if has_rated and 'validators_data' in locals():
                        for idx, records in validators_data.items():
                            total_days = len(records)
                            avg_effectiveness = sum(r.get('validatorEffectiveness', 0) for r in records) / total_days if total_days > 0 else 0
                            avg_uptime = sum(r.get('uptime', 0) for r in records) / total_days if total_days > 0 else 0
                            avg_correctness = sum(r.get('avgCorrectness', 0) for r in records) / total_days if total_days > 0 else 0
                            avg_inclusion_delay = sum(r.get('avgInclusionDelay', 0) for r in records) / total_days if total_days > 0 else 0
                            
                            rated_validator_stats[idx] = {
                                'avg_effectiveness': avg_effectiveness,
                                'avg_uptime': avg_uptime,
                                'avg_correctness': avg_correctness,
                                'avg_inclusion_delay': avg_inclusion_delay,
                                'days': total_days
                            }
                    
                    # Key Findings section (matches the dashboard)
                    report.append("## Key Findings\n")
                    
                    # Critical Issues
                    critical_data = []
                    
                    # Check for slashings
                    for idx, stats in bc_validator_stats.items():
                        if stats['slashings'] > 0:
                            pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                            critical_data.append({
                                'Validator': pubkey,
                                'Index': idx,
                                'Issue': 'Slashing Event',
                                'Details': f"{stats['slashings']} slashing(s)",
                                'Threshold': 'Any occurrence'
                            })
                    
                    # Check for very low effectiveness (< 90%)
                    for idx, stats in rated_validator_stats.items():
                        if stats['avg_effectiveness'] < 90:
                            pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                            critical_data.append({
                                'Validator': pubkey,
                                'Index': idx,
                                'Issue': 'Low Effectiveness',
                                'Details': f"{stats['avg_effectiveness']:.1f}%",
                                'Threshold': '<90%'
                            })
                    
                    report.append("### 🚨 Critical Issues\n")
                    if critical_data:
                        report.append("| Validator | Index | Issue | Details | Threshold |")
                        report.append("|-----------|-------|-------|---------|-----------|")
                        for item in critical_data:
                            report.append(f"| {item['Validator']} | {item['Index']} | {item['Issue']} | {item['Details']} | {item['Threshold']} |")
                        report.append("\n**Thresholds**: Slashings = Any occurrence | Effectiveness < 90%")
                    else:
                        report.append("No critical issues found")
                    report.append("")
                    
                    # Performance Concerns
                    concerns_data = []
                    
                    # Check for high missed attestations (> 1% of total attestations)
                    # Ethereum has ~225 attestation duties per day (32 slots per epoch * 225 epochs per day / 32 slots per attestation)
                    ATTESTATIONS_PER_DAY = 225
                    for idx, stats in bc_validator_stats.items():
                        total_attestation_duties = stats['days'] * ATTESTATIONS_PER_DAY
                        miss_rate = (stats['missed_attestations'] / total_attestation_duties * 100) if total_attestation_duties > 0 else 0
                        if miss_rate > 1:
                            pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                            concerns_data.append({
                                'Validator': pubkey,
                                'Index': idx,
                                'Concern': 'High Attestation Miss Rate',
                                'Value': f"{miss_rate:.1f}%",
                                'Threshold': '>1%'
                            })
                    
                    # Check for low uptime (< 99%)
                    for idx, stats in rated_validator_stats.items():
                        if stats['avg_uptime'] < 0.99:
                            pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                            concerns_data.append({
                                'Validator': pubkey,
                                'Index': idx,
                                'Concern': 'Low Uptime',
                                'Value': f"{stats['avg_uptime']*100:.1f}%",
                                'Threshold': '<99%'
                            })
                    
                    report.append("### ⚠️ Performance Concerns\n")
                    if concerns_data:
                        report.append("| Validator | Index | Concern | Value | Threshold |")
                        report.append("|-----------|-------|---------|-------|-----------|")
                        for item in concerns_data:
                            report.append(f"| {item['Validator']} | {item['Index']} | {item['Concern']} | {item['Value']} | {item['Threshold']} |")
                        report.append("\n**Thresholds**: Attestation miss rate >1% of total attestations | Uptime <99%")
                    else:
                        report.append("No major performance concerns")
                    report.append("")
                    
                    # Aggregated Performance Metrics
                    report.append("## Aggregated Performance Metrics\n")
                    
                    # Calculate aggregated metrics similar to the dashboard display
                    # BeaconChain totals
                    bc_total_missed_blocks = sum(stats.get('missed_blocks', 0) for stats in bc_validator_stats.values()) if bc_validator_stats else 0
                    bc_total_missed_attestations = sum(stats.get('missed_attestations', 0) for stats in bc_validator_stats.values()) if bc_validator_stats else 0
                    bc_total_missed_sync = sum(stats.get('missed_sync', 0) for stats in bc_validator_stats.values()) if bc_validator_stats else 0
                    bc_total_slashings = sum(stats.get('slashings', 0) for stats in bc_validator_stats.values()) if bc_validator_stats else 0
                    bc_total_proposed = sum(stats.get('proposed_blocks', 0) for stats in bc_validator_stats.values()) if bc_validator_stats else 0
                    
                    if has_beaconchain:
                        report.append("### beaconcha.in Data\n")
                        report.append(f"- **Proposed Blocks**: {bc_total_proposed:,}")
                        report.append(f"- **Missed Blocks**: {bc_total_missed_blocks:,}")
                        report.append(f"- **Missed Attestations**: {bc_total_missed_attestations:,}")
                        report.append(f"- **Missed Sync**: {bc_total_missed_sync:,}")
                        report.append(f"- **Total Slashings**: {bc_total_slashings:,}")
                        report.append("")
                    
                    # Rated Summary
                    if has_rated and 'validators_data' in locals():
                        # Calculate overall averages
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
                            report.append("### rated.network Effectiveness\n")
                            report.append(f"- **Avg Validator Effectiveness**: {sum(all_effectiveness)/len(all_effectiveness):.2f}%")
                            report.append(f"- **Avg Uptime**: {sum(all_uptime)/len(all_uptime)*100:.2f}%")
                            report.append(f"- **Avg Correctness**: {sum(all_correctness)/len(all_correctness)*100:.2f}%")
                            report.append(f"- **Avg Inclusion Delay**: {sum(all_inclusion_delay)/len(all_inclusion_delay):.2f}")
                            report.append("")
                        
                        # Attestations Summary
                        if 'all_attestation_results' in locals() and all_attestation_results:
                            report.append("### Attestation Performance\n")
                            total_attest_days = len(all_attestation_results)
                            avg_att_eff = sum(r.get("attesterEffectiveness", 0) for r in all_attestation_results) / total_attest_days if total_attest_days > 0 else 0
                            total_att_missed = sum(r.get("sumMissedAttestations", 0) for r in all_attestation_results)
                            total_att_wrong_head = sum(r.get("sumWrongHeadVotes", 0) for r in all_attestation_results)
                            total_att_wrong_target = sum(r.get("sumWrongTargetVotes", 0) for r in all_attestation_results)
                            total_att_late_head = sum(r.get("sumLateHeadVotes", 0) for r in all_attestation_results)
                            
                            report.append(f"- **Avg Attester Effectiveness**: {avg_att_eff:.2f}%")
                            report.append(f"- **Total Missed**: {total_att_missed:,}")
                            report.append(f"- **Wrong Head Votes**: {total_att_wrong_head:,}")
                            report.append(f"- **Wrong Target Votes**: {total_att_wrong_target:,}")
                            report.append(f"- **Late Head Votes**: {total_att_late_head:,}")
                            report.append("")
                        
                        # Proposals Summary
                        if 'all_proposal_results' in locals() and all_proposal_results:
                            report.append("### Block Proposal Performance\n")
                            total_prop_duties = sum(r.get("proposerDutiesCount", 0) for r in all_proposal_results)
                            total_prop_proposed = sum(r.get("proposedCount", 0) for r in all_proposal_results)
                            total_prop_empty = sum(r.get("executionProposedEmptyCount", 0) for r in all_proposal_results)
                            prop_effectiveness = (total_prop_proposed / total_prop_duties * 100) if total_prop_duties > 0 else 0
                            prop_empty_rate = (total_prop_empty / total_prop_proposed * 100) if total_prop_proposed > 0 else 0
                            
                            report.append(f"- **Total Duties**: {total_prop_duties:,}")
                            report.append(f"- **Blocks Proposed**: {total_prop_proposed:,}")
                            report.append(f"- **Effectiveness**: {prop_effectiveness:.1f}%")
                            report.append(f"- **Empty Blocks**: {total_prop_empty:,}")
                            if total_prop_proposed > 0:
                                report.append(f"- **Empty Rate**: {prop_empty_rate:.1f}%")
                            report.append(f"- **Missed Proposals**: {total_prop_duties - total_prop_proposed:,}")
                            report.append("")
                    
                    # Detailed Analysis
                    report.append("## Detailed Analysis\n")
                    
                    # Per-Validator Summary - MEGA TABLE
                    report.append("### Per-Validator Performance\n")
                    report.append("| Validator Pubkey | Index | Val Eff % | Att Eff % | Prop Eff % | Uptime % | Correctness % | Incl Delay | Missed Att | Missed Blocks | Missed Sync | Proposed | Slashings | Days |")
                    report.append("|------------------|-------|-----------|-----------|------------|----------|---------------|------------|------------|---------------|-------------|----------|-----------|------|")
                    
                    # Get comprehensive data for each validator
                    all_validator_indices = set(list(bc_validator_stats.keys()) + list(rated_validator_stats.keys()))
                    
                    # Also check for attestation and proposal data
                    if 'attestation_validators_data' in locals():
                        all_validator_indices.update(attestation_validators_data.keys())
                    if 'proposal_validators_data' in locals():
                        all_validator_indices.update(proposal_validators_data.keys())
                    
                    for idx in sorted(all_validator_indices):
                        pubkey = index_to_pubkey.get(idx, f"Unknown-{idx}")
                        
                        # Get stats from all sources
                        bc_stats = bc_validator_stats.get(idx, {})
                        rated_stats = rated_validator_stats.get(idx, {})
                        
                        # Get attestation aggregates if available
                        att_effectiveness = "N/A"
                        if 'attestation_validators_data' in locals() and idx in attestation_validators_data:
                            att_records = attestation_validators_data[idx]
                            if att_records:
                                avg_att_eff = sum(r.get('attesterEffectiveness', 0) for r in att_records) / len(att_records)
                                att_effectiveness = f"{avg_att_eff:.1f}"
                        
                        # Get proposal effectiveness if available
                        prop_effectiveness = "N/A"
                        if 'proposal_validators_data' in locals() and idx in proposal_validators_data:
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
                        
                        report.append(f"| {pubkey} | {idx} | {val_effectiveness} | {att_effectiveness} | {prop_effectiveness} | {uptime} | {correctness} | {incl_delay} | {missed_att} | {missed_blocks} | {missed_sync} | {proposed} | {slashings} | {days} |")
                    
                    report.append("")
                    
                    
                    report.append("\n---\n")
                    report.append("*This report was generated by the Xatu Analysis Validator Performance Dashboard*")
                    
                    return "\n".join(report)
                
                # Generate and offer download
                markdown_report = generate_markdown_report()
                
                # Add some spacing before the download button
                st.markdown("")
                st.download_button(
                    label="📄 Download Markdown Report",
                    data=markdown_report,
                    file_name=f"validator_performance_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.md",
                    mime="text/markdown",
                    help="Download a comprehensive markdown report of all findings",
                    key="download_markdown_report"
                )


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