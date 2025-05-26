# Create New Analysis Page

This command provides instructions to create a new analysis page following the established architecture pattern in the xatu-analysis repo. Your instructions will be coming next. Read these instructions carefully, do nothing, and then wait for the user to provide the details about the new page.

## Before You Begin

**IMPORTANT: Ask the user questions before proceeding if it's not clear from the prompt:**

1. **Analysis Topic**: What is the analysis about? (e.g., "block_rewards", "validator_performance", "network_latency")
2. **Page Title**: What should the page title be? (e.g., "Block Rewards Analysis", "Validator Performance Dashboard")
3. **Data Source**: What data will this analyze?
   - Database tables/views?
   - Parquet files?
   - External APIs?
   - Combination of sources?
4. **Key Metrics**: What are the main metrics to calculate and display? (e.g., "average_reward", "total_validators", "performance_score")
5. **Visualization Types**: What types of plots/charts are needed?
   - Time series?
   - Before/after comparisons?
   - Distribution plots?
   - Custom visualizations?
6. **Grouping Options**: How should data be grouped for analysis?
   - By client type?
   - By entity/validator?
   - By time period?
   - Other grouping options?
7. **Configuration Parameters**: What user-configurable options should be available?
   - Time ranges?
   - Network selection?
   - Filtering options?

## Architecture Overview

The page will follow this established structure:

```
pages/analysis/{analysis_name}/
├── page.py                    # Entry point (minimal, imports dashboard)
├── interactive_dashboard.py   # Main dashboard logic and UI
├── config_utils.py           # Metric definitions and configurations
├── data_loaders.py           # Data fetching and loading functions
├── metrics_calculators.py    # Business logic for calculating metrics
├── plot_generators.py        # Visualization creation functions
└── requirements.txt          # Page-specific dependencies (if any)
```

## Implementation Steps

1. **Create Directory Structure**
   - Create `pages/analysis/{analysis_name}/` directory
   - Create all required Python files

2. **Implement Core Components**
   - `page.py`: Simple entry point that imports and runs the dashboard
   - `config_utils.py`: Define metric information and configuration helpers
   - `data_loaders.py`: Implement data loading functions
   - `metrics_calculators.py`: Implement business logic for metric calculations
   - `plot_generators.py`: Create visualization functions
   - `interactive_dashboard.py`: Build the main dashboard UI and logic

3. **Follow These Patterns**

### page.py Template:
```python
# pages/analysis/{analysis_name}/page.py
import streamlit as st
import sys
import os

# Add current directory to path for relative imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Import the main dashboard
from interactive_dashboard import main as run_dashboard

# Run the dashboard
run_dashboard()
```

### config_utils.py Template:
```python
"""
Configuration utilities for {analysis_name} analysis
"""
import streamlit as st

def get_metric_info(metric_name):
    """Get human-readable title and description for metrics."""
    metric_info = {
        "example_metric": {
            "title": "Example Metric",
            "subtitle": "Description of what this metric measures and why it's important."
        },
        # Add all your metrics here
    }
    
    return metric_info.get(metric_name, {
        "title": metric_name.replace('_', ' ').title(),
        "subtitle": "No description available for this metric."
    })
```

### data_loaders.py Template:
```python
"""
Data loading functions for {analysis_name} analysis

IMPORTANT: Before implementing new data loading functions:
1. Check shared/database.py for existing database utilities
2. Check shared/parquet_utils.py for parquet file handling
3. Check shared/ethereum/ for Ethereum-specific data loading
4. Check shared/data_utils.py for common data processing functions

If you need new functionality that could be reusable:
- Add it to the appropriate shared/ module instead of here
- This file should primarily compose existing shared functions
"""
import streamlit as st
import pandas as pd
import numpy as np

# Import existing shared data loading functionality
from shared.database import get_database_connection
from shared.parquet_utils import calculate_parquet_urls, download_and_cache_parquet
from shared.ethereum.validators import load_blockprint_clients, load_validators_from_ethseer
from shared.ethereum.blocks import fetch_proposer_indices, fetch_proposer_indices_parquet
from shared.ethereum.attestations import load_attestation_data, load_attestation_data_parquet
# Import other shared utilities as needed

def load_analysis_data(start_time, end_time, network="mainnet"):
    """
    Load and return the main dataset for analysis.
    
    PATTERN: This function should primarily compose existing shared functions.
    If you need new database queries or data processing that could be reusable,
    add them to shared/ modules instead.
    
    Args:
        start_time: Start timestamp
        end_time: End timestamp  
        network: Network name (mainnet, holesky, etc.)
    
    Returns:
        pd.DataFrame: Loaded data
    """
    # Example pattern - compose existing shared functions:
    # conn = get_database_connection()
    # data = some_shared_function(conn, start_time, end_time, network)
    # return data
    pass

# Only add page-specific data loading functions here if they truly cannot be generalized
# Most data loading should use or extend shared/ functionality
```

