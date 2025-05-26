# Comprehensive Shared Functionality Extraction Plan

## Overview

> Extract all generic, reusable functionality from the attestation_packing directory to shared components while preserving 100% functionality. This analysis covers ALL files in the directory and identifies each function as either extractable (generic) or attestation-specific.

## Current State Assessment

### Files Analyzed

- **`config_utils.py`** - Mixed utilities and attestation-specific configurations
- **`data_loaders.py`** - Database connections, parquet handling, and attestation-specific loaders  
- **`metrics_calculators.py`** - Entirely attestation-specific calculation logic
- **`plot_generators.py`** - Mixed generic utilities and attestation-specific plotting
- **`interactive_dashboard.py`** - Mixed UI patterns and attestation-specific dashboard logic
- **`page.py`** - Simple wrapper pattern (could be generalized)

### Function Classification Analysis

#### ✅ EXTRACTABLE (Generic Utilities)

**Database & Infrastructure:**
- `get_database_connection()` (from config_utils.py and data_loaders.py) - Generic ClickHouse connection
- `get_cache_dir()` (from config_utils.py and data_loaders.py) - Generic cache directory creation

**Parquet File Handling:**
- `calculate_parquet_urls()` (from data_loaders.py) - Generic Xatu parquet URL generation
- `download_and_cache_parquet()` (from data_loaders.py) - Generic parquet download and caching

**Data Processing:**
- `get_aggregate_function()` (from plot_generators.py) - Generic aggregation string to pandas function mapping

**UI & Branding:**
- `add_ethpandaops_logo()` (from plot_generators.py) - Generic EthPandaOps branding
- CSS styling patterns (from interactive_dashboard.py) - Generic Streamlit styling
- Time range configuration UI patterns (from interactive_dashboard.py) - Generic date selection
- Cache management UI patterns (from interactive_dashboard.py) - Generic cache controls

#### ❌ NON-EXTRACTABLE (Attestation-Specific)

**Metric Definitions:**
- `get_metric_info()` (from config_utils.py and plot_generators.py) - Hardcoded attestation metrics

**Attestation Data Loading:**
- `load_blockprint_clients()` - Specific to validator/client mapping
- `load_attestation_data_parquet()` - Specific to attestation table structure
- `load_attestation_data()` - Specific to attestation table (ClickHouse version)
- `fetch_proposer_indices_parquet()` - Specific to beacon block proposer data
- `fetch_proposer_indices()` - Specific to beacon block proposer data  
- `load_validators_from_ethseer()` - Specific to validator entity mapping

**Metrics Calculation:**
- `calculate_first_seen_attestations()` - Entirely attestation-specific validator tracking logic
- `calculate_slot_metrics()` - Entirely attestation-specific metrics calculation

**Plotting Functions:**
- `create_before_after_comparison()` - Uses attestation-specific metric info
- `create_distribution_plot()` - Uses attestation-specific metric info
- `create_time_series_plot()` - Uses attestation-specific metric info
- `create_inclusion_distance_distribution()` - Heavily specific to attestation inclusion concepts

**Dashboard Logic:**
- Main dashboard orchestration - Entirely attestation-specific
- Entity/client selection logic - Uses attestation-specific data sources
- Metric selection and configuration - Attestation-specific metrics

## Goals

1. **Primary goal**: Extract ALL generic functionality to shared modules while keeping attestation-specific code in place
2. **Eliminate duplication**: Remove duplicate functions like `get_database_connection()` and `get_cache_dir()`
3. **Create reusable infrastructure**: Enable future analysis pages to use shared data loading and UI patterns
4. **Preserve functionality**: Maintain 100% of existing attestation packing behavior
5. **Modular organization**: Clear separation between generic utilities and domain-specific logic
6. **Import simplification**: Clean import paths for attestation_packing after extraction

## Design Approach

### Architecture Overview

Extract functions into focused shared modules organized by responsibility:

- **Core infrastructure** (database, caching) used by all analysis pages
- **Data loading utilities** for common Xatu data patterns (parquet handling)
- **UI components** for common dashboard patterns (styling, time selection)
- **Analysis utilities** for common data processing patterns (aggregation functions)

### Component Breakdown

1. **Database Infrastructure** (`shared/database.py`)
   - Purpose: Database connections and configuration management
   - Functions: `get_database_connection()`
   - Deduplication: Merge identical functions from config_utils.py and data_loaders.py

2. **File System Utilities** (`shared/filesystem.py`) 
   - Purpose: Cache management and file system operations
   - Functions: `get_cache_dir()`
   - Deduplication: Merge identical functions from config_utils.py and data_loaders.py

