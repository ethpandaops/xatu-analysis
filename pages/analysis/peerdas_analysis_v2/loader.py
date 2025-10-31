"""
Data loader for PeerDAS Analysis V2 - Head correctness analysis.

This module loads head correctness data by analyzing whether attestations
voted for the proposed block_root (including blocks that may have been reorged),
with support for filtering by proposer and attester characteristics.
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

from shared.database import get_database_connection, get_routed_connection
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

    sql = f"""
        SELECT DISTINCT slot
        FROM `{network}`.int_block_mev_head
        WHERE slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
          AND slot > 0
        ORDER BY slot
    """.replace('{network}', network)

    conn = get_routed_connection(sql, cluster_name)
    if not conn:
        logger.error(f"Failed to get database connection for cluster: {cluster_name}")
        return []

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
        logger.info(f"MEV slot range: {min(mev_slots)} to {max(mev_slots)}")
        # Sample some slots for debugging
        if len(mev_slots) > 10:
            logger.info(f"Sample MEV slots: {mev_slots[:5]} ... {mev_slots[-5:]}")
        return mev_slots
    except Exception as e:
        logger.warning(f"Error loading MEV slots (may not be available for this network): {e}")
        return []


@st.cache_data(ttl=300, show_spinner=False, persist=False)
def load_eligible_slots(
    network: str,
    start_date: datetime,
    end_date: datetime,
    proposer_type: Optional[str] = None,
    cl_filter: Optional[List[str]] = None,
    el_filter: Optional[List[str]] = None,
    architecture_filter: Optional[List[str]] = None,
    operator_filter: Optional[List[str]] = None,
    region_filter: Optional[List[str]] = None,
    datacenter_filter: Optional[List[str]] = None,
    mev_filter: Optional[str] = None,
    cluster_name: Optional[str] = None
) -> Tuple[List[int], Dict[int, str], Dict[int, int], List[int]]:
    """Load proposer-filtered slots using dim_node metadata."""

    logger.info(
        "Loading eligible slots (dim_node) for %s | proposer_type=%s cl=%s el=%s arch=%s operator=%s region=%s datacenter=%s mev=%s",
        network,
        proposer_type,
        cl_filter,
        el_filter,
        architecture_filter,
        operator_filter,
        region_filter,
        datacenter_filter,
        mev_filter
    )

    proposer_filters_sql = ""
    if proposer_type:
        proposer_filters_sql += f"\n      AND coalesce(vm.node_type, 'unknown') = '{proposer_type}'"
    if cl_filter:
        proposer_filters_sql += f"\n      AND coalesce(vm.cl_client, 'unknown'){_format_in_clause(cl_filter)}"
    if el_filter:
        proposer_filters_sql += f"\n      AND coalesce(vm.el_client, 'unknown'){_format_in_clause(el_filter)}"
    if architecture_filter:
        proposer_filters_sql += f"\n      AND coalesce(vm.architecture, 'unknown'){_format_in_clause(architecture_filter)}"
    if operator_filter:
        proposer_filters_sql += f"\n      AND coalesce(vm.operator, 'unknown'){_format_in_clause(operator_filter)}"
    if region_filter:
        proposer_filters_sql += f"\n      AND coalesce(vm.region, 'unknown'){_format_in_clause(region_filter)}"
    if datacenter_filter:
        proposer_filters_sql += f"\n      AND coalesce(vm.datacenter, 'unknown'){_format_in_clause(datacenter_filter)}"

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

    conn = get_routed_connection(sql, cluster_name)
    if not conn:
        logger.error("Failed to get database connection for cluster: %s", cluster_name)
        return [], {}, {}, []

    params = {'start_date': start_date, 'end_date': end_date}

    try:
        df = pd.read_sql(sql, conn, params=params)
    except Exception as exc:
        error_msg = f"Error loading eligible slots: {exc}"
        logger.error(error_msg, exc_info=True)
        if hasattr(st, 'session_state'):
            st.session_state['peerdas_v2_last_error'] = error_msg
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
  FROM `{network}`.fct_block_proposer_head FINAL
  WHERE slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
) AS base
LEFT JOIN (
  SELECT DISTINCT slot
  FROM `{network}`.fct_block_mev_head
  WHERE slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
) ms ON base.slot = ms.slot
LEFT JOIN (
{metadata_subquery}
) vm ON base.proposer_validator_index = vm.validator_index
WHERE 1 = 1{proposer_filter_sql}
""".replace('{network}', network).strip()


