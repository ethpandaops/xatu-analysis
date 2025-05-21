import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path
from typing import Optional, List, Union


class ParquetConnector:
    def __init__(self, base_path: Optional[Union[str, Path]] = None):
        self.base_path = Path(base_path) if base_path else Path("./data")
        self.base_path.mkdir(exist_ok=True)

    def read_parquet(self, file_path: Union[str, Path]) -> pd.DataFrame:
        if not Path(file_path).is_absolute():
            file_path = self.base_path / file_path
        
        return pd.read_parquet(file_path)

    def write_parquet(self, df: pd.DataFrame, file_path: Union[str, Path]) -> None:
        if not Path(file_path).is_absolute():
            file_path = self.base_path / file_path
        
        file_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(file_path, index=False)

    def read_multiple_parquet(self, pattern: str) -> pd.DataFrame:
        files = list(self.base_path.glob(pattern))
        if not files:
            raise FileNotFoundError(f"No files found matching pattern: {pattern}")
        
        dfs = [pd.read_parquet(file) for file in files]
        return pd.concat(dfs, ignore_index=True)

    def get_beacon_events_from_parquet(
        self,
        date_pattern: str = "beacon_events_*.parquet",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> pd.DataFrame:
        df = self.read_multiple_parquet(date_pattern)
        
        if "event_date_time" in df.columns:
            df["event_date_time"] = pd.to_datetime(df["event_date_time"])
            
            if start_time:
                df = df[df["event_date_time"] >= pd.to_datetime(start_time)]
            if end_time:
                df = df[df["event_date_time"] <= pd.to_datetime(end_time)]
        
        return df

    def get_mempool_transactions_from_parquet(
        self,
        date_pattern: str = "mempool_*.parquet",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> pd.DataFrame:
        df = self.read_multiple_parquet(date_pattern)
        
        if "event_date_time" in df.columns:
            df["event_date_time"] = pd.to_datetime(df["event_date_time"])
            
            if start_time:
                df = df[df["event_date_time"] >= pd.to_datetime(start_time)]
            if end_time:
                df = df[df["event_date_time"] <= pd.to_datetime(end_time)]
        
        return df

    def list_available_files(self, pattern: str = "*.parquet") -> List[Path]:
        return list(self.base_path.glob(pattern))