3. **Parquet Data Utilities** (`shared/parquet_utils.py`)
   - Purpose: Generic parquet file handling for Xatu data
   - Functions: `calculate_parquet_urls()`, `download_and_cache_parquet()`
   - Reusability: Any analysis page needing Xatu parquet data

4. **Data Processing Utilities** (`shared/data_utils.py`)
   - Purpose: Generic data processing functions
   - Functions: `get_aggregate_function()`
   - Reusability: Any analysis page doing aggregations

5. **UI Components** (`shared/ui_components.py`)
   - Purpose: Common Streamlit UI patterns and styling
   - Functions: `add_ethpandaops_logo()`, CSS styling, time range widgets
   - Reusability: Consistent branding and UI patterns across all pages

## Implementation Approach

### 1. Extract Database Infrastructure

#### Specific Changes

- Create `shared/database.py` with deduplicated database connection logic
- Remove duplicate `get_database_connection()` from both config_utils.py and data_loaders.py
- Preserve exact connection behavior and error handling

#### Sample Implementation

```python
# shared/database.py
import os
import streamlit as st
from sqlalchemy import create_engine

def get_database_connection():
    """Create database connection for ClickHouse."""
    try:
        username = os.getenv('XATU_CLICKHOUSE_USERNAME')
        password = os.getenv('XATU_CLICKHOUSE_PASSWORD')
        host = os.getenv('XATU_CLICKHOUSE_HOST')
        
        if not all([username, password, host]):
            st.error("Missing database credentials. Please check your .env file.")
            return None
            
        db_url = f"clickhouse+http://{username}:{password}@{host}:443/default?protocol=https"
        engine = create_engine(db_url)
        return engine.connect()
    except Exception as e:
        st.error(f"Failed to connect to database: {e}")
        return None
```

#### Implementation Commands

```bash
# Extract database function from data_loaders.py
sed -n '398,414p' pages/analysis/attestation_packing/data_loaders.py > shared/database.py
# Add proper imports at the top
sed -i '1i import os\nimport streamlit as st\nfrom sqlalchemy import create_engine\n' shared/database.py

# Remove from data_loaders.py
sed -i '398,414d' pages/analysis/attestation_packing/data_loaders.py

# Remove from config_utils.py (find and remove the duplicate)
grep -n "def get_database_connection" pages/analysis/attestation_packing/config_utils.py
# Use line numbers from grep to remove the function
```

### 2. Extract File System Utilities

#### Specific Changes

- Create `shared/filesystem.py` with cache directory management
- Remove duplicate `get_cache_dir()` functions 
- Add any other file system utilities discovered

#### Sample Implementation

```python
# shared/filesystem.py
from pathlib import Path

def get_cache_dir():
    """Get the cache directory for parquet files."""
    cache_dir = Path(".cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
```

#### Implementation Commands

```bash
# Extract from data_loaders.py
sed -n '450,454p' pages/analysis/attestation_packing/data_loaders.py > shared/filesystem.py
sed -i '1i from pathlib import Path\n' shared/filesystem.py

# Remove duplicates
sed -i '450,454d' pages/analysis/attestation_packing/data_loaders.py
# Remove from config_utils.py if it exists there too
```

### 3. Extract Parquet Data Utilities

#### Specific Changes

- Create `shared/parquet_utils.py` with generic Xatu parquet handling
- Extract `calculate_parquet_urls()` and `download_and_cache_parquet()`
- These functions are generic enough to work with any Xatu table

#### Sample Implementation

```python
# shared/parquet_utils.py
import streamlit as st
import pandas as pd
import requests
import hashlib
from datetime import datetime, timedelta
from .filesystem import get_cache_dir

def calculate_parquet_urls(start_date_str, end_date_str, network, table_name):
    """Calculate the parquet file URLs needed for a date range."""
    # [Function body preserved exactly]

def download_and_cache_parquet(url, cache_dir):
    """Download and cache a parquet file locally."""
    # [Function body preserved exactly]
```

#### Implementation Commands

```bash
# Extract functions from data_loaders.py (lines 13-64)
sed -n '1,11p' pages/analysis/attestation_packing/data_loaders.py > shared/parquet_utils.py
sed -n '13,64p' pages/analysis/attestation_packing/data_loaders.py >> shared/parquet_utils.py
# Add import for filesystem
sed -i '11a from .filesystem import get_cache_dir' shared/parquet_utils.py

# Remove from original file
sed -i '13,64d' pages/analysis/attestation_packing/data_loaders.py
```

### 4. Extract Data Processing Utilities

#### Specific Changes