def _build_attester_subquery(network: str, attester_filter_sql: str) -> str:
    metadata_subquery = textwrap.indent(_build_validator_metadata_subquery(network), '  ')

    return f"""
SELECT
  base.slot AS slot,
  base.attesting_validator_index AS attesting_validator_index,
  base.status AS status,
  base.slot_distance AS slot_distance,
  vm.cl_client      AS attester_cl_client,
  vm.el_client      AS attester_el_client,
  vm.node_type      AS attester_node_type,
  vm.architecture   AS attester_architecture,
  vm.operator       AS attester_operator,
  vm.region         AS attester_region,
  vm.datacenter     AS attester_datacenter
FROM (
  SELECT slot, attesting_validator_index, status, slot_distance, slot_start_date_time
  FROM `{network}`.fct_attestation_correctness_by_validator_canonical FINAL
  WHERE slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
) AS base
LEFT JOIN (
{metadata_subquery}
) vm ON base.attesting_validator_index = vm.validator_index
WHERE 1 = 1{attester_filter_sql}
""".replace('{network}', network).strip()


def _build_blob_subquery(network: str) -> str:
    return f"""
SELECT
  slot,
  anyLast(blob_count) AS blob_count
FROM `{network}`.fct_block_blob_count_head FINAL
WHERE slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
GROUP BY slot
""".replace('{network}', network).strip()


def _build_attester_filter_clause(
    attester_type: Optional[str],
    cl_filter: Optional[List[str]],
    el_filter: Optional[List[str]],
    architecture_filter: Optional[List[str]],
    operator_filter: Optional[List[str]],
    region_filter: Optional[List[str]] = None,
    datacenter_filter: Optional[List[str]] = None,
    ignore_offline_validators: bool = False
) -> str:
    clause = ""
    # Filter out offline validators (status='missed') if requested
    if ignore_offline_validators:
        clause += "\n      AND base.status != 'missed'"
    if attester_type:
        clause += f"\n      AND coalesce(vm.node_type, 'unknown') = '{attester_type}'"
    if cl_filter:
        clause += f"\n      AND coalesce(vm.cl_client, 'unknown'){_format_in_clause(cl_filter)}"
    if el_filter:
        clause += f"\n      AND coalesce(vm.el_client, 'unknown'){_format_in_clause(el_filter)}"
    if architecture_filter:
        clause += f"\n      AND coalesce(vm.architecture, 'unknown'){_format_in_clause(architecture_filter)}"
    if operator_filter:
        clause += f"\n      AND coalesce(vm.operator, 'unknown'){_format_in_clause(operator_filter)}"
    if region_filter:
        clause += f"\n      AND coalesce(vm.region, 'unknown'){_format_in_clause(region_filter)}"
    if datacenter_filter:
        clause += f"\n      AND coalesce(vm.datacenter, 'unknown'){_format_in_clause(datacenter_filter)}"
    return clause


def _build_proposer_filter_clause(
    proposer_type: Optional[str],
    cl_filter: Optional[List[str]],
    el_filter: Optional[List[str]],
    architecture_filter: Optional[List[str]],
    operator_filter: Optional[List[str]],
    region_filter: Optional[List[str]] = None,
    datacenter_filter: Optional[List[str]] = None
) -> str:
    clause = ""
    if proposer_type:
        clause += f"\n      AND coalesce(vm.node_type, 'unknown') = '{proposer_type}'"
    if cl_filter:
        clause += f"\n      AND coalesce(vm.cl_client, 'unknown'){_format_in_clause(cl_filter)}"
    if el_filter:
        clause += f"\n      AND coalesce(vm.el_client, 'unknown'){_format_in_clause(el_filter)}"
    if architecture_filter:
        clause += f"\n      AND coalesce(vm.architecture, 'unknown'){_format_in_clause(architecture_filter)}"
    if operator_filter:
        clause += f"\n      AND coalesce(vm.operator, 'unknown'){_format_in_clause(operator_filter)}"
    if region_filter:
        clause += f"\n      AND coalesce(vm.region, 'unknown'){_format_in_clause(region_filter)}"
    if datacenter_filter:
        clause += f"\n      AND coalesce(vm.datacenter, 'unknown'){_format_in_clause(datacenter_filter)}"
    return clause


