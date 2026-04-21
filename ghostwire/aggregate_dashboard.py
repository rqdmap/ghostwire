from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Optional

from .concurrency import Burst
from .models import HostSnapshot

if TYPE_CHECKING:
    from .models import BestDay, Cards, Dashboard, TimelineEntry


def merge_host_snapshots(snapshots: list[HostSnapshot]) -> dict:
    """Merge N same-date snapshots (different hosts) into one combined dict."""
    date_str = snapshots[0].date if snapshots else ""
    active_total_seconds = sum(s.active.get("total_seconds", 0) for s in snapshots)
    by_category: dict[str, int] = {"terminal": 0, "browser": 0, "other": 0}
    for s in snapshots:
        cats = s.active.get("by_category", {})
        for key in by_category:
            by_category[key] += cats.get(key, 0)
    app_totals: dict[tuple[str, str], int] = {}
    for s in snapshots:
        for app in s.applications:
            key = (app["name"], app["category"])
            app_totals[key] = app_totals.get(key, 0) + app["seconds"]
    applications = [
        {"name": name, "category": cat, "seconds": secs}
        for (name, cat), secs in app_totals.items()
    ]
    rhythm = [0] * 24
    for s in snapshots:
        for i, val in enumerate(s.rhythm[:24]):
            rhythm[i] += val
    opencode_tokens_total = sum(s.opencode.get("tokens_total", 0) for s in snapshots)
    opencode_by_model: dict[str, int] = {}
    for s in snapshots:
        for entry in s.opencode.get("by_model", []):
            model = entry["model"]
            tokens = entry["tokens"]
            opencode_by_model[model] = opencode_by_model.get(model, 0) + tokens
    bursts: list[Burst] = []
    for s in snapshots:
        for session in s.opencode.get("sessions", []):
            for b in session.bursts:
                bursts.append(
                    Burst(
                        start=datetime.fromisoformat(b.start),
                        end=datetime.fromisoformat(b.end),
                        session_id=session.session_id,
                    )
                )
    workstations = [
        {
            "label": s.host.label,
            "platform": s.host.platform,
            "seconds": s.active.get("total_seconds", 0),
        }
        for s in snapshots
    ]
    return {
        "date": date_str,
        "active_total_seconds": active_total_seconds,
        "by_category": by_category,
        "applications": applications,
        "rhythm": rhythm,
        "opencode_tokens_total": opencode_tokens_total,
        "opencode_by_model": opencode_by_model,
        "bursts": bursts,
        "workstations": workstations,
    }


def merge_snapshots_by_date(all_snapshots: list[HostSnapshot]) -> dict[str, dict]:
    by_date: dict[str, list[HostSnapshot]] = defaultdict(list)
    for s in all_snapshots:
        by_date[s.date].append(s)
    return {d: merge_host_snapshots(snaps) for d, snaps in by_date.items()}


def build_timeline_30d(
    merged_by_date: dict[str, dict],
    today: date,
) -> list["TimelineEntry"]:
    """
    Return exactly 30 TimelineEntry items (today-29 through today).
    Missing dates get zeros.
    """
    from .models import TimelineEntry

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
    Missing days contribute zeros so the average always spans 7 logical days.
    """
    totals = [0.0] * 24
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        merged = merged_by_date.get(d.isoformat())
        rhythm = merged.get("rhythm", []) if merged else []
        for hour in range(24):
            totals[hour] += rhythm[hour] if hour < len(rhythm) else 0
    return [int(totals[hour] / 7) for hour in range(24)]


def _date_bounds(today: date, days: int) -> tuple[date, date]:
    return today - timedelta(days=days - 1), today


def _filter_merged_by_date(
    merged_by_date: dict[str, dict],
    start: date,
    end: date,
) -> dict[str, dict]:
    start_str = start.isoformat()
    end_str = end.isoformat()
    return {
        date_str: merged
        for date_str, merged in merged_by_date.items()
        if start_str <= date_str <= end_str
    }


def select_best_day(timeline: list["TimelineEntry"]) -> "BestDay":
    from .models import BestDay

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
    from .models import Cards, SessionLoad, WorkstationEntry

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


def aggregate(
    snapshots: list["HostSnapshot"],
    today: Optional[date] = None,
    timezone_name: str = "Asia/Shanghai",
    day_start: time = time.min,
) -> "Dashboard":
    from datetime import date as date_type

    from .concurrency import compute_concurrency
    from .models import (
        ApplicationEntry,
        Dashboard,
        DashboardHeader,
        DashboardRange,
        ModelEntry,
    )

    if today is None:
        today = date_type.today()

    merged_by_date = merge_snapshots_by_date(snapshots)
    range_start, range_end = _date_bounds(today, 30)
    range_merged = _filter_merged_by_date(merged_by_date, range_start, range_end)
    timeline_30d = build_timeline_30d(merged_by_date, today)

    previous_end = today - timedelta(days=30)
    timeline_prev_30d = build_timeline_30d(merged_by_date, previous_end)

    rhythm_7d = compute_rhythm_7d(merged_by_date, today)
    best_day = select_best_day(timeline_30d)

    all_bursts: list[Burst] = []
    for merged in range_merged.values():
        all_bursts.extend(merged.get("bursts", []))
    concurrency_metrics = compute_concurrency(all_bursts, day_start=day_start)

    ws_totals: dict[tuple[str, str], int] = {}
    for merged in range_merged.values():
        for workstation in merged.get("workstations", []):
            key = (workstation["label"], workstation["platform"])
            ws_totals[key] = ws_totals.get(key, 0) + workstation["seconds"]
    workstations = [
        {"label": label, "platform": platform, "seconds": seconds}
        for (label, platform), seconds in ws_totals.items()
    ]

    cards = build_cards(
        timeline_30d=timeline_30d,
        timeline_prev_30d=timeline_prev_30d,
        concurrency=concurrency_metrics,
        workstations=workstations,
        today=today,
    )

    app_totals: dict[str, int] = {"terminal": 0, "browser": 0, "other": 0}
    for merged in range_merged.values():
        by_category = merged.get("by_category", {})
        for category in app_totals:
            app_totals[category] += by_category.get(category, 0)
    category_labels = {"terminal": "终端", "browser": "浏览器", "other": "其他"}
    applications_30d = [
        ApplicationEntry(
            category=category, label=category_labels[category], seconds=seconds
        )
        for category, seconds in sorted(
            app_totals.items(), key=lambda item: item[1], reverse=True
        )
    ]

    model_totals: dict[str, int] = {}
    for merged in range_merged.values():
        for model, tokens in merged.get("opencode_by_model", {}).items():
            model_totals[model] = model_totals.get(model, 0) + tokens
    models_30d = sorted(
        [
            ModelEntry(model=model, tokens=tokens)
            for model, tokens in model_totals.items()
        ],
        key=lambda entry: entry.tokens,
        reverse=True,
    )

    generated_at = datetime.now().isoformat()
    start_date = (today - timedelta(days=29)).isoformat()
    return Dashboard(
        generated_at=generated_at,
        range=DashboardRange(
            days=30,
            start=start_date,
            end=today.isoformat(),
            timezone=timezone_name,
        ),
        header=DashboardHeader(
            hosts_count=len({snapshot.host.id for snapshot in snapshots}),
            synced_at=generated_at,
        ),
        cards=cards,
        timeline_30d=timeline_30d,
        best_day=best_day,
        applications_30d=applications_30d,
        models_30d=models_30d,
        rhythm_7d=rhythm_7d,
    )
