# pages/analysis/multi_metric_analysis/page.py
import streamlit as st
import sys
import os

# Get current directory and add it to sys.path so imports work
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Import the dashboard module
try:
    # Import with the directory in path
    from interactive_dashboard import main

    # Run the dashboard
    main()

except ImportError as e:
    import traceback
    st.code(traceback.format_exc())
except Exception as e:
    st.error(f"Error running Multi-Metric Performance Analysis dashboard: {e}")
    import traceback
    st.code(traceback.format_exc())