def _build_mev_filter_clause(mev_filter: Optional[str], alias: str = 'ps') -> str:
    if mev_filter == 'yes':
        return f"\n    AND {alias}.mev_status = 'mev'"
    if mev_filter == 'no':
        return f"\n    AND {alias}.mev_status = 'non-mev'"
    return ""


PROPOSER_GROUP_EXPRESSIONS = {
    'none': "'all'",
    'node_type': "coalesce(ps.proposer_node_type, 'unknown')",
    'cl_client': "coalesce(ps.proposer_cl_client, 'unknown')",
    'el_client': "coalesce(ps.proposer_el_client, 'unknown')",
    'architecture': "coalesce(ps.proposer_architecture, 'unknown')",
    'operator': "coalesce(ps.proposer_operator, 'unknown')",
    'region': "coalesce(ps.proposer_region, 'unknown')",
    'datacenter': "coalesce(ps.proposer_datacenter, 'unknown')",
    'cl_el_combined': "coalesce(concat(ps.proposer_cl_client, '-', ps.proposer_el_client), 'unknown')",
    'cl_node_type': "coalesce(concat(ps.proposer_cl_client, '-', ps.proposer_node_type), 'unknown')",
    'cl_architecture': "coalesce(concat(ps.proposer_cl_client, '-', ps.proposer_architecture), 'unknown')",
    'cl_operator': "coalesce(concat(ps.proposer_cl_client, '-', ps.proposer_operator), 'unknown')",
    'block_building': "if(ps.mev_status = 'mev', 'mev', 'non-mev')",
    'node_type_mev': "coalesce(concat(ps.proposer_node_type, '-', ps.mev_status), 'unknown')",
    'cl_node_type_mev': "coalesce(concat(ps.proposer_cl_client, '-', ps.proposer_node_type, '-', ps.mev_status), 'unknown')",
}


ATTESTER_GROUP_EXPRESSIONS = {
    'none': "'all'",
    'node_type': "coalesce(ae.attester_node_type, 'unknown')",
    'cl_client': "coalesce(ae.attester_cl_client, 'unknown')",
    'el_client': "coalesce(ae.attester_el_client, 'unknown')",
    'architecture': "coalesce(ae.attester_architecture, 'unknown')",
    'operator': "coalesce(ae.attester_operator, 'unknown')",
    'region': "coalesce(ae.attester_region, 'unknown')",
    'datacenter': "coalesce(ae.attester_datacenter, 'unknown')",
    'cl_el_combined': "coalesce(concat(ae.attester_cl_client, '-', ae.attester_el_client), 'unknown')",
    'cl_node_type': "coalesce(concat(ae.attester_cl_client, '-', ae.attester_node_type), 'unknown')",
    'el_node_type': "coalesce(concat(ae.attester_el_client, '-', ae.attester_node_type), 'unknown')",
    'cl_architecture': "coalesce(concat(ae.attester_cl_client, '-', ae.attester_architecture), 'unknown')",
    'cl_operator': "coalesce(concat(ae.attester_cl_client, '-', ae.attester_operator), 'unknown')",
}


def _build_base_head_correctness_sql(network: str, proposer_filter_sql: str, attester_filter_sql: str, mev_filter_sql: str) -> str:
    proposer_subquery = textwrap.indent(_build_proposer_subquery(network, proposer_filter_sql), '  ')
    attester_subquery = textwrap.indent(_build_attester_subquery(network, attester_filter_sql), '  ')
    blob_subquery = textwrap.indent(_build_blob_subquery(network), '  ')

    return f"""
SELECT
  ae.slot AS slot,
  countDistinct(ae.attesting_validator_index) AS total_scheduled,
  countDistinctIf(ae.attesting_validator_index, ae.status = 'canonical' AND ae.slot_distance = 0) AS correct_votes,
  if(countDistinct(ae.attesting_validator_index) > 0,
     round(100.0 * countDistinctIf(ae.attesting_validator_index, ae.status = 'canonical' AND ae.slot_distance = 0)
           / countDistinct(ae.attesting_validator_index), 2),
     NULL) AS head_correctness_pct,
  coalesce(bc.blob_count, toUInt64(0)) AS blob_count
FROM (
{proposer_subquery}
) ps
INNER JOIN (
{attester_subquery}
) ae ON ps.slot = ae.slot
LEFT JOIN (
{blob_subquery}
) bc ON ps.slot = bc.slot
WHERE 1 = 1{mev_filter_sql}
GROUP BY ae.slot, bc.blob_count
ORDER BY ae.slot
"""


