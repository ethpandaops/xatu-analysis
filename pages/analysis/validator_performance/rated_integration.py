"""
Rated.network API integration for validator performance analysis.

This module handles all interactions with the Rated API including:
- Effectiveness data fetching
- Attestations data fetching  
- Proposals data fetching
- Rate limiting and retry logic
- Date validation and filtering
- UI rendering with streamlit
"""

import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any

import httpx
import pandas as pd
import streamlit as st

from .time_utils import get_time_range_from_selection


def fetch_rated_effectiveness(
    indices: List[int], 
    time_range: Tuple[datetime, datetime],
    excluded_ranges: List[Dict[str, Any]]
) -> Tuple[List[Dict], int, int]:
    """
    Fetch effectiveness data from Rated API for given validator indices.
    
    Args:
        indices: List of validator indices to fetch data for
        time_range: Tuple of (start_date, end_date) for the query
        excluded_ranges: List of date ranges to exclude from results
        
    Returns:
        Tuple of (results_list, unfiltered_count, successful_validators)
    """
    # Check if API key is set
    api_key = os.getenv('RATED_API_KEY')
    if not api_key:
        raise ValueError("RATED_API_KEY environment variable not set")
    
    start_date, end_date = time_range
    
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
    
    # API configuration
    url = "https://api.rated.network/v1/eth/validators/effectiveness"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    # Build base params for individual validator requests
    base_params = {
        "limit": 1000,
        "sortOrder": "asc",
        "granularity": "day",
        "groupBy": "granularity",
        "fromDate": from_date.strftime('%Y-%m-%d'),
        "toDate": to_date.strftime('%Y-%m-%d')
    }
    
    # Collect all results
    all_results = []
    unfiltered_count = 0
    successful_validators = 0
    
    # Rate limiting configuration (2 requests per second)
    last_request_time = 0
    min_interval = 0.5  # 500ms between requests
    
    # Make individual requests per validator
    with httpx.Client() as client:
        for i, idx in enumerate(indices):
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
                        # Add validator index to each result
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
    
    return all_results, unfiltered_count, successful_validators


def fetch_rated_attestations(
    indices: List[int],
    time_range: Tuple[datetime, datetime],
    excluded_ranges: List[Dict[str, Any]]
) -> Tuple[List[Dict], int, int]:
    """
    Fetch attestation data from Rated API for given validator indices.
    
    Args:
        indices: List of validator indices to fetch data for
        time_range: Tuple of (start_date, end_date) for the query
        excluded_ranges: List of date ranges to exclude from results
        
    Returns:
        Tuple of (results_list, unfiltered_count, successful_validators)
    """
    # Check if API key is set
    api_key = os.getenv('RATED_API_KEY')
    if not api_key:
        raise ValueError("RATED_API_KEY environment variable not set")
    
    start_date, end_date = time_range
    
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
    
    # API configuration
    url = "https://api.rated.network/v1/eth/validators"
    headers = {"Authorization": f"Bearer {api_key}"}
    
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
    
    # Rate limiting configuration (2 requests per second)
    last_request_time = 0
    min_interval = 0.5  # 500ms between requests
    
    # Make individual requests per validator
    with httpx.Client() as client:
        for i, idx in enumerate(indices):
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
    
    return all_attestation_results, unfiltered_count, successful_validators


def fetch_rated_proposals(
    indices: List[int],
    time_range: Tuple[datetime, datetime],
    excluded_ranges: List[Dict[str, Any]]
) -> Tuple[List[Dict], int, int]:
    """
    Fetch proposal data from Rated API for given validator indices.
    
    Args:
        indices: List of validator indices to fetch data for
        time_range: Tuple of (start_date, end_date) for the query
        excluded_ranges: List of date ranges to exclude from results
        
    Returns:
        Tuple of (results_list, unfiltered_count, successful_validators)
    """
    # Check if API key is set
    api_key = os.getenv('RATED_API_KEY')
    if not api_key:
        raise ValueError("RATED_API_KEY environment variable not set")
    
    start_date, end_date = time_range
    
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
    
    # API configuration
    url = "https://api.rated.network/v1/eth/validators"
    headers = {"Authorization": f"Bearer {api_key}"}
    
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
    
    # Rate limiting configuration (2 requests per second)
    last_request_time = 0
    min_interval = 0.5  # 500ms between requests
    
    # Make individual requests per validator
    with httpx.Client() as client:
        for i, idx in enumerate(indices):
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
    
    return all_proposal_results, unfiltered_count, successful_validators


