"""Cross-host snapshot merging utilities for the aw-report pipeline."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from aw_report.concurrency import Burst
from aw_report.models import HostSnapshot


def merge_host_snapshots(snapshots: list[HostSnapshot]) -> dict:
    """Merge N snapshots for the SAME date (different hosts) into one combined dict.

    Returns:
    {
        "date": str,
        "active_total_seconds": int,
        "by_category": {"terminal": int, "browser": int, "other": int},
        "applications": list[{"name": str, "category": str, "seconds": int}],
        "rhythm": list[int],                  # 24-element element-wise sum
        "opencode_tokens_total": int,
        "opencode_by_model": dict[str, int],
        "bursts": list[Burst],                # Burst objects for concurrency.py
        "workstations": list[{"label": str, "platform": str, "seconds": int}],
    }
    """
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
    return {date: merge_host_snapshots(snaps) for date, snaps in by_date.items()}
