# Validator Index Lookup Implementation Plan

## Executive Summary
> The validator performance dashboard requires a mechanism to convert user-provided validator public keys (pubkeys) to their corresponding validator indices. This is essential because most ClickHouse tables store performance data indexed by validator index, not pubkey. 
> 
> This implementation will query the `canonical_beacon_validators_pubkeys` table to map pubkeys to indices, handle cases where pubkeys are not found, and maintain a clean list of valid validators for subsequent data lookups.

## Goals & Objectives
### Primary Goals
- Enable users to input validator pubkeys and retrieve corresponding validator indices from ClickHouse
- Provide clear feedback when validator pubkeys are not found in the database

### Secondary Objectives
- Optimize bulk lookups for 100+ validators
- Cache results to minimize database queries
- Maintain consistency with existing dashboard patterns

## Solution Overview
### Approach
Implement a data loading function in the validator performance dashboard that queries ClickHouse to map validator pubkeys to their indices. This follows the established pattern from the attestation packing dashboard.

### Key Components
1. **Data Loader Function**: Query ClickHouse for pubkey-to-index mapping
2. **Error Handling**: Display warnings for missing pubkeys and exclude them from further processing
3. **Session State Integration**: Store valid mappings and track excluded pubkeys

### Data Flow
```
User Input (Pubkeys) → Validation → ClickHouse Query → Index Mapping
                                                      ↓
                                              Warning for Missing
                                                      ↓
                                            Valid Indices for Future Use
```

### Expected Outcomes
- Users can input validator pubkeys and the system will retrieve their indices
- Missing pubkeys are clearly reported to users with appropriate warnings
- Only validators with valid indices proceed to performance data queries

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
shared/
├── database.py (Already exists - provides get_database_connection())
│
pages/analysis/validator_performance/
├── data_loaders.py (Task #0: Implement load_validator_indices function)
├── interactive_dashboard.py (Task #1: Integrate index lookup into data loading flow)
└── session_state.py (Task #1: Add state management for index mappings)
```

### Execution Plan

#### Group A: Core Implementation (Execute in sequence)
- [ ] **Task #0**: Create validator index lookup function
  - Folder: `pages/analysis/validator_performance/`
  - File: `data_loaders.py`
  - Imports:
    ```python
    from typing import Dict, List, Tuple, Optional
    import pandas as pd
    from sqlalchemy import text
    import streamlit as st
    from shared.database import get_database_connection
    ```
  - Implements:
    - `load_validator_indices(pubkeys: List[str], network: str) -> Tuple[Dict[str, int], List[str]]`
      - Parameters:
        - pubkeys: List of cleaned, validated pubkeys (0x-prefixed, lowercase)
        - network: Network name ('mainnet', 'holesky', etc.)
      - Returns:
        - Tuple of (mapping dict, list of missing pubkeys)
        - mapping dict: {pubkey: validator_index}
        - missing list: pubkeys not found in database
      - Query:
        ```sql
        SELECT pubkey, `index` 
        FROM canonical_beacon_validators_pubkeys FINAL 
        WHERE meta_network_name = :network 
        AND pubkey IN :pubkeys
        ```
      - Implementation details:
        - Use parameterized query with SQLAlchemy text()
        - Handle ClickHouse IN clause with tuple conversion
        - Return empty dict and full missing list on connection failure
        - Close connection in finally block
  - Exports: `load_validator_indices` function
  - Context: This is the foundational function for all validator performance queries

- [ ] **Task #1**: Integrate index lookup into dashboard workflow
  - Folder: `pages/analysis/validator_performance/`
  - Files: `interactive_dashboard.py`, `session_state.py` (new file)
  - Imports for interactive_dashboard.py:
    ```python
    from .data_loaders import load_validator_indices
    from .session_state import (
        store_validator_mappings, 
        get_valid_validators, 
        get_excluded_validators,
        clear_validator_mappings
    )
    ```
  - Creates session_state.py with:
    ```python
    import streamlit as st
    from typing import Dict, List
    ```
  - Implements in session_state.py:
    - `store_validator_mappings(pubkey_to_index: Dict[str, int], excluded_pubkeys: List[str]) -> None`
      - Stores in st.session_state['validator_performance_pubkey_to_index']
      - Stores in st.session_state['validator_performance_excluded_pubkeys']
    - `get_valid_validators() -> Dict[str, int]`
      - Returns stored pubkey-to-index mapping
    - `get_excluded_validators() -> List[str]`
      - Returns list of excluded pubkeys
    - `clear_validator_mappings() -> None`
      - Clears stored mappings when configuration changes
  - Modifies interactive_dashboard.py:
    - In `load_data()` function after "Load Data" button:
      1. Call `load_validator_indices(valid_pubkeys, selected_network)`
      2. Display warning for missing pubkeys:
         ```python
         if missing_pubkeys:
             st.warning(f"⚠️ {len(missing_pubkeys)} validator(s) not found in database and will be excluded:")
             for pubkey in missing_pubkeys[:5]:  # Show first 5
                 st.text(f"  • {format_pubkey_for_display(pubkey)}")
             if len(missing_pubkeys) > 5:
                 st.text(f"  • ... and {len(missing_pubkeys) - 5} more")
         ```
      3. Store results with `store_validator_mappings(pubkey_to_index, missing_pubkeys)`
      4. Display success message with count of valid validators
    - In configuration change detection:
      - Call `clear_validator_mappings()` when network or validators change
  - Context: Integrates the lookup function into the user workflow with proper feedback

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