def render_rated_effectiveness_section(
    pubkey_to_index: Dict[str, int],
    time_range_config: Dict[str, Any],
    excluded_ranges: List[Dict[str, Any]]
) -> Optional[List[Dict]]:
    """
    Render the Rated effectiveness section in the Streamlit UI.
    
    Args:
        pubkey_to_index: Mapping of validator pubkeys to indices
        time_range_config: Time range configuration from session state
        excluded_ranges: List of date ranges to exclude
        
    Returns:
        List of all effectiveness results if successful, None otherwise
    """
    with st.expander("rated.network - Effectiveness", expanded=True):
        with st.spinner("Loading data from Rated..."):
            try:
                # Check if API key is set
                if not os.getenv('RATED_API_KEY'):
                    st.error("RATED_API_KEY environment variable not set. Please set it to use Rated API.")
                    st.info("Get your API key from https://www.rated.network/")
                    return None
                
                # Get list of all validator indices
                limited_indices = list(pubkey_to_index.values())
                
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
                
                # Fetch effectiveness data
                all_results, unfiltered_count, successful_validators = fetch_rated_effectiveness(
                    limited_indices, (start_date, end_date), excluded_ranges
                )
                
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
                    
                    # Store results in session state for later use
                    st.session_state['rated_effectiveness_data'] = {
                        'all_results': all_results,
                        'validators_data': validators_data
                    }
                    
                    return all_results
                else:
                    st.warning("No effectiveness data returned from API")
                    return None
                    
            except Exception as e:
                st.error(f"Error in Rated API test: {type(e).__name__}: {str(e)}")
                return None


def render_rated_attestations_section(
    pubkey_to_index: Dict[str, int],
    time_range_config: Dict[str, Any],
    excluded_ranges: List[Dict[str, Any]]
) -> Optional[List[Dict]]:
    """
    Render the Rated attestations section in the Streamlit UI.
    
    Args:
        pubkey_to_index: Mapping of validator pubkeys to indices
        time_range_config: Time range configuration from session state
        excluded_ranges: List of date ranges to exclude
        
    Returns:
        List of all attestation results if successful, None otherwise
    """
    with st.expander("rated.network - Attestations", expanded=True):
        with st.spinner("Loading attestation data from Rated..."):
            try:
                # Check if API key is set
                if not os.getenv('RATED_API_KEY'):
                    st.error("RATED_API_KEY environment variable not set. Please set it to use Rated API.")
                    st.info("Get your API key from https://www.rated.network/")
                    return None
                
                # Get list of all validator indices
                limited_indices = list(pubkey_to_index.values())
                
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
                
                # Fetch attestation data
                all_attestation_results, unfiltered_count, successful_validators = fetch_rated_attestations(
                    limited_indices, (start_date, end_date), excluded_ranges
                )
                
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
                    
                    # Store results in session state for later use
                    st.session_state['rated_attestation_data'] = {
                        'all_attestation_results': all_attestation_results,
                        'attestation_validators_data': attestation_validators_data
                    }
                    
                    return all_attestation_results
                else:
                    st.warning("No attestation data returned from API")
                    return None
                    
            except Exception as e:
                st.error(f"Error in Rated Attestations API: {type(e).__name__}: {str(e)}")
                return None


def render_rated_proposals_section(
    pubkey_to_index: Dict[str, int],
    time_range_config: Dict[str, Any],
    excluded_ranges: List[Dict[str, Any]]
) -> Optional[List[Dict]]:
    """
    Render the Rated proposals section in the Streamlit UI.
    
    Args:
        pubkey_to_index: Mapping of validator pubkeys to indices
        time_range_config: Time range configuration from session state
        excluded_ranges: List of date ranges to exclude
        
    Returns:
        List of all proposal results if successful, None otherwise
    """
    with st.expander("rated.network - Proposals", expanded=True):
        with st.spinner("Loading proposal data from Rated..."):
            try:
                # Check if API key is set
                if not os.getenv('RATED_API_KEY'):
                    st.error("RATED_API_KEY environment variable not set. Please set it to use Rated API.")
                    st.info("Get your API key from https://www.rated.network/")
                    return None
                
                # Get list of all validator indices
                limited_indices = list(pubkey_to_index.values())
                
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
                
                # Fetch proposal data
                all_proposal_results, unfiltered_count, successful_validators = fetch_rated_proposals(
                    limited_indices, (start_date, end_date), excluded_ranges
                )
                
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
                    
                    # Store results in session state for later use
                    st.session_state['rated_proposal_data'] = {
                        'all_proposal_results': all_proposal_results,
                        'proposal_validators_data': proposal_validators_data
                    }
                    
                    return all_proposal_results
                else:
                    st.warning("No proposal data returned from API")
                    return None
                    
            except Exception as e:
                st.error(f"Error in Rated Proposals API: {type(e).__name__}: {str(e)}")
                return None