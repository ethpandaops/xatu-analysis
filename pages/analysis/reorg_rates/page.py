# pages/analysis/reorg_rates/page.py
import streamlit as st
import sys
import os
import importlib.util
from contextlib import contextmanager

@contextmanager
def isolated_import_context(directory_path, clear_cache=True):
    """Context manager for completely isolated imports with cache clearing."""
    original_path = sys.path[:]
    modules_to_clean = []
    
    try:
        # Clear any cached modules that might conflict
        if clear_cache:
            conflicting_modules = [
                'loader', 'plot_generators', 'interactive_dashboard', 'queries'
            ]
            for module_name in conflicting_modules:
                if module_name in sys.modules:
                    modules_to_clean.append((module_name, sys.modules[module_name]))
                    del sys.modules[module_name]
        
        # Set up isolated path
        sys.path = [directory_path] + [p for p in original_path if p != directory_path]
        yield
        
    finally:
        # Restore original sys.path
        sys.path[:] = original_path
        
        # Clean up any modules we imported
        if clear_cache:
            for module_name in conflicting_modules:
                if module_name in sys.modules:
                    del sys.modules[module_name]
            
            # Restore original modules if they existed
            for module_name, original_module in modules_to_clean:
                sys.modules[module_name] = original_module

# Get current directory
current_dir = os.path.dirname(os.path.abspath(__file__))
dashboard_path = os.path.join(current_dir, "interactive_dashboard.py")

try:
    # Use completely isolated import context
    with isolated_import_context(current_dir):
        # Load the module directly by file path with unique name
        module_name = f"reorg_rates_dashboard_{id(current_dir)}"
        spec = importlib.util.spec_from_file_location(module_name, dashboard_path)
        dashboard_module = importlib.util.module_from_spec(spec)
        
        # Execute the module within the isolated context
        spec.loader.exec_module(dashboard_module)
        
        # Run the dashboard
        dashboard_module.main()
    
except ImportError as e:
    st.error(f"Failed to load Reorg Rates dashboard: {e}")
    st.info("Please ensure all required dependencies are installed.")
    st.code(f"Current directory: {current_dir}")
    st.code(f"Dashboard path: {dashboard_path}")
    st.code(f"Path exists: {os.path.exists(dashboard_path)}")
except Exception as e:
    st.error(f"Error running Reorg Rates dashboard: {e}")
    import traceback
    st.code(traceback.format_exc())