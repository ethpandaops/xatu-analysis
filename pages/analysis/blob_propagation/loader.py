"""
Data loader for Blob Propagation Analysis.

This module loads blob propagation data by analyzing how blob sidecar events
propagate from proposer groups to attester groups across the Ethereum network.
"""

import pandas as pd
import polars as pl
import streamlit as st
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import logging
import yaml
import os
import textwrap

from shared.database import get_database_connection
from shared.network_spec import get_network_spec

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _format_in_clause(values: Optional[List[str]]) -> str:
    """Return SQL IN clause string for a list of string values."""
    if not values:
        return ""
    safe = ",".join(f"'{value}'" for value in values)
    return f" IN ({safe})"


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_network_mapping(network: str) -> Dict[str, Any]:
    """
    Load network mapping from YAML files.
    
    Args:
        network: Network name
        
    Returns:
        Dictionary with node configurations
    """
    network_file = f"networks/{network}.yaml"
    if not os.path.exists(network_file):
        logger.warning(f"Network file {network_file} not found")
        return {}
    
    try:
        with open(network_file, 'r') as f:
            data = yaml.safe_load(f)
            return data.get('nodes', {})
    except Exception as e:
        logger.error(f"Error loading network mapping: {e}")
        return {}


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_mev_slots(
    network: str,
    start_date: datetime,
    end_date: datetime,
    cluster_name: Optional[str] = None
) -> List[int]:
    """
    Load slots that were delivered via MEV relay using int_block_mev_head table.

    Returns:
        List of slot numbers that had MEV payloads
    """
    logger.info(f"Loading MEV slots for network={network}")

    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return []

    sql = f"""
        SELECT DISTINCT slot
        FROM `{network}`.int_block_mev_head
        WHERE slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
          AND slot > 0
        ORDER BY slot
    """.replace('{network}', network)

    params = {
        'start_date': start_date,
        'end_date': end_date
    }

    try:
        df = pd.read_sql(sql, conn, params=params)
        if df.empty:
            logger.info(f"No MEV slots found for network {network}")
            return []

        mev_slots = df['slot'].tolist()
        logger.info(f"Found {len(mev_slots)} MEV slots for {network} between {start_date} and {end_date}")
        return mev_slots
    except Exception as e:
        logger.warning(f"Error loading MEV slots (may not be available for this network): {e}")
        return []


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_eligible_slots_for_blob_analysis(
    network: str,
    start_date: datetime,
    end_date: datetime,
    proposer_filters: Optional[Dict[str, Any]] = None,
    mev_filter: Optional[str] = None,
    cluster_name: Optional[str] = None
) -> Tuple[List[int], Dict[int, str], Dict[int, int], List[int]]:
    """Load proposer-filtered slots using dim_node metadata for blob analysis."""

    logger.info(f"Loading eligible slots for blob analysis: network={network}")

    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error("Failed to get database connection for cluster: %s", cluster_name)
        return [], {}, {}, []

    # Build proposer filters from the proposer_filters dict
    proposer_filters_sql = ""
    if proposer_filters:
        if proposer_filters.get('proposer_type'):
            proposer_filters_sql += f"\n      AND coalesce(vm.node_type, 'unknown') = '{proposer_filters['proposer_type']}'"
        if proposer_filters.get('proposer_cl'):
            proposer_filters_sql += f"\n      AND coalesce(vm.cl_client, 'unknown'){_format_in_clause(proposer_filters['proposer_cl'])}"
        if proposer_filters.get('proposer_el'):
            proposer_filters_sql += f"\n      AND coalesce(vm.el_client, 'unknown'){_format_in_clause(proposer_filters['proposer_el'])}"
        if proposer_filters.get('proposer_architecture'):
            proposer_filters_sql += f"\n      AND coalesce(vm.architecture, 'unknown'){_format_in_clause(proposer_filters['proposer_architecture'])}"
        if proposer_filters.get('proposer_operator'):
            proposer_filters_sql += f"\n      AND coalesce(vm.operator, 'unknown'){_format_in_clause(proposer_filters['proposer_operator'])}"
        if proposer_filters.get('proposer_region'):
            proposer_filters_sql += f"\n      AND coalesce(vm.region, 'unknown'){_format_in_clause(proposer_filters['proposer_region'])}"
        if proposer_filters.get('proposer_datacenter'):
            proposer_filters_sql += f"\n      AND coalesce(vm.datacenter, 'unknown'){_format_in_clause(proposer_filters['proposer_datacenter'])}"

    mev_filter_sql = _build_mev_filter_clause(mev_filter, alias='ps')

    proposer_subquery = textwrap.indent(_build_proposer_subquery(network, proposer_filters_sql), '  ')

    sql = f"""
SELECT
  ps.slot AS slot,
  ps.block_root AS block_root,
  ps.proposer_validator_index,
  ps.mev_status
FROM (
{proposer_subquery}
) ps
WHERE 1 = 1{mev_filter_sql}
ORDER BY slot
"""

    params = {'start_date': start_date, 'end_date': end_date}

    try:
        df = pd.read_sql(sql, conn, params=params)
    except Exception as exc:
        error_msg = f"Error loading eligible slots: {exc}"
        logger.error(error_msg, exc_info=True)
        raise Exception(error_msg) from exc

    if df.empty:
        logger.warning('Eligible slot query returned no rows for the supplied filters')
        return [], {}, {}, []

    slots = df['slot'].tolist()
    slot_to_block = dict(zip(df['slot'], df['block_root']))
    slot_to_proposer = dict(zip(df['slot'], df['proposer_validator_index']))
    mev_slots = df.loc[df['mev_status'] == 'mev', 'slot'].tolist()

    logger.info('Eligible slot load complete: %d slots (%d MEV)', len(slots), len(mev_slots))
    return slots, slot_to_block, slot_to_proposer, mev_slots


