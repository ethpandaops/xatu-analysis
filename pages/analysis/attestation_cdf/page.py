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