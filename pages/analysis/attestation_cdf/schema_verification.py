import streamlit as st
import sys
import os

# Add current directory to path for relative imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Add parent directories for shared imports
sys.path.append(os.path.join(current_dir, '../../..'))

from shared.database import get_database_connection

def check_table_schemas(network="mainnet"):
    """Check actual table schemas and available columns."""
    
    conn = get_database_connection(network)
    
    tables_to_check = [
        "mev_relay_proposer_payload_delivered",
        "libp2p_gossipsub_beacon_attestation", 
        "beacon_api_eth_v1_events_attestation",
        "beacon_api_eth_v1_events_block",
        "beacon_api_eth_v2_beacon_block",
        "canonical_beacon_block"
    ]
    
    schema_info = {}
    
    for table in tables_to_check:
        try:
            # Get table structure
            describe_query = f"DESCRIBE {table}"
            columns = conn.execute(describe_query).fetchall()
            
            schema_info[table] = {
                "exists": True,
                "columns": [{"name": col[0], "type": col[1]} for col in columns],
                "column_names": [col[0] for col in columns]
            }
            
        except Exception as e:
            schema_info[table] = {
                "exists": False,
                "error": str(e)
            }
    
    return schema_info

if __name__ == "__main__":
    st.title("Xatu Database Schema Verification")
    
    if st.button("Check Schemas"):
        with st.spinner("Checking database schemas..."):
            schemas = check_table_schemas()
            
            for table_name, info in schemas.items():
                st.subheader(f"Table: {table_name}")
                
                if info["exists"]:
                    st.success("✅ Table exists")
                    
                    # Show columns in a nice format
                    st.write("**Columns:**")
                    for col in info["columns"]:
                        st.write(f"- `{col['name']}`: {col['type']}")
                        
                    # Show just column names for easy copying
                    st.write("**Column Names (for queries):**")
                    st.code(", ".join(info["column_names"]))
                    
                else:
                    st.error(f"❌ Table not found: {info['error']}")
                    
                st.divider()