import streamlit as st
import pandas as pd
import numpy as np
import os
import requests
import hashlib
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from pathlib import Path
import dotenv


from shared.database import get_database_connection
from shared.filesystem import get_cache_dir

from shared.parquet_utils import calculate_parquet_urls, download_and_cache_parquet

# Import Ethereum-specific functions from shared modules
from shared.ethereum.validators import load_blockprint_clients, load_validators_from_ethseer
from shared.ethereum.blocks import fetch_proposer_indices, fetch_proposer_indices_parquet
from shared.ethereum.attestations import load_attestation_data, load_attestation_data_parquet

