from typing import Optional, Dict, Any
from .base import XatuEvent


class BeaconEvent(XatuEvent):
    slot: Optional[int] = None
    epoch: Optional[int] = None
    block_root: Optional[str] = None
    state_root: Optional[str] = None
    proposer_index: Optional[int] = None
    
    @property
    def slot_time(self) -> Optional[float]:
        if self.slot is not None:
            # Ethereum mainnet genesis time: 1606824023
            # Slot duration: 12 seconds
            genesis_time = 1606824023
            return genesis_time + (self.slot * 12)
        return None
    
    @property
    def epoch_from_slot(self) -> Optional[int]:
        if self.slot is not None:
            return self.slot // 32
        return None
