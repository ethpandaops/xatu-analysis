from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any


class XatuEvent(BaseModel):
    event_date_time: datetime
    meta_client_name: str
    meta_client_id: str
    meta_client_version: str
    meta_client_implementation: str
    meta_network_id: Optional[int] = None
    meta_network_name: Optional[str] = None
    
    class Config:
        extra = "allow"
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "XatuEvent":
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()