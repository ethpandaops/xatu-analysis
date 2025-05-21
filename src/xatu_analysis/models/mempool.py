from typing import Optional, Dict, Any
from .base import XatuEvent


class MempoolEvent(XatuEvent):
    hash: Optional[str] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    value: Optional[str] = None
    gas: Optional[int] = None
    gas_price: Optional[str] = None
    max_fee_per_gas: Optional[str] = None
    max_priority_fee_per_gas: Optional[str] = None
    nonce: Optional[int] = None
    transaction_type: Optional[int] = None
    
    @property
    def value_in_eth(self) -> Optional[float]:
        if self.value:
            try:
                # Convert from wei to ETH
                return int(self.value) / 10**18
            except (ValueError, TypeError):
                return None
        return None
    
    @property
    def gas_price_in_gwei(self) -> Optional[float]:
        if self.gas_price:
            try:
                # Convert from wei to Gwei
                return int(self.gas_price) / 10**9
            except (ValueError, TypeError):
                return None
        return None
