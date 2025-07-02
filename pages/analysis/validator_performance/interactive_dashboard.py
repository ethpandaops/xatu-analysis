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
                with st.expander(f"⚠️ {len(errors)} issue(s)", expanded=False):
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
        
        # Network selection
        networks = get_supported_networks()
        network = st.selectbox(
            "Network",
            options=networks,
            index=networks.index(st.session_state['validator_performance_network']),
            help="Select the Ethereum network to analyze"
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
            "🔄 Load Data",
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
    st.title("📊 Validator Performance")
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
        st.subheader("Selected Validators")
        
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
                    st.text(f"{i+1}. ✅ {pubkey} (index: {pubkey_to_index[pubkey]})")
                elif pubkey in excluded_pubkeys:
                    st.text(f"{i+1}. ❌ {pubkey} (not found)")
                else:
                    st.text(f"{i+1}. {pubkey}")
                
                if i >= 99:  # Show max 100 validators
                    st.text(f"... and {len(config['validator_pubkeys']) - 100} more")
                    break
    
    # Data loading section
    st.divider()
    
    if not config['validator_pubkeys']:
        st.info("👈 Select validators in the sidebar to begin analysis")
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
                st.warning(f"⚠️ {len(missing_pubkeys)} validator(s) not found in database and will be excluded")
            
            # Store results in session state
            store_validator_mappings(pubkey_to_index, missing_pubkeys)
            
            # Display success/error message
            if pubkey_to_index:
                st.success(f"✅ Successfully loaded {len(pubkey_to_index)} validator(s)")
                
                # Test BeaconchainClient.get_validator_performance
                with st.spinner("Testing Beaconcha.in API..."):
                    try:
                        # Create client
                        client = BeaconchainClient()
                        
                        # Get list of validator indices (max 10 for testing)
                        test_indices = list(pubkey_to_index.values())[:10]
                        
                        # Call get_validator_performance
                        performance_data = client.get_validator_performance(test_indices)
                        
                        # Store results in session state
                        st.session_state['validator_performance_api_test_results'] = {
                            'test_indices': test_indices,
                            'performance_data': [
                                {
                                    "validatorindex": perf.validatorindex,
                                    "balance": perf.balance,
                                    "performance1d": perf.performance1d,
                                    "performance7d": perf.performance7d,
                                    "performance31d": perf.performance31d,
                                    "performance365d": perf.performance365d,
                                    "rank7d": perf.rank7d
                                } for perf in performance_data
                            ],
                            'error': None
                        }
                        
                        # Close the client
                        client.close()
                        
                    except Exception as e:
                        st.session_state['validator_performance_api_test_results'] = {
                            'test_indices': test_indices,
                            'performance_data': [],
                            'error': str(e)
                        }
                
                # Mark data as loaded
                st.session_state['validator_performance_data_loaded'] = True
                st.session_state['validator_performance_loading_initiated'] = False
                st.rerun()
            else:
                st.error("❌ No valid validators found. Please check your validator pubkeys.")
                st.session_state['validator_performance_loading_initiated'] = False
        else:
            st.info("🔄 Click 'Load Data' in the sidebar to fetch validator performance data")
    else:
        # Data has been loaded - show summary
        pubkey_to_index = get_valid_validators()
        excluded_pubkeys = get_excluded_validators()
        
        st.success(f"✅ {len(pubkey_to_index)} validator(s) found, {len(excluded_pubkeys)} excluded")
        
        # Display API test results if available
        if st.session_state.get('validator_performance_api_test_results'):
            test_results = st.session_state['validator_performance_api_test_results']
            
            with st.expander("🧪 Beaconcha.in API Test Results", expanded=True):
                if test_results.get('error'):
                    st.error(f"❌ Error testing Beaconcha.in API: {test_results['error']}")
                else:
                    st.write(f"**Requested indices:** {test_results['test_indices']}")
                    st.write(f"**Response count:** {len(test_results['performance_data'])}")
                    
                    if test_results['performance_data']:
                        st.write("**Sample performance data:**")
                        for i, perf in enumerate(test_results['performance_data'][:3]):  # Show max 3
                            st.write(f"\n**Validator {perf['validatorindex']}:**")
                            st.json(perf)
                        
                        if len(test_results['performance_data']) > 3:
                            st.write(f"... and {len(test_results['performance_data']) - 3} more validators")
                    else:
                        st.warning("No performance data returned from API")


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