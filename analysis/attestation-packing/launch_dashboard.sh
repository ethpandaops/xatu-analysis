#!/bin/bash

# Launch script for the Interactive Attestation Packing Analysis Dashboard

echo "🚀 Starting Attestation Packing Analysis Dashboard..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo "Please create a .env file with your ClickHouse credentials:"
    echo ""
    echo "XATU_CLICKHOUSE_USERNAME=your_username"
    echo "XATU_CLICKHOUSE_PASSWORD=your_password"
    echo "XATU_CLICKHOUSE_HOST=your_host"
    echo ""
    exit 1
fi

# Check if Python requirements are installed
echo "📦 Checking Python dependencies..."
python3 -c "import streamlit, pandas, plotly" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "📥 Installing Python dependencies..."
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "❌ Failed to install dependencies!"
        echo "Please run: pip install -r requirements.txt"
        exit 1
    fi
fi

echo "✅ Dependencies ready!"
echo ""
echo "🌐 Starting Streamlit dashboard..."
echo "Dashboard will open in your browser at: http://localhost:8501"
echo ""
echo "💡 Usage Tips:"
echo "   1. Configure network and time range in the sidebar"
echo "   2. Click 'Load Data' to fetch from ClickHouse"
echo "   3. Select clients and metrics to analyze"
echo "   4. Choose visualization type and explore!"
echo ""
echo "Press Ctrl+C to stop the dashboard"
echo ""

# Launch the Streamlit app
streamlit run interactive_dashboard.py