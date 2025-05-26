#!/bin/bash
set -e

echo "🐼 ethPandaOps Analysis Dashboard"
echo "================================="

# Install dependencies using uv
echo "📦 Installing dependencies with uv..."
uv sync

# Validate environment file
if [ ! -f .env ]; then
    echo "❌ .env file not found. Please copy example.env to .env and configure."
    exit 1
fi

echo "✅ Starting Analysis Dashboard..."
uv run streamlit run app.py --server.port=8502 --server.address=0.0.0.0