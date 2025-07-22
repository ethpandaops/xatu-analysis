"""Interactive dashboard for validator performance analysis."""
import streamlit as st
from typing import List, Dict, Any, Optional, Tuple
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
from pages.analysis.validator_performance.time_utils import get_time_range_from_selection
from pages.analysis.validator_performance.beaconchain_integration import (
    fetch_beaconchain_stats,
    render_beaconchain_section
)
from pages.analysis.validator_performance.rated_integration import (
    render_rated_effectiveness_section,
    render_rated_attestations_section,
    render_rated_proposals_section
)
from pages.analysis.validator_performance.performance_summary import render_performance_summary
from pages.analysis.validator_performance.report_generator import generate_markdown_report


def split_date_ranges_with_exclusions(
    start_date: datetime, 
    end_date: datetime, 
    excluded_ranges: List[Dict[str, Any]]
) -> List[Tuple[datetime, datetime]]:
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
                        
                        # Get excluded ranges for filtering
                        excluded_ranges = st.session_state.get('validator_performance_excluded_ranges', [])
                        
                        # Fetch stats using the new function
                        results = fetch_beaconchain_stats(
                            client,
                            pubkey_to_index,
                            time_range,
                            excluded_ranges,
                            max_validators=50
                        )
                        
                        # Store results in session state
                        st.session_state['validator_performance_api_test_results'] = results
                        
                        # Close the client
                        client.close()
                        
                    except Exception as e:
                        st.session_state['validator_performance_api_test_results'] = {
                            'all_indices': list(pubkey_to_index.values()),
                            'max_validators': 0,
                            'stats_data': [],
                            'start_date': None,
                            'end_date': None,
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
            
            # Render BeaconChain section using the new function
            render_beaconchain_section(test_results, pubkey_to_index)
        
        # Test Rated API (only available for mainnet)
        current_network = st.session_state.get('validator_performance_network', 'mainnet')
        if st.session_state.get('validator_performance_data_loaded') and pubkey_to_index and current_network == 'mainnet':
            # Get configuration for passing to render functions
            time_range_config = st.session_state.get('validator_performance_time_range', {})
            excluded_ranges = st.session_state.get('validator_performance_excluded_ranges', [])
            
            # Render Rated Effectiveness section
            all_results = render_rated_effectiveness_section(
                pubkey_to_index,
                time_range_config,
                excluded_ranges
            )
        
            # Render Rated Attestations section
            all_attestation_results = render_rated_attestations_section(
                pubkey_to_index,
                time_range_config,
                excluded_ranges
            )
        
            # Render Rated Proposals section
            all_proposal_results = render_rated_proposals_section(
                pubkey_to_index,
                time_range_config,
                excluded_ranges
            )
        
        # Combined Analysis Summary
        if st.session_state.get('validator_performance_data_loaded') and pubkey_to_index:
            beaconchain_results = st.session_state.get('validator_performance_api_test_results')
            
            # Prepare effectiveness data from all_results if available
            effectiveness_data = None
            if 'all_results' in locals() and all_results:
                # Group effectiveness data by validator
                effectiveness_data = {}
                for result in all_results:
                    vid = result.get("validatorIndex", 0)
                    if vid not in effectiveness_data:
                        effectiveness_data[vid] = []
                    effectiveness_data[vid].append(result)
            
            # Prepare attestation data if available
            attestation_data = None
            if 'all_attestation_results' in locals() and all_attestation_results:
                # Use the raw attestation results directly
                attestation_data = all_attestation_results
            
            # Prepare proposal data if available
            proposal_data = None
            if 'all_proposal_results' in locals() and all_proposal_results:
                # Use the raw proposal results directly
                proposal_data = all_proposal_results
            
            # Check if we have data from any source
            has_beaconchain = beaconchain_results and beaconchain_results.get('stats_data', [])
            has_rated = effectiveness_data or attestation_data or proposal_data
            
            if has_beaconchain or has_rated:
                st.divider()
                
                # Render the performance summary using the new function
                render_performance_summary(
                    pubkey_to_index=pubkey_to_index,
                    beaconchain_results=beaconchain_results,
                    effectiveness_data=effectiveness_data,
                    attestation_data=attestation_data,
                    proposal_data=proposal_data
                )
                
                # Generate and offer download of markdown report
                markdown_report = generate_markdown_report(
                    current_network=current_network,
                    pubkey_to_index=pubkey_to_index,
                    time_range_config=st.session_state.get('validator_performance_time_range', {}),
                    excluded_ranges=st.session_state.get('validator_performance_excluded_ranges', []),
                    beaconchain_results=beaconchain_results,
                    effectiveness_data=effectiveness_data,
                    attestation_data=attestation_data,
                    proposal_data=proposal_data
                )
                
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