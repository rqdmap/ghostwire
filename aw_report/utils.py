from __future__ import annotations

from datetime import date, datetime, time, timedelta


def day_range(d: date, tz):
    start = datetime.combine(d, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start, end


def parse_range(range_start: str, range_end: str, tz):
    start = datetime.fromisoformat(range_start)
    end = datetime.fromisoformat(range_end)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    return start, end