### metrics_calculators.py Template:
```python
"""
Metrics calculation functions for {analysis_name} analysis

IMPORTANT: Before implementing new metric calculations:
1. Check shared/data_utils.py for existing data processing utilities
2. Check other analysis pages for similar metric calculations that could be generalized
3. If creating reusable metric calculations, consider adding them to shared/

This file should contain analysis-specific business logic that cannot be generalized.
"""
import pandas as pd
import numpy as np
from shared.data_utils import get_aggregate_function  # Example of using shared utilities

def calculate_primary_metrics(df):
    """
    Calculate the main metrics for the analysis.
    
    Args:
        df: Input dataframe
        
    Returns:
        dict: Dictionary of calculated metrics
    """
    # Implement your analysis-specific metrics calculation logic here
    pass

def calculate_grouped_metrics(group):
    """Calculate metrics for a grouped dataset."""
    # Implement grouped calculation logic
    # Use shared utilities where possible
    pass

# Only add functions here that are truly specific to this analysis
# For reusable calculations, extend shared/ modules instead
```

### plot_generators.py Template:
```python
"""
Visualization functions for {analysis_name} analysis

IMPORTANT: Leverage existing shared plotting patterns:
1. Always use shared.ui_components.add_ethpandaops_logo() for consistent branding
2. Check other analysis pages for similar plot types that could be generalized
3. For reusable plotting utilities, consider adding them to shared/ui_components.py
4. Follow established patterns for plot styling and layout

This file should contain analysis-specific visualization logic.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from shared.ui_components import add_ethpandaops_logo  # Always use for consistent branding
from config_utils import get_metric_info

def create_time_series_plot(data, metric, groups, **kwargs):
    """Create a time series visualization."""
    metric_info = get_metric_info(metric)
    
    # Follow established patterns from other analysis pages
    fig = px.line(
        data, 
        x='datetime', 
        y=metric,
        title=f'{metric_info["title"]} - Time Series<br><sub>{metric_info["subtitle"]}</sub>',
        labels={'datetime': 'Date/Time', metric: metric_info["title"]}
    )
    
    # Standard layout updates
    fig.update_layout(
        height=500,
        title={'font': {'size': 16}}
    )
    
    # Always add branding
    return add_ethpandaops_logo(fig)

def create_comparison_plot(data, metric, groups, **kwargs):
    """Create a comparison visualization."""
    # Implement comparison plotting logic following established patterns
    # Use consistent color schemes: {'Before': '#1f77b4', 'After': '#2ca02c'}
    pass

# Only add analysis-specific plotting functions here
# For reusable plot utilities, extend shared/ui_components.py instead
```

### interactive_dashboard.py Template:
```python
"""
Interactive {analysis_name} Analysis Dashboard
"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Import components
from config_utils import get_metric_info
from data_loaders import load_analysis_data
from metrics_calculators import calculate_primary_metrics
from plot_generators import create_time_series_plot, create_comparison_plot

# Import shared components
from shared.ui_components import apply_ethpandaops_styling

def main():
    # Apply consistent styling
    apply_ethpandaops_styling()
    
    # Initialize session state
    if 'data_loaded' not in st.session_state:
        st.session_state.data_loaded = False
    
    # Header
    st.markdown('<h1 class="main-header">📊 {Page Title}</h1>', unsafe_allow_html=True)
    
    # Sidebar configuration
    st.sidebar.header("⚙️ Configuration")
    
    # Add your configuration UI here
    network = st.sidebar.selectbox("Select Network", ["mainnet", "holesky", "sepolia"])
    
    # Data loading section
    if st.sidebar.button("Load Data"):
        # Implement data loading logic
        pass
    
    # Main dashboard content
    if st.session_state.data_loaded:
        # Display your analysis dashboard
        pass
    else:
        st.info("Configure parameters and click 'Load Data' to begin analysis.")

if __name__ == "__main__":
    main()
```

## Key Principles

1. **Leverage Existing Shared Functionality**: Always check `shared/` modules first before implementing new data loading, processing, or UI components
2. **Contribute to Shared**: If you need new functionality that could be reusable across pages, add it to the appropriate `shared/` module instead of the page-specific files
3. **Separation of Concerns**: Each file has a single responsibility
4. **Minimal Page-Specific Code**: Page-specific files should primarily compose and configure shared functionality
5. **Consistency**: Follow established patterns for UI, naming, and structure
6. **Error Handling**: Include proper error handling and user feedback
7. **Documentation**: Add clear docstrings and comments
8. **Configuration**: Make the analysis configurable through the UI

## Shared Components to Leverage

- `shared/ui_components.py`: Styling and branding
- `shared/data_utils.py`: Common data processing utilities  
- `shared/database.py`: Database connection management
- `shared/parquet_utils.py`: Parquet file handling
- `shared/ethereum/`: Ethereum-specific data loading functions

## Testing

After implementation:
1. Test data loading with different parameters
2. Verify all visualizations render correctly
3. Test error handling with invalid inputs
4. Ensure UI responsiveness and usability

## Integration

Add the new page to the main navigation by updating the appropriate navigation configuration file.