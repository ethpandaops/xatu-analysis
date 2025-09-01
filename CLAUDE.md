# Xatu Analysis Dashboard

A Streamlit-based data analysis dashboard for Ethereum data using Xatu. This project provides modular analysis tools for Ethereum blockchain data, with support for ClickHouse databases and Parquet file processing.

## Rules
- Use Polars for all data processing.
- Use Streamlit for all UI. Convert to Pandas at the edge where required to work with Streamlit.
- NEVER run streamlit yourself. I'll do it.