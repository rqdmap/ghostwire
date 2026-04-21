from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from statistics import median


@dataclass(frozen=True)
class Burst:
    start: datetime
    end: datetime
    session_id: str


@dataclass
class ConcurrencyMetrics:
    avg_concurrent: float = 0.0
    peak_concurrent: int = 0
    return_median_seconds: float = 0.0
    daily_avg_7d: list[float] = field(default_factory=list)


def compute_concurrency(
    bursts: list[Burst],
    day_start: time = time.min,
) -> ConcurrencyMetrics:
    normalized = [burst for burst in bursts if burst.end > burst.start]
    if not normalized:
        return ConcurrencyMetrics()

    avg_concurrent, peak_concurrent = _weighted_average_and_peak(normalized)
    return_median_seconds = _return_median_seconds(normalized)
    daily_avg_7d = _daily_average_7d(normalized, day_start)

    return ConcurrencyMetrics(
        avg_concurrent=avg_concurrent,
        peak_concurrent=peak_concurrent,
        return_median_seconds=return_median_seconds,
        daily_avg_7d=daily_avg_7d,
    )


def _weighted_average_and_peak(bursts: list[Burst]) -> tuple[float, int]:
    events: list[tuple[datetime, int]] = []
    for burst in bursts:
        events.append((burst.start, 1))
        events.append((burst.end, -1))

    events.sort(key=lambda item: item[0])

    active = 0
    peak = 0
    union_seconds = 0.0
    weighted_sum = 0.0
    previous_time = events[0][0]
    index = 0

    while index < len(events):
        current_time = events[index][0]
        interval_seconds = (current_time - previous_time).total_seconds()
        if interval_seconds > 0 and active > 0:
            union_seconds += interval_seconds
            weighted_sum += active * interval_seconds

        delta = 0
        while index < len(events) and events[index][0] == current_time:
            delta += events[index][1]
            index += 1

        active += delta
        peak = max(peak, active)
        previous_time = current_time

    if union_seconds == 0:
        return 0.0, peak

    return weighted_sum / union_seconds, peak


def _return_median_seconds(bursts: list[Burst]) -> float:
    by_session: dict[str, list[Burst]] = defaultdict(list)
    gaps: list[float] = []

    for burst in bursts:
        by_session[burst.session_id].append(burst)

    for session_bursts in by_session.values():
        ordered = sorted(session_bursts, key=lambda burst: (burst.start, burst.end))
        current_end = ordered[0].end
        for burst in ordered[1:]:
            if burst.start > current_end:
                gaps.append((burst.start - current_end).total_seconds())
                current_end = burst.end
            elif burst.end > current_end:
                current_end = burst.end

    if not gaps:
        return 0.0

    return float(median(gaps))


def _daily_average_7d(bursts: list[Burst], day_start: time) -> list[float]:
    per_day: dict[date, list[Burst]] = defaultdict(list)
    for burst in bursts:
        for day, day_burst in _split_burst_by_day(burst, day_start):
            per_day[day].append(day_burst)

    last_days = sorted(per_day)[-7:]
    averages: list[float] = []
    for day in last_days:
        average, _ = _weighted_average_and_peak(per_day[day])
        averages.append(average)
    return averages


def _split_burst_by_day(burst: Burst, day_start: time) -> list[tuple[date, Burst]]:
    parts: list[tuple[date, Burst]] = []
    cursor = burst.start

    while cursor < burst.end:
        day_label = _logical_day(cursor, day_start)
        next_day = datetime.combine(day_label, day_start, tzinfo=cursor.tzinfo)
        next_day += timedelta(days=1)
        part_end = min(burst.end, next_day)
        parts.append(
            (
                day_label,
                Burst(start=cursor, end=part_end, session_id=burst.session_id),
            )
        )
        cursor = part_end

    return parts


def _logical_day(value: datetime, day_start: time) -> date:
    boundary = datetime.combine(value.date(), day_start, tzinfo=value.tzinfo)
    if value < boundary:
        return value.date() - timedelta(days=1)
    return value.date()