def _build_proposer_group_sql(network: str, proposer_filter_sql: str, attester_filter_sql: str, grouping_dimension: str, mev_filter_sql: str) -> str:
    proposer_subquery = textwrap.indent(_build_proposer_subquery(network, proposer_filter_sql), '  ')
    attester_subquery = textwrap.indent(_build_attester_subquery(network, attester_filter_sql), '  ')
    blob_subquery = textwrap.indent(_build_blob_subquery(network), '  ')
    group_expr = PROPOSER_GROUP_EXPRESSIONS.get(grouping_dimension or 'node_type', "coalesce(ps.proposer_node_type, 'unknown')")

    return f"""
SELECT
  ae.slot AS slot,
  {group_expr} AS group_key,
  coalesce(bc.blob_count, toUInt64(0)) AS blob_count,
  countDistinct(ae.attesting_validator_index) AS total_scheduled_in_group,
  countDistinctIf(ae.attesting_validator_index, ae.status = 'canonical' AND ae.slot_distance = 0) AS correct_votes_in_group,
  if(countDistinct(ae.attesting_validator_index) > 0,
     round(100.0 * countDistinctIf(ae.attesting_validator_index, ae.status = 'canonical' AND ae.slot_distance = 0)
           / countDistinct(ae.attesting_validator_index), 2),
     NULL) AS head_correctness_pct
FROM (
{proposer_subquery}
) ps
INNER JOIN (
{attester_subquery}
) ae ON ps.slot = ae.slot
LEFT JOIN (
{blob_subquery}
) bc ON ps.slot = bc.slot
WHERE 1 = 1{mev_filter_sql}
GROUP BY ae.slot, group_key, bc.blob_count
ORDER BY ae.slot, group_key
"""


def _build_attester_group_sql(network: str, proposer_filter_sql: str, attester_filter_sql: str, grouping_dimension: str, mev_filter_sql: str) -> str:
    proposer_subquery = textwrap.indent(_build_proposer_subquery(network, proposer_filter_sql), '  ')
    attester_subquery = textwrap.indent(_build_attester_subquery(network, attester_filter_sql), '  ')
    blob_subquery = textwrap.indent(_build_blob_subquery(network), '  ')
    group_expr = ATTESTER_GROUP_EXPRESSIONS.get(grouping_dimension or 'node_type', "coalesce(ae.attester_node_type, 'unknown')")

    return f"""
SELECT
  ae.slot AS slot,
  {group_expr} AS group_key,
  coalesce(bc.blob_count, toUInt64(0)) AS blob_count,
  countDistinct(ae.attesting_validator_index) AS total_scheduled_in_group,
  countDistinctIf(ae.attesting_validator_index, ae.status = 'canonical' AND ae.slot_distance = 0) AS correct_votes_in_group,
  if(countDistinct(ae.attesting_validator_index) > 0,
     round(100.0 * countDistinctIf(ae.attesting_validator_index, ae.status = 'canonical' AND ae.slot_distance = 0)
           / countDistinct(ae.attesting_validator_index), 2),
     NULL) AS head_correctness_pct
FROM (
{proposer_subquery}
) ps
INNER JOIN (
{attester_subquery}
) ae ON ps.slot = ae.slot
LEFT JOIN (
{blob_subquery}
) bc ON ps.slot = bc.slot
WHERE 1 = 1{mev_filter_sql}
GROUP BY ae.slot, group_key, bc.blob_count
ORDER BY ae.slot, group_key
"""