- Create `shared/data_utils.py` with generic data processing functions
- Extract `get_aggregate_function()` from plot_generators.py
- Keep it pure - no dependencies on attestation-specific logic

#### Sample Implementation

```python
# shared/data_utils.py
import pandas as pd

def get_aggregate_function(aggregate):
    """Convert aggregate string to pandas function."""
    agg_map = {
        'mean': 'mean',
        'min': 'min',
        'max': 'max',
        'median': 'median',
        'p05': lambda x: x.quantile(0.05),
        'p50': lambda x: x.quantile(0.50),
        'p90': lambda x: x.quantile(0.90),
        'p95': lambda x: x.quantile(0.95),
        'p99': lambda x: x.quantile(0.99)
    }
    return agg_map.get(aggregate, 'mean')
```

#### Implementation Commands

```bash
# Extract from plot_generators.py (lines 6-19)
echo "import pandas as pd\n" > shared/data_utils.py
sed -n '6,19p' pages/analysis/attestation_packing/plot_generators.py >> shared/data_utils.py

# Remove from plot_generators.py
sed -i '6,19d' pages/analysis/attestation_packing/plot_generators.py
```

### 5. Extract UI Components

#### Specific Changes

- Create `shared/ui_components.py` with common UI patterns
- Extract `add_ethpandaops_logo()` function
- Extract CSS styling patterns from interactive_dashboard.py
- Create reusable time range and cache management widgets

#### Sample Implementation

```python
# shared/ui_components.py
import streamlit as st
from datetime import datetime, date, timedelta

def add_ethpandaops_logo(fig):
    """Add EthPandaOps logo to a plotly figure."""
    # Function is currently disabled but extracted for future use
    return fig

def apply_ethpandaops_styling():
    """Apply consistent EthPandaOps styling to Streamlit app."""
    st.markdown("""
    <style>
        /* Main header styling */
        .main-header {
            text-align: center;
            color: #1e40af;
            border-bottom: 3px solid #3b82f6;
            padding-bottom: 1rem;
            margin-bottom: 2rem;
        }
        
        /* Metric cards */
        .metric-card {
            background: #f8fafc;
            padding: 1.5rem;
            border-radius: 10px;
            border: 1px solid #e2e8f0;
            margin: 0.5rem 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        /* Other styling preserved... */
    </style>
    """, unsafe_allow_html=True)

def create_time_range_selector():
    """Create a standardized time range selection widget."""
    # Extract time range patterns from interactive_dashboard.py
    pass

def create_cache_management_controls():
    """Create standardized cache management controls."""
    # Extract cache management patterns
    pass
```

#### Implementation Commands

```bash
# Extract logo function from plot_generators.py (lines 21-24)
echo "import streamlit as st\nfrom datetime import datetime, date, timedelta\n" > shared/ui_components.py
sed -n '21,24p' pages/analysis/attestation_packing/plot_generators.py >> shared/ui_components.py

# Extract CSS from interactive_dashboard.py (lines 29-73)
echo "\ndef apply_ethpandaops_styling():" >> shared/ui_components.py
echo '    """Apply consistent EthPandaOps styling to Streamlit app."""' >> shared/ui_components.py
sed -n '29,73p' pages/analysis/attestation_packing/interactive_dashboard.py | sed 's/^/    /' >> shared/ui_components.py

# Remove from original files
sed -i '21,24d' pages/analysis/attestation_packing/plot_generators.py
sed -i '29,73d' pages/analysis/attestation_packing/interactive_dashboard.py
```

### 6. Update Import Statements

#### Specific Changes

- Update all files in attestation_packing to import from shared modules
- Replace local function calls with shared module imports
- Ensure all functionality remains identical

#### Sample Implementation

```python
# pages/analysis/attestation_packing/data_loaders.py - Updated imports
from shared.database import get_database_connection
from shared.filesystem import get_cache_dir
from shared.parquet_utils import calculate_parquet_urls, download_and_cache_parquet

# pages/analysis/attestation_packing/plot_generators.py - Updated imports  
from shared.data_utils import get_aggregate_function
from shared.ui_components import add_ethpandaops_logo

# pages/analysis/attestation_packing/interactive_dashboard.py - Updated imports
from shared.ui_components import apply_ethpandaops_styling
```

#### Implementation Commands

