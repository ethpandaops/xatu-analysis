#!/bin/bash
set -e

echo "🐼 EthPandaOps Analysis Dashboard"
echo "================================="

# Check Python dependencies
if ! python -c "import streamlit, pandas, plotly" 2>/dev/null; then
    echo "❌ Missing required dependencies. Installing..."
    pip install -r requirements.txt
fi

# Validate environment file
if [ ! -f .env ]; then
    echo "❌ .env file not found. Please copy example.env to .env and configure."
    exit 1
fi

echo "✅ Starting Analysis Dashboard..."
streamlit run app.py --server.port=8502 --server.address=0.0.0.0