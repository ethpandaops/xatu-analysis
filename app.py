"""
ethPandaOps Analysis Dashboard
Main application entry point using modern Streamlit st.navigation API
"""
import streamlit as st
import dotenv

# Load environment variables
dotenv.load_dotenv()

# Initialize configuration system
from shared.config_loader import config_loader

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

block_producer_performance_page = st.Page(
    "pages/analysis/block_producer_performance/page.py",
    title="Block Producer Performance",
    icon="🏗️",
    url_path="block-producer-performance"
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

peerdas_analysis_page = st.Page(
    "pages/analysis/peerdas_analysis/page.py",
    title="PeerDAS Analysis",
    icon="🔮",
    url_path="peerdas-analysis"
)

peerdas_analysis_v2_page = st.Page(
    "pages/analysis/peerdas_analysis_v2/page.py",
    title="Head Correctness",
    icon="🎯",
    url_path="head-correctness"
)

gossipsub_monitoring_page = st.Page(
    "pages/analysis/gossipsub_monitoring/page.py",
    title="Gossipsub Monitoring",
    icon="🌐",
    url_path="gossipsub-monitoring"
)

reorgs_page = st.Page(
    "pages/analysis/reorgs/page.py",
    title="Chain Reorgs",
    icon="🔄",
    url_path="reorgs"
)

reorg_rates_page = st.Page(
    "pages/analysis/reorg_rates/page.py",
    title="Reorg Rates",
    icon="📈",
    url_path="reorg-rates"
)

blob_mempool_analysis_page = st.Page(
    "pages/analysis/blob_mempool_analysis/page.py",
    title="Blob Mempool Analysis",
    icon="🧊",
    url_path="blob-mempool-analysis"
)

blob_propagation_analysis_page = st.Page(
    "pages/analysis/blob_propagation/page.py",
    title="Blob Propagation Analysis",
    icon="🔗",
    url_path="blob-propagation-analysis"
)

# Configure navigation with sections
navigation = st.navigation({
    "Main": [home_page],
    "Analysis": [block_producer_performance_page, multi_metric_analysis_page, attestation_cdf_page, validator_performance_page, peerdas_analysis_page, peerdas_analysis_v2_page, gossipsub_monitoring_page, reorgs_page, reorg_rates_page, blob_mempool_analysis_page, blob_propagation_analysis_page]
})

# Run the selected page
navigation.run()