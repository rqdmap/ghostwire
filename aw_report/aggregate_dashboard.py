from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aw_report.models import BestDay, Cards, TimelineEntry


def build_timeline_30d(
    merged_by_date: dict[str, dict],
    today: date,
) -> list["TimelineEntry"]:
    """
    Return exactly 30 TimelineEntry items (today-29 through today).
    Missing dates get zeros.
    """
    from aw_report.models import TimelineEntry

    entries: list[TimelineEntry] = []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        date_str = d.isoformat()
        merged = merged_by_date.get(date_str, {})
        bc = merged.get("by_category", {})
        entries.append(
            TimelineEntry(
                date=date_str,
                terminal_seconds=bc.get("terminal", 0),
                browser_seconds=bc.get("browser", 0),
                other_seconds=bc.get("other", 0),
                tokens=merged.get("opencode_tokens_total", 0),
            )
        )
    return entries


def compute_delta_pct(current: float, previous: float) -> int:
    if previous == 0:
        return 0
    return round((current - previous) / previous * 100)


def compute_rhythm_7d(
    merged_by_date: dict[str, dict],
    today: date,
) -> list[int]:
    """
    Average the rhythm arrays for the last 7 days.
    Returns 24-element list of average seconds/hour.
    If fewer than 7 days of data, average what's available.
    """
    totals = [0.0] * 24
    days_found = 0
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        merged = merged_by_date.get(d.isoformat())
        if merged and merged.get("rhythm"):
            rhythm = merged["rhythm"]
            for hour in range(24):
                totals[hour] += rhythm[hour] if hour < len(rhythm) else 0
            days_found += 1
    if days_found == 0:
        return [0] * 24
    return [int(totals[hour] / days_found) for hour in range(24)]


def select_best_day(timeline: list["TimelineEntry"]) -> "BestDay":
    from aw_report.models import BestDay

    best = max(
        timeline,
        key=lambda entry: entry.terminal_seconds
        + entry.browser_seconds
        + entry.other_seconds,
    )
    return BestDay(
        date=best.date,
        active_seconds=best.terminal_seconds
        + best.browser_seconds
        + best.other_seconds,
        tokens=best.tokens,
    )


def build_cards(
    timeline_30d: list["TimelineEntry"],
    timeline_prev_30d: list["TimelineEntry"],
    concurrency,
    workstations: list[dict],
    today: date,
) -> "Cards":
    from aw_report.models import Cards, SessionLoad, WorkstationEntry

    del today

    active_30d = sum(
        entry.terminal_seconds + entry.browser_seconds + entry.other_seconds
        for entry in timeline_30d
    )
    active_prev = sum(
        entry.terminal_seconds + entry.browser_seconds + entry.other_seconds
        for entry in timeline_prev_30d
    )
    tokens_7d = sum(entry.tokens for entry in timeline_30d[-7:])
    tokens_prev_7d = sum(entry.tokens for entry in timeline_prev_30d[-7:])
    ws_entries = [
        WorkstationEntry(
            label=workstation["label"],
            platform=workstation["platform"],
            seconds=workstation["seconds"],
        )
        for workstation in workstations
    ]
    session_load = SessionLoad(
        avg_concurrent=concurrency.avg_concurrent,
        peak_concurrent=concurrency.peak_concurrent,
        return_median_seconds=int(concurrency.return_median_seconds),
        trend_7d=concurrency.daily_avg_7d,
    )
    return Cards(
        active_30d_seconds=active_30d,
        active_30d_delta_pct=compute_delta_pct(active_30d, active_prev),
        tokens_7d=tokens_7d,
        tokens_7d_delta_pct=compute_delta_pct(tokens_7d, tokens_prev_7d),
        workstations=ws_entries,
        session_load=session_load,
    )