def _build_validator_metadata_subquery(network: str) -> str:
    return f"""
SELECT
  validator_index,
  coalesce(arrayElement(splitByChar(':', arrayFilter(x -> startsWith(x, 'cl:'), tags)[1]), 2), 'unknown') AS cl_client,
  coalesce(arrayElement(splitByChar(':', arrayFilter(x -> startsWith(x, 'el:'), tags)[1]), 2), 'unknown') AS el_client,
  IF(attributes['isClSupernode'] = 'true', 'supernode', 'regular') AS node_type,
  IF(arrayExists(x -> x = 'arch:arm', tags) OR lower(name) LIKE '%%arm%%', 'ARM', 'x86') AS architecture,
  coalesce(source, 'unknown') AS operator,
  coalesce(attributes['cloudRegion'], 'unknown') AS region,
  coalesce(attributes['cloud'], 'unknown') AS datacenter
FROM `{network}`.dim_node FINAL
""".replace('{network}', network).strip()


def _build_proposer_subquery(network: str, proposer_filter_sql: str) -> str:
    metadata_subquery = textwrap.indent(_build_validator_metadata_subquery(network), '  ')

    return f"""
SELECT
  base.slot AS slot,
  base.block_root AS block_root,
  base.proposer_validator_index AS proposer_validator_index,
  if(ms.slot > 0, 'mev', 'non-mev') AS mev_status,
  vm.cl_client      AS proposer_cl_client,
  vm.el_client      AS proposer_el_client,
  vm.node_type      AS proposer_node_type,
  vm.architecture   AS proposer_architecture,
  vm.operator       AS proposer_operator,
  vm.region         AS proposer_region,
  vm.datacenter     AS proposer_datacenter
FROM (
  SELECT slot, block_root, proposer_validator_index, slot_start_date_time
  FROM `{network}`.int_block_proposer_head FINAL
  WHERE slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
) AS base
LEFT JOIN (
  SELECT DISTINCT slot
  FROM `{network}`.int_block_mev_head
  WHERE slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
) ms ON base.slot = ms.slot
LEFT JOIN (
{metadata_subquery}
) vm ON base.proposer_validator_index = vm.validator_index
WHERE 1 = 1{proposer_filter_sql}
""".replace('{network}', network).strip()