def load_head_correctness_data(
    network: str,
    start_date: datetime,
    end_date: datetime,
    eligible_slots: List[int],
    slot_to_block: Dict[int, str],
    slot_to_proposer: Dict[int, int] = None,
    mev_slots: List[int] = None,
    mev_filter: Optional[str] = None,
    proposer_type: Optional[str] = None,
    proposer_cl_filter: Optional[List[str]] = None,
    proposer_el_filter: Optional[List[str]] = None,
    proposer_architecture_filter: Optional[List[str]] = None,
    proposer_operator_filter: Optional[List[str]] = None,
    proposer_region_filter: Optional[List[str]] = None,
    proposer_datacenter_filter: Optional[List[str]] = None,
    attester_type: Optional[str] = None,
    cl_filter: Optional[List[str]] = None,
    el_filter: Optional[List[str]] = None,
    architecture_filter: Optional[List[str]] = None,
    operator_filter: Optional[List[str]] = None,
    region_filter: Optional[List[str]] = None,
    datacenter_filter: Optional[List[str]] = None,
    grouping_dimension: Optional[str] = None,
    attester_grouping_dimension: Optional[str] = None,
    ignore_offline_validators: bool = False,
    cluster_name: Optional[str] = None
) -> pd.DataFrame:
    """Load head correctness metrics using precomputed ClickHouse fact tables."""

    logger.info(
        "Head correctness query: network=%s slots=%d grouping=%s attester_group=%s",
        network,
        len(eligible_slots),
        grouping_dimension,
        attester_grouping_dimension,
    )

    if not eligible_slots:
        logger.warning("No eligible slots provided to load_head_correctness_data")
        return pd.DataFrame()

    proposer_filter_sql = _build_proposer_filter_clause(
        proposer_type,
        proposer_cl_filter,
        proposer_el_filter,
        proposer_architecture_filter,
        proposer_operator_filter,
        proposer_region_filter,
        proposer_datacenter_filter
    )

    attester_filter_sql = _build_attester_filter_clause(
        attester_type,
        cl_filter,
        el_filter,
        architecture_filter,
        operator_filter,
        region_filter,
        datacenter_filter,
        ignore_offline_validators
    )

    mev_filter_sql = _build_mev_filter_clause(mev_filter)

    params = {
        'start_date': start_date,
        'end_date': end_date,
    }

    base_sql = _build_base_head_correctness_sql(network, proposer_filter_sql, attester_filter_sql, mev_filter_sql)
    conn = get_routed_connection(base_sql, cluster_name)
    if not conn:
        logger.error("Failed to obtain ClickHouse connection (cluster=%s)", cluster_name)
        return pd.DataFrame()

    overall_df = pd.read_sql(base_sql, conn, params=params)

    if overall_df.empty:
        logger.warning("Head correctness base query returned no data for the provided filters")
        return pd.DataFrame()

    overall_df = overall_df.rename(
        columns={
            'total_scheduled': 'total_validators_assigned',
            'correct_votes': 'correct_head_votes',
        }
    )
    overall_df['data_type'] = 'overall'

    combined_frames: List[pd.DataFrame] = [overall_df]

    if grouping_dimension and grouping_dimension != 'none':
        proposer_sql = _build_proposer_group_sql(network, proposer_filter_sql, attester_filter_sql, grouping_dimension, mev_filter_sql)
        proposer_conn = get_routed_connection(proposer_sql, cluster_name)
        if not proposer_conn:
            logger.error("Failed to obtain ClickHouse connection for proposer grouping (cluster=%s)", cluster_name)
        else:
            proposer_df = pd.read_sql(proposer_sql, proposer_conn, params=params)
            if not proposer_df.empty:
                proposer_df = proposer_df.rename(
                    columns={
                        'total_scheduled_in_group': 'total_validators_assigned',
                        'correct_votes_in_group': 'correct_head_votes',
                    }
                )
                proposer_df['data_type'] = 'proposer'
                proposer_df['grouping_dimension'] = grouping_dimension
                combined_frames.append(proposer_df)

    if attester_grouping_dimension and attester_grouping_dimension != 'none':
        attester_sql = _build_attester_group_sql(network, proposer_filter_sql, attester_filter_sql, attester_grouping_dimension, mev_filter_sql)
        attester_conn = get_routed_connection(attester_sql, cluster_name)
        if not attester_conn:
            logger.error("Failed to obtain ClickHouse connection for attester grouping (cluster=%s)", cluster_name)
        else:
            attester_df = pd.read_sql(attester_sql, attester_conn, params=params)
            if not attester_df.empty:
                attester_df = attester_df.rename(
                    columns={
                        'total_scheduled_in_group': 'total_validators_assigned',
                        'correct_votes_in_group': 'correct_head_votes',
                    }
                )
                attester_df['data_type'] = 'attester'
                attester_df['grouping_dimension'] = attester_grouping_dimension
                combined_frames.append(attester_df)

    result_df = pd.concat(combined_frames, ignore_index=True)

    if 'blob_count' in result_df.columns:
        result_df['blob_count'] = result_df['blob_count'].fillna(0).astype(int)

    return result_df

