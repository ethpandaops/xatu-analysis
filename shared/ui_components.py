"""
UI components and styling for EthPandaOps Analysis Dashboard
"""
import streamlit as st


def add_ethpandaops_logo(fig):
    """Add EthPandaOps logo to a plotly figure."""
    # Logo functionality disabled
    return fig


def apply_ethpandaops_styling():
    """Apply consistent EthPandaOps styling to Streamlit app."""
    st.markdown("""
    <style>
        
        /* Main header styling */
        .main-header {
            text-align: center;
            color: #1e40af;
            border-bottom: 3px solid #3b82f6;
            padding-bottom: 1rem;
            margin-bottom: 2rem;
        }
        
        /* Metric cards */
        .metric-card {
            background: #f8fafc;
            padding: 1.5rem;
            border-radius: 10px;
            border: 1px solid #e2e8f0;
            margin: 0.5rem 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        /* Metric description box */
        .metric-description {
            background: #eff6ff;
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
            border-left: 4px solid #3b82f6;
        }
        
        .metric-title {
            font-size: 1.2rem;
            font-weight: 600;
            color: #1e40af;
            margin-bottom: 0.5rem;
        }
        
        .metric-subtitle {
            color: #475569;
            line-height: 1.5;
        }
    </style>
    """, unsafe_allow_html=True)