```bash
# Update data_loaders.py
sed -i '1i from shared.database import get_database_connection\nfrom shared.filesystem import get_cache_dir\nfrom shared.parquet_utils import calculate_parquet_urls, download_and_cache_parquet\n' pages/analysis/attestation_packing/data_loaders.py

# Update plot_generators.py  
sed -i '5i from shared.data_utils import get_aggregate_function\nfrom shared.ui_components import add_ethpandaops_logo\n' pages/analysis/attestation_packing/plot_generators.py

# Update interactive_dashboard.py
sed -i '11i from shared.ui_components import apply_ethpandaops_styling\n' pages/analysis/attestation_packing/interactive_dashboard.py

# Replace function calls with imported versions
find pages/analysis/attestation_packing/ -name "*.py" -exec sed -i 's/def get_cache_dir():/# Removed - using shared version/g' {} \;
find pages/analysis/attestation_packing/ -name "*.py" -exec sed -i 's/def get_database_connection():/# Removed - using shared version/g' {} \;
```

### 7. Create Shared Module Init

#### Specific Changes

- Create `shared/__init__.py` with convenient imports
- Organize imports by category for easy discovery
- Document the shared module structure

#### Sample Implementation

```python
# shared/__init__.py
"""
EthPandaOps Analysis Dashboard - Shared Utilities

This package provides reusable functionality for analysis pages:

Database & Infrastructure:
- database.py: ClickHouse connections
- filesystem.py: Cache and file management

Data Processing:
- parquet_utils.py: Xatu parquet file handling  
- data_utils.py: Generic data processing utilities

UI & Branding:
- ui_components.py: Common Streamlit components and styling
"""

# Convenient imports for common functions
from .database import get_database_connection
from .filesystem import get_cache_dir
from .parquet_utils import calculate_parquet_urls, download_and_cache_parquet
from .data_utils import get_aggregate_function
from .ui_components import add_ethpandaops_logo, apply_ethpandaops_styling

__all__ = [
    'get_database_connection',
    'get_cache_dir', 
    'calculate_parquet_urls',
    'download_and_cache_parquet',
    'get_aggregate_function',
    'add_ethpandaops_logo',
    'apply_ethpandaops_styling'
]
```

## Testing Strategy

### Unit Testing

- **Function preservation**: Test that each extracted function works identically to original
- **Import resolution**: Verify all shared module imports work correctly
- **Deduplication**: Ensure no duplicate functions remain in attestation_packing
- **Error handling**: Validate same error messages and behavior

### Integration Testing

- **Full attestation workflow**: Complete end-to-end test of attestation packing analysis
- **Shared module independence**: Test that shared modules work without attestation-specific code
- **Import paths**: Verify all relative imports resolve correctly after moves
- **UI consistency**: Ensure styling and branding remain identical

### Validation Criteria

- **Functionality preservation**: 100% identical behavior for attestation packing analysis
- **Code deduplication**: No duplicate functions across files
- **Import cleanliness**: Clear, logical import statements in attestation_packing
- **Shared reusability**: Other analysis pages can import and use shared modules

## Implementation Dependencies

### Phase 1: Extract Core Infrastructure

- [ ] Create `shared/database.py` and `shared/filesystem.py`
- [ ] Remove duplicate database and cache functions from attestation_packing
- [ ] Update imports in attestation_packing files
- [ ] Test database connections and cache operations work
- Dependencies: None

### Phase 2: Extract Data Processing Utilities

- [ ] Create `shared/parquet_utils.py` and `shared/data_utils.py`
- [ ] Move parquet and aggregation functions from attestation_packing
- [ ] Update imports and test data loading functionality
- Dependencies: Completion of Phase 1

### Phase 3: Extract UI Components

- [ ] Create `shared/ui_components.py` with styling and branding
- [ ] Move UI functions and CSS from attestation_packing
- [ ] Update imports and test UI consistency
- Dependencies: Completion of Phase 2

### Phase 4: Final Integration and Testing

- [ ] Create `shared/__init__.py` with convenient imports
- [ ] Perform comprehensive testing of all functionality
- [ ] Validate no functionality regression in attestation_packing
- [ ] Document the shared module architecture
- Dependencies: Completion of Phase 3

## Expected Outcomes

- **Modular architecture**: 5 focused shared modules containing all generic functionality
- **Zero duplication**: No duplicate functions across the codebase
- **Preserved functionality**: 100% identical behavior for attestation packing analysis
- **Reusable infrastructure**: Future analysis pages can easily use shared utilities
- **Cleaner codebase**: Attestation_packing directory contains only domain-specific logic

### Success Metrics

- **Function extraction**: 8+ functions moved to shared modules
- **File size reduction**: Attestation_packing files reduced by 30-50% (generic code removed)
- **Import clarity**: Clean, logical import statements throughout
- **Reusability**: Shared modules can be imported by any future analysis page
- **Performance preservation**: No degradation in loading times or responsiveness