# Xatu Analysis Dashboard

A Streamlit-based data analysis dashboard for Ethereum data using Xatu.

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager

### Installation & Running

1. Clone the repository:
```bash
git clone https://github.com/ethpandaops/xatu-analysis.git
cd xatu-analysis
```

2. Set up environment:
```bash
cp example.env .env
# Edit .env with your configuration
```

3. Run the dashboard:
```bash
# Option 1: Using the launch script
./launch_dashboard.sh

# Option 2: Using uv directly
uv sync
uv run streamlit run app.py --server.port=8502 --server.address=0.0.0.0
```

The dashboard will be available at `http://localhost:8502`

## Configuration

Copy `example.env` to `.env` and configure your ClickHouse connection and other settings.

## Development

```bash
# Install dependencies
uv sync

# Run in development mode
uv run streamlit run app.py

# Add new dependencies
uv add package-name
```

## License

MIT License - see LICENSE file for details.
