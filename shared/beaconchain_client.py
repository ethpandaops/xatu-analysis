import os
import time
from typing import Dict, Any, Optional, List, Union
from functools import lru_cache
import httpx
from pydantic import ValidationError
import logging

from .models.beaconchain_models import (
    BeaconchainResponse,
    ValidatorInfo,
    ValidatorPerformance,
    ValidatorExecutionPerformance,
    ValidatorIncomeHistory,
    ValidatorProposal,
    ValidatorWithdrawal,
    ValidatorDailyStats
)

logger = logging.getLogger(__name__)

class RateLimiter:
    """Simple rate limiter for API calls"""
    def __init__(self, calls_per_minute: int = 10):
        self.calls_per_minute = calls_per_minute
        self.call_times: List[float] = []
    
    def wait_if_needed(self) -> None:
        """Wait if rate limit would be exceeded"""
        now = time.time()
        minute_ago = now - 60
        
        # Remove old calls
        self.call_times = [t for t in self.call_times if t > minute_ago]
        
        if len(self.call_times) >= self.calls_per_minute:
            sleep_time = 60 - (now - self.call_times[0]) + 0.1
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        self.call_times.append(time.time())

class BeaconchainClient:
    """Client for interacting with beaconcha.in API"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """Initialize the client with optional API key and base URL"""
        self.api_key = api_key or os.getenv('BEACONCHAIN_API_KEY')
        self.base_url = (base_url or os.getenv('BEACONCHAIN_BASE_URL', 'https://beaconcha.in')).rstrip('/')
        self.rate_limiter = RateLimiter(calls_per_minute=10 if not self.api_key else 100)
        self._client = httpx.Client(timeout=30.0)
    
    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make HTTP request to the API with rate limiting and error handling"""
        self.rate_limiter.wait_if_needed()
        
        headers = {}
        if self.api_key:
            headers['apikey'] = self.api_key
        
        url = f"{self.base_url}/api/v1{endpoint}"
        
        try:
            response = self._client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for {url}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Request failed for {url}: {str(e)}")
            raise
    
    def get_validator_info(self, indices_or_pubkeys: Union[str, List[str]]) -> List[ValidatorInfo]:
        """Get basic validator information for up to 100 validators"""
        if isinstance(indices_or_pubkeys, list):
            indices_or_pubkeys = ','.join(str(x) for x in indices_or_pubkeys)
        
        response = self._make_request(f"/validator/{indices_or_pubkeys}")
        
        try:
            parsed = BeaconchainResponse(**response)
            if isinstance(parsed.data, list):
                return [ValidatorInfo(**v) for v in parsed.data]
            else:
                return [ValidatorInfo(**parsed.data)]
        except ValidationError as e:
            logger.error(f"Failed to parse validator info response: {e}")
            return []
    
    def get_validator_stats(self, index: int, start_day: Optional[int] = None, end_day: Optional[int] = None) -> List[ValidatorDailyStats]:
        """Get validator statistics over time
        
        Args:
            index: Validator index
            start_day: Start day number (day 1 = Dec 1, 2020)
            end_day: End day number (day 1 = Dec 1, 2020)
        """
        params = {}
        if start_day is not None:
            params['start_day'] = start_day
        if end_day is not None:
            params['end_day'] = end_day
        
        response = self._make_request(f"/validator/stats/{index}", params=params)
        
        try:
            parsed = BeaconchainResponse(**response)
            if isinstance(parsed.data, list):
                return [ValidatorDailyStats(**v) for v in parsed.data]
            else:
                return [ValidatorDailyStats(**parsed.data)]
        except ValidationError as e:
            logger.error(f"Failed to parse validator stats response: {e}")
            return []
    
    def get_validator_performance(self, indices_or_pubkeys: Union[str, List[str]]) -> List[ValidatorPerformance]:
        """Get validator consensus layer performance metrics"""
        if isinstance(indices_or_pubkeys, list):
            indices_or_pubkeys = ','.join(str(x) for x in indices_or_pubkeys)
        
        response = self._make_request(f"/validator/{indices_or_pubkeys}/performance")
        
        try:
            parsed = BeaconchainResponse(**response)
            if isinstance(parsed.data, list):
                return [ValidatorPerformance(**v) for v in parsed.data]
            else:
                return [ValidatorPerformance(**parsed.data)]
        except ValidationError as e:
            logger.error(f"Failed to parse validator performance response: {e}")
            return []
    
    def get_validator_execution_performance(self, indices_or_pubkeys: Union[str, List[str]]) -> List[ValidatorExecutionPerformance]:
        """Get validator execution layer performance metrics"""
        if isinstance(indices_or_pubkeys, list):
            indices_or_pubkeys = ','.join(str(x) for x in indices_or_pubkeys)
        
        response = self._make_request(f"/validator/{indices_or_pubkeys}/execution/performance")
        
        try:
            parsed = BeaconchainResponse(**response)
            if isinstance(parsed.data, list):
                return [ValidatorExecutionPerformance(**v) for v in parsed.data]
            else:
                return [ValidatorExecutionPerformance(**parsed.data)]
        except ValidationError as e:
            logger.error(f"Failed to parse execution performance response: {e}")
            return []
    
    def get_validator_attestation_efficiency(self, indices_or_pubkeys: Union[str, List[str]]) -> Dict[str, Any]:
        """Get validator attestation efficiency (returns raw response as structure not defined)"""
        if isinstance(indices_or_pubkeys, list):
            indices_or_pubkeys = ','.join(str(x) for x in indices_or_pubkeys)
        
        response = self._make_request(f"/validator/{indices_or_pubkeys}/attestationefficiency")
        
        try:
            parsed = BeaconchainResponse(**response)
            return parsed.data
        except ValidationError as e:
            logger.error(f"Failed to parse attestation efficiency response: {e}")
            return {}
    
    def get_validator_income_history(self, indices_or_pubkeys: Union[str, List[str]], 
                                   latest_epoch: Optional[int] = None,
                                   offset: Optional[int] = None,
                                   limit: Optional[int] = None) -> List[ValidatorIncomeHistory]:
        """Get detailed validator income history"""
        if isinstance(indices_or_pubkeys, list):
            indices_or_pubkeys = ','.join(str(x) for x in indices_or_pubkeys)
        
        params = {}
        if latest_epoch is not None:
            params['latest_epoch'] = latest_epoch
        if offset is not None:
            params['offset'] = offset
        if limit is not None:
            params['limit'] = min(limit, 100)  # API max is 100
        
        response = self._make_request(f"/validator/{indices_or_pubkeys}/incomedetailhistory", params=params)
        
        try:
            parsed = BeaconchainResponse(**response)
            if isinstance(parsed.data, list):
                return [ValidatorIncomeHistory(**v) for v in parsed.data]
            else:
                return [ValidatorIncomeHistory(**parsed.data)]
        except ValidationError as e:
            logger.error(f"Failed to parse income history response: {e}")
            return []
    
    def get_validator_proposals(self, indices_or_pubkeys: Union[str, List[str]], epoch: Optional[int] = None) -> List[ValidatorProposal]:
        """Get validator proposed blocks"""
        if isinstance(indices_or_pubkeys, list):
            indices_or_pubkeys = ','.join(str(x) for x in indices_or_pubkeys)
        
        params = {}
        if epoch is not None:
            params['epoch'] = epoch
        
        response = self._make_request(f"/validator/{indices_or_pubkeys}/proposals", params=params)
        
        try:
            parsed = BeaconchainResponse(**response)
            if isinstance(parsed.data, list):
                return [ValidatorProposal(**v) for v in parsed.data]
            else:
                return [ValidatorProposal(**parsed.data)]
        except ValidationError as e:
            logger.error(f"Failed to parse proposals response: {e}")
            return []
    
    def get_validator_withdrawals(self, indices_or_pubkeys: Union[str, List[str]], epoch: Optional[int] = None) -> List[ValidatorWithdrawal]:
        """Get validator withdrawal history"""
        if isinstance(indices_or_pubkeys, list):
            indices_or_pubkeys = ','.join(str(x) for x in indices_or_pubkeys)
        
        params = {}
        if epoch is not None:
            params['epoch'] = epoch
        
        response = self._make_request(f"/validator/{indices_or_pubkeys}/withdrawals", params=params)
        
        try:
            parsed = BeaconchainResponse(**response)
            if isinstance(parsed.data, list):
                return [ValidatorWithdrawal(**v) for v in parsed.data]
            else:
                return [ValidatorWithdrawal(**parsed.data)]
        except ValidationError as e:
            logger.error(f"Failed to parse withdrawals response: {e}")
            return []
    
    def close(self) -> None:
        """Close the HTTP client"""
        self._client.close()
    
    def __enter__(self):
        """Context manager support"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup"""
        self.close()

# Convenience function for getting a configured client
@lru_cache(maxsize=1)
def get_beaconchain_client() -> BeaconchainClient:
    """Get a singleton BeaconchainClient instance"""
    return BeaconchainClient()