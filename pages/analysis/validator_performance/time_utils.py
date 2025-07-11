"""Time range utilities for validator performance dashboard."""
from typing import Optional, Any, Tuple
from datetime import datetime, timedelta


def get_time_range_from_selection(
    time_range_type: str,
    time_range_value: Optional[str] = None,
    custom_start: Optional[Any] = None,
    custom_end: Optional[Any] = None,
    before_date: Optional[Any] = None,
    after_date: Optional[Any] = None
) -> Optional[Tuple[datetime, datetime]]:
    """Convert time range selection into start and end datetime objects in UTC.
    
    Args:
        time_range_type: Type of time range ('predefined', 'custom', 'before', 'after')
        time_range_value: Value for predefined ranges
        custom_start: Start date for custom range
        custom_end: End date for custom range
        before_date: Date for 'before' type
        after_date: Date for 'after' type
        
    Returns:
        Tuple of (start_datetime, end_datetime) in UTC or None if invalid
    """
    # Use UTC for consistency with APIs
    now = datetime.utcnow()
    
    if time_range_type == 'predefined' and time_range_value:
        days_map = {
            'last_24_hours': 1,
            'last_7_days': 7,
            'last_30_days': 30,
            'last_90_days': 90,
            'last_180_days': 180,
            'last_365_days': 365
        }
        
        if time_range_value in days_map:
            days = days_map[time_range_value]
            end_date = now
            start_date = now - timedelta(days=days)
            return (start_date, end_date)
    
    elif time_range_type == 'custom' and custom_start and custom_end:
        # Convert date objects to datetime in UTC (start of day and end of day in UTC)
        start_datetime = datetime.combine(custom_start, datetime.min.time())
        end_datetime = datetime.combine(custom_end, datetime.max.time())
        return (start_datetime, end_datetime)
    
    elif time_range_type == 'before' and before_date:
        # 30 days before the specified date
        end_datetime = datetime.combine(before_date, datetime.max.time())
        start_datetime = end_datetime - timedelta(days=30)
        return (start_datetime, end_datetime)
    
    elif time_range_type == 'after' and after_date:
        # 30 days after the specified date
        start_datetime = datetime.combine(after_date, datetime.min.time())
        end_datetime = start_datetime + timedelta(days=30)
        return (start_datetime, end_datetime)
    
    return None