def _build_mev_filter_clause(mev_filter: Optional[str], alias: str = 'ps') -> str:
    """Build MEV filter clause based on mev_filter parameter."""
    if mev_filter == 'mev_only':
        return f"\n  AND {alias}.mev_status = 'mev'"
    elif mev_filter == 'non_mev_only':
        return f"\n  AND {alias}.mev_status = 'non-mev'"
    else:
        return ""


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_blob_propagation_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    eligible_slots: List[int],
    data_source: str = "beacon_api",
    proposer_group_by: str = "node_type",
    attester_group_by: str = "node_type",
    max_propagation_ms: int = 12000,
    proposer_filters: Optional[Dict[str, Any]] = None,
    attester_filters: Optional[Dict[str, Any]] = None,
    cluster_name: Optional[str] = None
) -> pd.DataFrame:
    """
    Load blob propagation data showing how blob sidecar events propagate
    from proposer groups to attester groups.
    """
    
    logger.info(f"Loading blob propagation data: network={network}, slots={len(eligible_slots)}")

    if not eligible_slots:
        logger.warning("No eligible slots provided to load_blob_propagation_data")
        return pd.DataFrame()

    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error("Failed to obtain ClickHouse connection (cluster=%s)", cluster_name)
        return pd.DataFrame()

    # Build the main query for blob propagation data
    sql = _build_blob_propagation_query(
        network=network,
        data_source=data_source,
        proposer_group_by=proposer_group_by,
        attester_group_by=attester_group_by,
        max_propagation_ms=max_propagation_ms
    )

    params = {
        'network': network,
        'start_date': start_date,
        'end_date': end_date,
        'eligible_slots': eligible_slots,
        'max_propagation_ms': max_propagation_ms
    }

    try:
        df = pd.read_sql(sql, conn, params=params)
        
        if df.empty:
            logger.warning("Blob propagation query returned no data")
            return pd.DataFrame()
        
        logger.info(f"Successfully loaded {len(df)} blob propagation records")
        return df
        
    except Exception as e:
        logger.error(f"Error loading blob propagation data: {e}")
        return pd.DataFrame()


def _build_blob_propagation_query(
    network: str,
    data_source: str = "beacon_api",
    proposer_group_by: str = "node_type",
    attester_group_by: str = "node_type",
    max_propagation_ms: int = 12000
) -> str:
    """Build the main SQL query for blob propagation analysis."""
    
    # Choose table based on data source
    if data_source == 'libp2p':
        blob_sidecar_table = f'`{network}`.libp2p_gossipsub_blob_sidecar FINAL'
        client_impl_col = 'meta_client_implementation'
    else:
        blob_sidecar_table = f'`{network}`.beacon_api_eth_v1_events_blob_sidecar'
        client_impl_col = 'meta_consensus_implementation'

    # Build grouping expressions
    proposer_group_expr = _get_grouping_expression(proposer_group_by, 'proposer')
    attester_group_expr = _get_grouping_expression(attester_group_by, 'attester')

    return f"""
WITH 
-- Get eligible slots with proposer metadata
eligible_slots AS (
  SELECT 
    ps.slot,
    ps.proposer_validator_index,
    vm.cl_client as proposer_cl_client,
    vm.el_client as proposer_el_client,
    vm.node_type as proposer_node_type,
    vm.architecture as proposer_architecture,
    vm.operator as proposer_operator,
    vm.region as proposer_region,
    vm.datacenter as proposer_datacenter
  FROM (
    SELECT slot, proposer_validator_index, slot_start_date_time
    FROM `{network}`.int_block_proposer_head FINAL
    WHERE slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
      AND slot IN %(eligible_slots)s
  ) ps
  LEFT JOIN (
    SELECT
      validator_index,
      coalesce(arrayElement(splitByChar(':', arrayFilter(x -> startsWith(x, 'cl:'), tags)[1]), 2), 'unknown') AS cl_client,
      coalesce(arrayElement(splitByChar(':', arrayFilter(x -> startsWith(x, 'el:'), tags)[1]), 2), 'unknown') AS el_client,
      IF(attributes['isClSupernode'] = 'true', 'supernode', 'regular') AS node_type,
      IF(arrayExists(x -> x = 'arch:arm', tags) OR lower(name) LIKE '%%arm%%', 'ARM', 'x86') AS architecture,
      coalesce(source, 'unknown') AS operator,
      coalesce(attributes['cloudRegion'], 'unknown') AS region,
      coalesce(attributes['cloud'], 'unknown') AS datacenter
    FROM `{network}`.dim_node FINAL
  ) vm ON ps.proposer_validator_index = vm.validator_index
),

-- Get blob sidecar events with client metadata
blob_events AS (
  SELECT 
    bs.slot,
    bs.blob_index,
    bs.meta_client_name as attester_client_name,
    bs.{client_impl_col} as attester_client_impl,
    bs.propagation_slot_start_diff,
    bs.slot_start_date_time,
    bs.meta_client_geo_continent_code
  FROM {blob_sidecar_table} bs
  WHERE bs.meta_network_name = %(network)s
    AND bs.slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
    AND bs.slot IN %(eligible_slots)s
    AND bs.propagation_slot_start_diff < %(max_propagation_ms)s
    AND bs.meta_client_name != ''
)

-- Join and aggregate blob propagation data
SELECT 
  be.slot,
  {proposer_group_expr} as proposer_group,
  {attester_group_expr} as attester_group,
  be.blob_index,
  min(be.propagation_slot_start_diff) as min_propagation_ms,
  max(be.propagation_slot_start_diff) as max_propagation_ms,
  avg(be.propagation_slot_start_diff) as avg_propagation_ms,
  count(*) as event_count,
  countDistinct(be.attester_client_name) as unique_clients,
  be.slot_start_date_time
FROM blob_events be
INNER JOIN eligible_slots es ON be.slot = es.slot
GROUP BY 
  be.slot,
  proposer_group,
  attester_group,
  be.blob_index,
  be.slot_start_date_time
ORDER BY be.slot, proposer_group, attester_group, be.blob_index
""".replace('{network}', network).replace('{client_impl_col}', client_impl_col)


