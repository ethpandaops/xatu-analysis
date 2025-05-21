import clickhouse_connect
import pandas as pd
from typing import Optional, Dict, Any
from ..utils.config import load_config


class ClickHouseConnector:
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        config = load_config()
        
        self.host = host or config.get("clickhouse", {}).get("host", "localhost")
        self.port = port or config.get("clickhouse", {}).get("port", 8123)
        self.username = username or config.get("clickhouse", {}).get("username", "default")
        self.password = password or config.get("clickhouse", {}).get("password", "")
        self.database = database or config.get("clickhouse", {}).get("database", "default")
        
        self.client = None

    def connect(self) -> None:
        self.client = clickhouse_connect.get_client(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            database=self.database,
        )

    def query(self, sql: str, parameters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        if not self.client:
            self.connect()
        
        result = self.client.query_df(sql, parameters=parameters or {})
        return result

    def get_beacon_events(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        event_name: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        conditions = []
        if start_time:
            conditions.append(f"event_date_time >= '{start_time}'")
        if end_time:
            conditions.append(f"event_date_time <= '{end_time}'")
        if event_name:
            conditions.append(f"meta_client_name = '{event_name}'")
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        limit_clause = f"LIMIT {limit}" if limit else ""
        
        sql = f"""
        SELECT *
        FROM beacon_api_eth_v1_events_head
        {where_clause}
        ORDER BY event_date_time DESC
        {limit_clause}
        """
        
        return self.query(sql)

    def get_mempool_transactions(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        conditions = []
        if start_time:
            conditions.append(f"event_date_time >= '{start_time}'")
        if end_time:
            conditions.append(f"event_date_time <= '{end_time}'")
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        limit_clause = f"LIMIT {limit}" if limit else ""
        
        sql = f"""
        SELECT *
        FROM mempool_transaction
        {where_clause}
        ORDER BY event_date_time DESC
        {limit_clause}
        """
        
        return self.query(sql)

    def close(self) -> None:
        if self.client:
            self.client.close()