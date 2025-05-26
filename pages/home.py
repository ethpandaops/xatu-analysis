"""
EthPandaOps Analysis Dashboard - Home Page
"""
import streamlit as st

st.title("🐼 EthPandaOps Analysis Dashboard")

st.markdown("""
Welcome to the EthPandaOps Analysis Dashboard! This interactive platform provides 
comprehensive tools for analyzing Ethereum network data and validator behavior.
""")

st.subheader("📈 Available Analyses")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("""
    ### 📦 Attestation Packing
    Analyze attestation packing efficiency, inclusion delays, and validator behavior 
    across different networks and consensus clients.
    
    **Features:**
    - Multi-network support (mainnet, holesky, sepolia)
    - Before/after Electra fork analysis
    - Consensus client and entity grouping
    - Interactive visualizations
    """)
    
    if st.button("Open Attestation Packing →", key="home_att_pack"):
        st.switch_page("pages/analysis/attestation_packing/page.py")

with col2:
    st.markdown("""
    ### 🔗 More Analyses
    Additional analysis tools will be added here as they become available.
    
    **Coming Soon:**
    - Validator performance analysis
    - Network consensus metrics
    - Beacon chain statistics
    """)

with col3:
    st.markdown("""
    ### 📚 Resources
    - [EthPandaOps Website](https://ethpandaops.io)
    - [Xatu Documentation](https://github.com/ethpandaops/xatu)
    - [Analysis Blog Posts](https://ethpandaops.io/posts)
    
    ### 🛠 Technical Info
    - Built with Streamlit
    - Data from Xatu network
    - Real-time analysis capabilities
    """)

# Footer with additional information
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666; font-size: 0.9em;">
    <p>EthPandaOps Analysis Dashboard | Built with ❤️ for the Ethereum community</p>
</div>
""", unsafe_allow_html=True)