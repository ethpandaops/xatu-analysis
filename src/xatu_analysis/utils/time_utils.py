from datetime import datetime
from typing import Union
import pandas as pd


def to_timestamp(dt: Union[str, datetime, pd.Timestamp]) -> int:
    if isinstance(dt, str):
        dt = pd.to_datetime(dt)
    elif isinstance(dt, datetime):
        dt = pd.Timestamp(dt)
    
    return int(dt.timestamp())


def from_timestamp(ts: Union[int, float]) -> pd.Timestamp:
    return pd.Timestamp.fromtimestamp(ts)


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        return f"{seconds/60:.2f}m"
    else:
        return f"{seconds/3600:.2f}h"


def time_range_to_filter(start_time: str, end_time: str) -> str:
    return f"event_date_time BETWEEN '{start_time}' AND '{end_time}'"
