# pages/analysis/peerdas_analysis_v2/page.py
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
    st.error(f"Failed to load PeerDAS Analysis V2 dashboard: {e}")
    st.info("Please ensure all required dependencies are installed.")
    st.code(f"Current directory: {current_dir}")
    st.code(f"Dashboard path: {os.path.join(current_dir, 'interactive_dashboard.py')}")
    st.code(f"Path exists: {os.path.exists(os.path.join(current_dir, 'interactive_dashboard.py'))}")
    import traceback
    st.code(traceback.format_exc())
except Exception as e:
    st.error(f"Error running PeerDAS Analysis V2 dashboard: {e}")
    import traceback
    st.code(traceback.format_exc())