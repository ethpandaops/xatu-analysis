"""
ethPandaOps Analysis Dashboard
Main application entry point using modern Streamlit st.navigation API
"""
import streamlit as st

st.set_page_config(
    page_title="ethPandaOps Analysis Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Define pages using st.Page
home_page = st.Page(
    "pages/home.py", 
    title="Home", 
    icon="🏠",
    default=True
)

attestation_packing_page = st.Page(
    "pages/analysis/attestation_packing/page.py",
    title="Attestation Packing",
    icon="📦"
)

# Configure navigation with sections
navigation = st.navigation({
    "Main": [home_page],
    "Analysis": [attestation_packing_page]
})

# Run the selected page
navigation.run()