"""
ethPandaOps Analysis Dashboard - Home Page
"""
import streamlit as st
from shared.header import render_global_header

# Render the global header with cluster/network selection
render_global_header()

st.title("🐼 ethPandaOps Analysis Dashboard")

st.markdown("""
Welcome to the ethPandaOps Analysis Dashboard! This interactive platform provides 
comprehensive tools for analyzing Ethereum network data and validator behavior.
""")

col1, col2 = st.columns(2)


with col1:
    st.markdown("""
    ### 📚 Resources
    - [ethPandaOps Website](https://ethPandaOps.io)
    - [Xatu Documentation](https://github.com/ethPandaOps/xatu)
    - [Analysis Blog Posts](https://ethPandaOps.io/posts)
    
    ### 🛠 Technical Info
    - Built with Streamlit
    - Data from Xatu network
    - Real-time analysis capabilities
    """)
