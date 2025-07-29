# pages/analysis/gas_usage_performance/page.py
import streamlit as st
import sys
import os
import importlib.util

# Get current directory
current_dir = os.path.dirname(os.path.abspath(__file__))

# Load the interactive dashboard module directly from file path
dashboard_path = os.path.join(current_dir, "interactive_dashboard.py")

try:
    # Load the module directly by file path to avoid import conflicts
    spec = importlib.util.spec_from_file_location("gas_usage_dashboard", dashboard_path)
    dashboard_module = importlib.util.module_from_spec(spec)
    
    # Add current directory to path for the dashboard's imports
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    
    # Execute the module
    spec.loader.exec_module(dashboard_module)
    
    # Run the dashboard
    dashboard_module.main()
    
except ImportError as e:
    st.error(f"Failed to load Multi-Metric Performance Analysis dashboard: {e}")
    st.info("Please ensure all required dependencies are installed.")
    st.code(f"Current directory: {current_dir}")
    st.code(f"Dashboard path: {dashboard_path}")
    st.code(f"Path exists: {os.path.exists(dashboard_path)}")
except Exception as e:
    st.error(f"Error running Multi-Metric Performance Analysis dashboard: {e}")
    import traceback
    st.code(traceback.format_exc())