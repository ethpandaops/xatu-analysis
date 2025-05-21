import os
from typing import Dict, Any
from pathlib import Path
import json
from dotenv import load_dotenv


def load_config() -> Dict[str, Any]:
    load_dotenv()
    
    config = {
        "clickhouse": {
            "host": os.getenv("CLICKHOUSE_HOST", "localhost"),
            "port": int(os.getenv("CLICKHOUSE_PORT", "8123")),
            "username": os.getenv("CLICKHOUSE_USERNAME", "default"),
            "password": os.getenv("CLICKHOUSE_PASSWORD", ""),
            "database": os.getenv("CLICKHOUSE_DATABASE", "default"),
        },
        "parquet": {
            "base_path": os.getenv("PARQUET_BASE_PATH", "./data"),
        },
    }
    
    # Try to load from config file if it exists
    config_file = Path("config.json")
    if config_file.exists():
        with open(config_file) as f:
            file_config = json.load(f)
            config.update(file_config)
    
    return config
