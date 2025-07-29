# First Seen Attestations in Next Slot Metrics Implementation Plan

## Executive Summary
> This plan adds a new reusable metric to the Multi-Metric performance analysis page:
> 1. **optimal_inclusion_attestations_in_next_slot_count**: The raw count of validator attestations included on-chain in the optimal slot
> 
> This metric measures how many attestations were included in the slot immediately following when they attested, helping identify if validators are getting their attestations on-chain in time. The count metric is particularly useful for correlation with gas limits to see absolute impact on network congestion.
> 
> The implementation leverages the existing dynamic metric discovery system, requiring only the addition of a new data loader and metric metadata. The metric will automatically appear in the UI for correlation analysis.

## Goals & Objectives
### Primary Goals
- Add optimal inclusion attestation timing metric for network performance analysis
- Enable correlation analysis between attestation counts and gas limits to identify network congestion impacts
- Ensure the metric handles deduplication correctly (same attestation can appear multiple times due to aggregation)

### Secondary Objectives
- Maintain query performance with proper indexing and partitioning strategies
- Follow existing codebase patterns for metric implementation
- Provide clear metric documentation and tooltips for users

## Solution Overview
### Approach
The solution adds a new data loader that queries the `canonical_beacon_elaborated_attestation` table, calculates the minimum inclusion slot for each validator-slot pair, and determines what percentage were included optimally (in the next slot). This integrates seamlessly with the existing Multi-Metric analysis framework.

### Key Components
1. **Data Loader**: New function in `data_loaders.py` that queries attestation timing data
2. **Metric Metadata**: Add metric info to `metric_utils.py` for proper display formatting
3. **Query Optimization**: Efficient ClickHouse query with proper deduplication logic

### Data Flow
```
ClickHouse Table → SQL Query → Polars DataFrame → Dynamic Metric Discovery → UI Selection
     ↓                ↓              ↓                      ↓                    ↓
elaborated_      MIN(block_slot)  Calculate %         Auto-detected      Correlation with
attestation      per validator    next slot          in dashboard         gas limits
```

### Expected Outcomes
- Users can select "optimal_inclusion_attestations_in_next_slot_count" to see absolute attestation counts
- The metric enables direct correlation with gas limits to quantify congestion impacts
- Query performance remains acceptable even for large date ranges

## Implementation Tasks

### CRITICAL IMPLEMENTATION RULES
1. **NO PLACEHOLDER CODE**: Every implementation must be production-ready. NEVER write "TODO", "in a real implementation", or similar placeholders unless explicitly requested by the user.
2. **CROSS-DIRECTORY TASKS**: Group related changes across directories into single tasks to ensure consistency. Never create isolated changes that require follow-up work in sibling directories.
3. **COMPLETE IMPLEMENTATIONS**: Each task must fully implement its feature including all consumers, type updates, and integration points.
4. **DETAILED SPECIFICATIONS**: Each task must include EXACTLY what to implement, including specific functions, types, and integration points to avoid "breaking change" confusion.
5. **CONTEXT AWARENESS**: Each task is part of a larger system - specify how it connects to other parts.
6. **MAKE BREAKING CHANGES**: Unless explicitly requested by the user, you MUST make breaking changes.

### Visual Dependency Tree
```
pages/analysis/multi_metric_analysis/
├── data_loaders.py (Task #1: Add attestation timing data loader)
│
shared/
├── metric_utils.py (Task #0: Add metric metadata)
│
config/
└── query_templates.py (Task #0: Add reusable query template - if file exists)
```

### Execution Plan

#### Group A: Foundation (Execute all in parallel)
- [x] **Task #0**: Add metric metadata
  - Folder: `shared/`
  - File: `metric_utils.py`
  - Function: Update `get_metric_info()` to add:
    ```python
    "optimal_inclusion_attestations_in_next_slot_count": {
        "title": "Optimal Inclusion Attestations",
        "subtitle": "Count of attestations included in the slot immediately following",
        "unit": "attestations",
        "format": ",d"
    }
    ```
  - Context: This metadata is used by the UI to properly display and format the metric