def _get_grouping_expression(group_by: str, prefix: str) -> str:
    """Get SQL expression for grouping dimension."""
    
    grouping_expressions = {
        'node_type': f"coalesce({prefix}_node_type, 'unknown')",
        'cl_client': f"coalesce({prefix}_cl_client, 'unknown')",
        'el_client': f"coalesce({prefix}_el_client, 'unknown')",
        'architecture': f"coalesce({prefix}_architecture, 'unknown')",
        'operator': f"coalesce({prefix}_operator, 'unknown')",
        'cl_el_combined': f"concat(coalesce({prefix}_cl_client, 'unknown'), '-', coalesce({prefix}_el_client, 'unknown'))",
        'cl_node_type': f"concat(coalesce({prefix}_cl_client, 'unknown'), '-', coalesce({prefix}_node_type, 'unknown'))",
        'cl_architecture': f"concat(coalesce({prefix}_cl_client, 'unknown'), '-', coalesce({prefix}_architecture, 'unknown'))"
    }
    
    return grouping_expressions.get(group_by, f"coalesce({prefix}_node_type, 'unknown')")


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def validate_blob_data_availability(
    network: str,
    start_date: datetime,
    end_date: datetime,
    data_source: str = "beacon_api",
    cluster_name: Optional[str] = None
) -> bool:
    """
    Validate that blob data is available for the given time range and data source.
    
    Returns:
        True if blob data is available, False otherwise
    """
    conn = get_database_connection(cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return False
    
    # Choose table based on data source
    if data_source == 'libp2p':
        table_name = f'`{network}`.libp2p_gossipsub_blob_sidecar FINAL'
    else:
        table_name = f'`{network}`.beacon_api_eth_v1_events_blob_sidecar'
    
    try:
        query = f"""
        SELECT COUNT(*) as count
        FROM {table_name}
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        LIMIT 1
        """
        result = pd.read_sql(query, conn, params={'network': network, 'start_date': start_date, 'end_date': end_date})
        has_data = result['count'].iloc[0] > 0 if not result.empty else False
        
        if has_data:
            logger.info(f"Blob data available for {network} using {data_source} data source")
        else:
            logger.warning(f"No blob data available for {network} using {data_source} data source")
            
        return has_data
        
    except Exception as e:
        logger.error(f"Failed to validate blob data availability: {e}")
        return False


def get_blob_propagation_summary_stats(data: pd.DataFrame) -> Dict[str, Any]:
    """
    Calculate summary statistics for blob propagation data.
    
    Args:
        data: DataFrame with blob propagation data
        
    Returns:
        Dictionary with summary statistics
    """
    if data.empty:
        return {
            'total_slots': 0,
            'total_proposer_groups': 0,
            'total_attester_groups': 0,
            'total_blob_events': 0,
            'avg_propagation_ms': 0,
            'min_propagation_ms': 0,
            'max_propagation_ms': 0
        }
    
    stats = {
        'total_slots': data['slot'].nunique(),
        'total_proposer_groups': data['proposer_group'].nunique() if 'proposer_group' in data.columns else 0,
        'total_attester_groups': data['attester_group'].nunique() if 'attester_group' in data.columns else 0,
        'total_blob_events': len(data),
        'avg_propagation_ms': data['avg_propagation_ms'].mean() if 'avg_propagation_ms' in data.columns else 0,
        'min_propagation_ms': data['min_propagation_ms'].min() if 'min_propagation_ms' in data.columns else 0,
        'max_propagation_ms': data['max_propagation_ms'].max() if 'max_propagation_ms' in data.columns else 0
    }
    
    return stats
