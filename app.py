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
    icon="📦",
    url_path="attestation-packing"
)

multi_metric_analysis_page = st.Page(
    "pages/analysis/multi_metric_analysis/page.py",
    title="Multi-Metric Analysis",
    icon="📊",
    url_path="multi-metric-analysis"
)

attestation_cdf_page = st.Page(
    "pages/analysis/attestation_cdf/page.py",
    title="Attestation CDF Analysis",
    icon="📊",
    url_path="attestation-cdf"
)

validator_performance_page = st.Page(
    "pages/analysis/validator_performance/page.py",
    title="Validator Performance",
    icon="📊",
    url_path="validator-performance"
)

# Configure navigation with sections
navigation = st.navigation({
    "Main": [home_page],
    "Analysis": [attestation_packing_page, multi_metric_analysis_page, attestation_cdf_page, validator_performance_page]
})

# Run the selected page
navigation.run()