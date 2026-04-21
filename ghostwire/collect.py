"""Local ActivityWatch collection.

Reads window + AFK buckets for one host between [start, end) and returns:
- merged window events restricted to non-AFK intervals
- total active seconds, total AFK seconds
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .aw_client import AWClient


def fetch_events(
    client: AWClient, bucket_id: str, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    response = client._client.get(
        f"/api/0/buckets/{bucket_id}/events",
        params={"start": start.isoformat(), "end": end.isoformat()},
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def collect_active_windows(
    client: AWClient,
    window_bucket: str,
    afk_bucket: str,
    start: datetime,
    end: datetime,
) -> tuple[list[dict[str, Any]], float, float]:
    window_events = fetch_events(client, window_bucket, start, end)
    afk_events = fetch_events(client, afk_bucket, start, end)

    not_afk_intervals = _not_afk_intervals(afk_events)
    afk_seconds = sum(
        float(e.get("duration", 0))
        for e in afk_events
        if e.get("data", {}).get("status") == "afk"
    )

    active_events: list[dict[str, Any]] = []
    active_seconds = 0.0
    for event in window_events:
        ts = event.get("timestamp")
        dur = float(event.get("duration", 0))
        if not ts or dur <= 0:
            continue
        ev_start = datetime.fromisoformat(ts)
        ev_end = ev_start.fromtimestamp(ev_start.timestamp() + dur, tz=ev_start.tzinfo)
        clipped = _clip_to_intervals((ev_start, ev_end), not_afk_intervals)
        if clipped <= 0:
            continue
        active_events.append(
            {
                "timestamp": ts,
                "duration": clipped,
                "data": event.get("data", {}),
            }
        )
        active_seconds += clipped

    return active_events, active_seconds, afk_seconds


def _not_afk_intervals(
    afk_events: list[dict[str, Any]],
) -> list[tuple[datetime, datetime]]:
    intervals: list[tuple[datetime, datetime]] = []
    for event in afk_events:
        if event.get("data", {}).get("status") != "not-afk":
            continue
        ts = event.get("timestamp")
        dur = float(event.get("duration", 0))
        if not ts or dur <= 0:
            continue
        start = datetime.fromisoformat(ts)
        end = start.fromtimestamp(start.timestamp() + dur, tz=start.tzinfo)
        intervals.append((start, end))
    intervals.sort(key=lambda iv: iv[0])
    return intervals


def _clip_to_intervals(
    event: tuple[datetime, datetime],
    intervals: list[tuple[datetime, datetime]],
) -> float:
    """Return the total seconds of `event` that overlap any active interval."""
    ev_start, ev_end = event
    total = 0.0
    for iv_start, iv_end in intervals:
        if iv_end <= ev_start:
            continue
        if iv_start >= ev_end:
            break
        overlap_start = max(ev_start, iv_start)
        overlap_end = min(ev_end, iv_end)
        total += (overlap_end - overlap_start).total_seconds()
    return total
