from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from .aw_client import AWClient, discover_host_buckets
from .categorize import categorize
from .collect import collect_active_windows
from .config import Config
from .models import HostMeta, HostSnapshot, OpenCodeBurst, OpenCodeSession
from .opencode import build_daily_opencode
from .sanitize import hash_session_id, sanitize_snapshot


def build_host_snapshot(
    client: AWClient,
    host_meta: HostMeta,
    config: Config,
    target_date: date,
    opencode_sessions: list[dict[str, Any]] | None = None,
) -> HostSnapshot:
    tz = config.timezone
    start, end = config.reporting_window(target_date)

    buckets = discover_host_buckets(client)
    window_bucket, afk_bucket = _resolve_buckets(buckets, host_meta.id)

    events, active_seconds, _ = collect_active_windows(
        client, window_bucket, afk_bucket, start, end
    )

    by_category = {"terminal": 0, "browser": 0, "other": 0}
    visible_apps: dict[tuple[str, str], int] = {}
    allowlisted = set(config.categorize_terminal) | set(config.categorize_browser)

    for event in events:
        app = str(event.get("data", {}).get("app", ""))
        seconds = int(event.get("duration", 0))
        category = categorize(app, config)
        by_category[category] += seconds
        if app in allowlisted:
            key = (app, category)
            visible_apps[key] = visible_apps.get(key, 0) + seconds

    applications = [
        {"name": name, "category": category, "seconds": seconds}
        for (name, category), seconds in sorted(
            visible_apps.items(), key=lambda kv: (-kv[1], kv[0][0])
        )
    ]

    if opencode_sessions is None:
        opencode_sessions = build_daily_opencode(
            target_date,
            window_start=start,
            window_end=end,
            burst_gap_minutes=config.opencode_burst_gap_minutes,
        )

    snapshot = HostSnapshot(
        host=host_meta,
        date=target_date.isoformat(),
        timezone=str(tz),
        generated_at=datetime.now(tz).isoformat(),
        active={
            "total_seconds": int(active_seconds),
            "by_category": by_category,
        },
        applications=applications,
        rhythm=_build_rhythm(events, tz),
        opencode=_build_opencode(opencode_sessions),
    )
    sanitize_snapshot(asdict(snapshot))
    snapshot.validate()
    return snapshot


def _resolve_buckets(
    buckets: dict[str, dict[str, str]], host_id: str
) -> tuple[str, str]:
    """Find window+AFK bucket ids for ``host_id``.

    AW returns logical names like ``currentwindow`` / ``afkstatus``; some
    fixtures use ``window`` / ``afk``.  Search both.
    """
    candidates: list[dict[str, str]] = []
    if host_id in buckets and isinstance(buckets[host_id], dict):
        candidates.append(buckets[host_id])
    candidates.extend(v for v in buckets.values() if isinstance(v, dict))

    window_aliases = ("window", "currentwindow", "window_bucket")
    afk_aliases = ("afk", "afkstatus", "afk_bucket")

    window = _first_alias(candidates, window_aliases)
    afk = _first_alias(candidates, afk_aliases)
    if not window or not afk:
        raise KeyError(f"missing window/afk bucket for host {host_id!r}")
    return window, afk


def _first_alias(candidates: list[dict[str, str]], aliases: tuple[str, ...]) -> str:
    for candidate in candidates:
        for alias in aliases:
            value = candidate.get(alias)
            if isinstance(value, str) and value:
                return value
    return ""


def _build_rhythm(events: list[dict], tz) -> list[int]:
    rhythm = [0] * 24
    for event in events:
        ts = event.get("timestamp")
        if not ts:
            continue
        hour = datetime.fromisoformat(ts).astimezone(tz).hour
        rhythm[hour] += int(event.get("duration", 0))
    return rhythm


def _build_opencode(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    if not sessions:
        return {"tokens_total": 0, "by_model": [], "sessions": []}

    tokens_total = 0
    by_model: dict[str, int] = {}
    out_sessions: list[OpenCodeSession] = []

    for session in sessions:
        tokens = int(session.get("tokens_total", session.get("tokens", 0)))
        tokens_total += tokens

        exact_by_model = session.get("by_model")
        if isinstance(exact_by_model, list) and exact_by_model:
            for entry in exact_by_model:
                if not isinstance(entry, dict):
                    continue
                model = entry.get("model")
                if not isinstance(model, str) or not model:
                    continue
                by_model[model] = by_model.get(model, 0) + int(entry.get("tokens", 0))
        else:
            model = session.get("model") or session.get("model_name")
            if model:
                by_model[model] = by_model.get(model, 0) + tokens

        bursts = [
            OpenCodeBurst(start=b["start"], end=b["end"])
            for b in session.get("bursts", [])
        ]
        sid = str(session.get("session_id", ""))
        out_sessions.append(
            OpenCodeSession(session_id=_normalize_session_id(sid), bursts=bursts)
        )

    by_model_list = [
        {"model": m, "tokens": t}
        for m, t in sorted(by_model.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {
        "tokens_total": tokens_total,
        "by_model": by_model_list,
        "sessions": out_sessions,
    }


def _normalize_session_id(raw: str) -> str:
    if len(raw) == 16 and all(ch in "0123456789abcdef" for ch in raw):
        return raw
    return hash_session_id(raw)
