# pages/analysis/attestation_packing/page.py
import streamlit as st
import sys
import os

# Add current directory to path for relative imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Import the original interactive dashboard and run it directly
# This preserves 100% of the existing functionality
from interactive_dashboard import main as run_dashboard

# Page title will be handled by st.navigation, but we can add subtitle
st.markdown("*Interactive analysis of Ethereum attestation packing metrics across networks, time periods, and consensus clients.*")

# Run the original dashboard logic unchanged
run_dashboard()