- [x] **Task #0**: Add query template (conditional - only if config/query_templates.py exists)
  - Folder: `config/`
  - File: `query_templates.py` (check if exists first)
  - Function: Add to query templates dictionary:
    ```python
    "attestation_timing": """
    WITH validator_attestations AS (
        SELECT 
            slot,
            block_slot,
            epoch,
            slot_start_date_time,
            arrayJoin(validators) as validator_index
        FROM canonical_beacon_elaborated_attestation
        WHERE meta_network_name = %(network)s
            AND slot_start_date_time BETWEEN %(start_date)s AND %(end_date)s
    ),
    first_inclusions AS (
        SELECT 
            slot,
            validator_index,
            MIN(block_slot) as first_block_slot,
            MIN(block_slot) - slot as inclusion_delay
        FROM validator_attestations
        GROUP BY slot, validator_index
    )
    SELECT 
        slot,
        COUNT(DISTINCT CASE WHEN inclusion_delay = 1 THEN validator_index END) as optimal_inclusion_attestations_in_next_slot_count,
        COUNT(DISTINCT validator_index) as total_attestations
    FROM first_inclusions
    GROUP BY slot
    ORDER BY slot
    """
    ```
  - Context: Reusable query template for attestation timing analysis

#### Group B: Core Implementation (Execute after Group A)
- [x] **Task #1**: Implement attestation timing data loader
  - Folder: `pages/analysis/multi_metric_analysis/`
  - File: `data_loaders.py`
  - Imports to add:
    ```python
    # No new imports needed - uses existing imports
    ```
  - Function to add:
    ```python
    @st.cache_data(ttl=3600)
    def load_attestation_timing_data(
        network: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pl.DataFrame]:
        """
        Load attestation timing data showing optimal inclusion counts.
        
        Returns DataFrame with columns:
        - slot: The attestation slot
        - slot_start_date_time: Timestamp of the slot
        - optimal_inclusion_attestations_in_next_slot_count: Count of attestations included in next slot
        - total_attestations: Total unique attestations in the slot
        """
    ```
  - Implementation details:
    - Use the attestation timing query from Task #0 or inline it
    - Connect to ClickHouse using `get_clickhouse_client()`
    - Execute query with proper parameter binding
    - Convert to Polars DataFrame
    - Rename columns to match metric naming convention
    - Handle null/empty results gracefully
    - Return None if error or use cached empty DataFrame pattern
  - Integration: Update `load_all_data()` function to include:
    ```python
    elif selected_template == "attestation_timing":
        df = load_attestation_timing_data(network, start_date, end_date)
    ```
  - Add to template options in UI if not auto-discovered
  - Context: This loader provides both attestation timing metrics (count and percentage) that will be automatically discovered by the dashboard

---

## Implementation Workflow

This plan file serves as the authoritative checklist for implementation. When implementing:

### Required Process
1. **Load Plan**: Read this entire plan file before starting
2. **Sync Tasks**: Create TodoWrite tasks matching the checkboxes below
3. **Execute & Update**: For each task:
   - Mark TodoWrite as `in_progress` when starting
   - Update checkbox `[ ]` to `[x]` when completing
   - Mark TodoWrite as `completed` when done
4. **Maintain Sync**: Keep this file and TodoWrite synchronized throughout

### Critical Rules
- This plan file is the source of truth for progress
- Update checkboxes in real-time as work progresses
- Never lose synchronization between plan file and TodoWrite
- Mark tasks complete only when fully implemented (no placeholders)
- Tasks should be run in parallel, unless there are dependencies, using subtasks, to avoid context bloat.

### Progress Tracking
The checkboxes above represent the authoritative status of each task. Keep them updated as you work.