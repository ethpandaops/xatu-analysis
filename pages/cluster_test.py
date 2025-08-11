"""
Test page for multi-cluster support.
This page demonstrates how to use the new multi-cluster configuration system.
"""
import streamlit as st
import pandas as pd
from shared.header import render_global_header, get_global_cluster, get_global_network
from shared.ui_utils import get_cluster_info
from shared.database import get_database_connection
from shared.config_loader import config_loader


def main():
    # Render the global header
    render_global_header()
    
    st.title("Multi-Cluster Configuration Test")
    
    st.markdown("""
    This page tests the new multi-cluster support system. You can:
    - Select different ClickHouse clusters
    - View discovered networks from each cluster
    - Test cluster connections
    - Query data from different clusters
    """)
    
    # Get global selections from header
    selected_cluster = get_global_cluster()
    selected_network = get_global_network()
    
    if selected_cluster:
        # Show cluster info
        with st.expander("Cluster Information", expanded=True):
            cluster_info = get_cluster_info(selected_cluster)
            
            col1, col2 = st.columns(2)
            with col1:
                st.write("**Host:**", cluster_info.get('host', 'N/A'))
                st.write("**Port:**", cluster_info.get('port', 'N/A'))
                st.write("**Database:**", cluster_info.get('database', 'N/A'))
            with col2:
                st.write("**Protocol:**", cluster_info.get('protocol', 'N/A'))
                st.write("**Description:**", cluster_info.get('description', 'N/A'))
                st.write("**Has Credentials:**", "✅" if cluster_info.get('has_credentials') else "❌")
        
        # Test connection button
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("Test Connection", key="test_conn"):
                with st.spinner(f"Testing connection to {selected_cluster}..."):
                    from shared.header import test_cluster_connection
                    if test_cluster_connection(selected_cluster):
                        st.success(f"✅ Successfully connected to {selected_cluster}")
                    else:
                        st.error(f"❌ Failed to connect to {selected_cluster}")
        
        with col2:
            if st.button("Reload Config", key="reload_config"):
                config_loader.reload_config()
                st.success("Configuration reloaded")
                st.rerun()
        
        # Network info
        st.divider()
        
        if selected_network:
            st.write(f"**Selected Network:** {selected_network}")
            
            # Show network config
            with st.expander("Network Configuration"):
                network_config = config_loader.get_network_config(selected_network)
                st.json(network_config)
        
        # Sample query section
        st.divider()
        st.subheader("Sample Query")
        
        query_type = st.selectbox(
            "Select a sample query",
            ["Network Discovery", "Recent Blocks", "Recent Attestations", "Custom Query"]
        )
        
        if query_type == "Network Discovery":
            query = """
                SELECT DISTINCT meta_network_name, COUNT(*) as count
                FROM canonical_beacon_block FINAL
                WHERE slot_start_date_time >= now() - INTERVAL 7 DAY
                AND meta_network_name != ''
                GROUP BY meta_network_name
                ORDER BY count DESC
            """
        elif query_type == "Recent Blocks":
            query = f"""
                SELECT slot, epoch, proposer_index, slot_start_date_time
                FROM canonical_beacon_block FINAL
                WHERE meta_network_name = '{selected_network}'
                ORDER BY slot DESC
                LIMIT 10
            """
        elif query_type == "Recent Attestations":
            query = f"""
                SELECT slot, committee_index, aggregation_bits_count, slot_start_date_time
                FROM canonical_beacon_attestation FINAL
                WHERE meta_network_name = '{selected_network}'
                ORDER BY slot DESC
                LIMIT 10
            """
        else:
            query = st.text_area("Enter your custom query", height=150)
        
        if query_type != "Custom Query":
            st.code(query, language="sql")
        
        if st.button("Execute Query"):
            try:
                conn = get_database_connection(selected_cluster)
                if conn:
                    with st.spinner("Executing query..."):
                        df = pd.read_sql(query, conn)
                        conn.close()
                        
                        st.success(f"Query returned {len(df)} rows")
                        st.dataframe(df)
            except Exception as e:
                st.error(f"Query failed: {e}")
        
        # Show all available clusters
        st.divider()
        st.subheader("All Configured Clusters")
        
        clusters = config_loader.get_clickhouse_clusters()
        cluster_data = []
        for name, config in clusters.items():
            cluster_data.append({
                'Name': name,
                'Host': config.get('host'),
                'Port': config.get('port'),
                'Database': config.get('database'),
                'Description': config.get('description', ''),
                'Default': '✅' if name == config_loader._config.get('clickhouse', {}).get('default_cluster') else ''
            })
        
        if cluster_data:
            st.dataframe(pd.DataFrame(cluster_data), use_container_width=True)
        
        # Show all discovered networks
        st.divider()
        st.subheader("All Available Networks")
        
        networks = config_loader.get_networks()
        network_data = []
        for name, config in networks.items():
            network_data.append({
                'Name': name,
                'Display Name': config.get('name', name.title()),
                'Chain ID': config.get('chain_id', 'N/A'),
                'Description': config.get('description', ''),
                'Has Gas Data': '✅' if config.get('has_gas_data') else '❌',
                'Has Blob Data': '✅' if config.get('has_blob_data') else '❌',
                'Source': 'Discovered' if config.get('discovered') else 'Config'
            })
        
        if network_data:
            st.dataframe(pd.DataFrame(network_data), use_container_width=True)


if __name__ == "__main__":
    main()