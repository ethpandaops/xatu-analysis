"""Admin page for cluster configuration testing."""
import streamlit as st
import pandas as pd
from shared.header import render_global_header, get_global_cluster, get_global_network
from shared.database import get_database_connection
from shared.config_loader import config_loader


def main():
    render_global_header()
    
    st.title("Cluster Admin")
    
    selected_cluster = get_global_cluster()
    selected_network = get_global_network()
    
    if not selected_cluster:
        st.error("No cluster selected")
        return
    
    # Quick test query
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Test Query", type="primary"):
            try:
                conn = get_database_connection(selected_cluster)
                if conn:
                    result = pd.read_sql(f"SELECT COUNT(*) as count FROM canonical_beacon_block FINAL WHERE meta_network_name = '{selected_network}' AND slot_start_date_time >= now() - INTERVAL 1 DAY", conn)
                    conn.close()
                    st.metric("Blocks (24h)", f"{result['count'][0]:,}")
            except Exception as e:
                st.error(f"Failed: {e}")
    
    # Custom query
    with st.expander("Custom Query"):
        query = st.text_area("SQL", height=100, label_visibility="collapsed")
        if st.button("Run") and query:
            try:
                conn = get_database_connection(selected_cluster)
                df = pd.read_sql(query, conn)
                conn.close()
                st.dataframe(df, use_container_width=True)
            except Exception as e:
                st.error(str(e))
    
    # Config tables
    tab1, tab2 = st.tabs(["Clusters", "Networks"])
    
    with tab1:
        clusters = config_loader.get_clickhouse_clusters()
        cluster_df = pd.DataFrame([
            {'Cluster': name, 'Host': c['host'], 'Port': c['port']}
            for name, c in clusters.items()
        ])
        st.dataframe(cluster_df, use_container_width=True, hide_index=True)
    
    with tab2:
        networks = config_loader.get_networks()
        network_df = pd.DataFrame([
            {'Network': name, 'Type': 'Discovered' if n.get('discovered') else 'Config'}
            for name, n in networks.items()
        ])
        st.dataframe(network_df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()