def validate_data_availability(
    network: str,
    start_date: datetime,
    end_date: datetime,
    cluster_name: Optional[str] = None
) -> Dict[str, bool]:
    """
    Check which data sources are available for the given time range.

    Returns:
        Dictionary indicating availability of each data source
    """
    availability = {}

    # Check beacon API attestations
    try:
        query = """
        SELECT COUNT(*) as count
        FROM beacon_api_eth_v1_events_attestation
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        LIMIT 1
        """
        conn = get_routed_connection(query, cluster_name)
        if not conn:
            logger.error(f"Failed to get database connection for cluster: {cluster_name}")
            availability['beacon_api'] = False
        else:
            result = pd.read_sql(query, conn, params={'network': network, 'start_date': start_date, 'end_date': end_date})
            availability['beacon_api'] = result['count'].iloc[0] > 0 if not result.empty else False
    except Exception as e:
        logger.warning(f"Failed to check beacon_api availability: {e}")
        availability['beacon_api'] = False

    # Check libp2p attestations
    try:
        query = """
        SELECT COUNT(*) as count
        FROM libp2p_gossipsub_beacon_attestation
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
        LIMIT 1
        """
        conn = get_routed_connection(query, cluster_name)
        if not conn:
            logger.error(f"Failed to get database connection for cluster: {cluster_name}")
            availability['libp2p_gossipsub'] = False
        else:
            result = pd.read_sql(query, conn, params={'network': network, 'start_date': start_date, 'end_date': end_date})
            availability['libp2p_gossipsub'] = result['count'].iloc[0] > 0 if not result.empty else False
    except Exception as e:
        logger.warning(f"Failed to check libp2p_gossipsub availability: {e}")
        availability['libp2p_gossipsub'] = False

    return availability



def get_unique_clients(
    network: str,
    start_date: datetime,
    end_date: datetime,
    cluster_name: Optional[str] = None
) -> List[str]:
    """
    Get list of unique client implementations from the network spec.
    
    Returns:
        List of client names (CL and EL implementations)
    """
    # Get network spec for this network
    network_spec = get_network_spec(network)
    
    if network_spec:
        # Get all unique CL and EL implementations from the network spec
        cl_implementations = set()
        el_implementations = set()
        
        for node_name in network_spec.get_all_nodes():
            node_clients = network_spec.get_node_clients(node_name)
            if node_clients['cl']:
                cl_implementations.add(node_clients['cl'])
            if node_clients['el']:
                el_implementations.add(node_clients['el'])
        
        # Return a list of unique implementations
        # Format as "cl-el" for compatibility with existing code
        client_combinations = []
        for cl in cl_implementations:
            for el in el_implementations:
                client_combinations.append(f"{cl}-{el}")
        
        return sorted(client_combinations)
    else:
        # Fallback to querying the database if no network spec
        query = """
        SELECT DISTINCT meta_client_name as client_name
        FROM beacon_api_eth_v1_events_attestation
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
            AND meta_client_name != ''
        ORDER BY client_name
        """

        conn = get_routed_connection(query, cluster_name)
        if not conn:
            logger.error(f"Failed to get database connection for cluster: {cluster_name}")
            return []

        try:
            df = pd.read_sql(query, conn, params={'network': network, 'start_date': start_date, 'end_date': end_date})
            return df['client_name'].tolist() if not df.empty else []
        except Exception as e:
            logger.error(f"Error getting unique clients: {e}")
            return []
