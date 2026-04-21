from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from importlib import import_module
from typing import TYPE_CHECKING, Any

from .config import Config
from .models import HostMeta, HostSnapshot, OpenCodeBurst, OpenCodeSession

categorize = import_module("aw_report.categorize").categorize
hash_session_id = import_module("aw_report.sanitize").hash_session_id
sanitize_snapshot = import_module("aw_report.sanitize").sanitize_snapshot

if TYPE_CHECKING:
    from aw_report.aw_client import AWClient
else:
    AWClient = Any


def collect_active_windows(
    *args: Any, **kwargs: Any
) -> tuple[list[dict], float, float]:
    module = import_module("aw_report.collect")
    return module.collect_active_windows(*args, **kwargs)


def discover_host_buckets(client: AWClient) -> dict:
    module = import_module("aw_report.aw_client")
    return module.discover_host_buckets(client)


def _get_bucket_id(buckets: dict[str, Any], host_id: str, *names: str) -> str:
    candidates = [buckets]
    host_bucket = buckets.get(host_id)
    if isinstance(host_bucket, dict):
        candidates.append(host_bucket)
    for value in buckets.values():
        if isinstance(value, dict):
            candidates.append(value)

    aliases = []
    for name in names:
        aliases.extend((name, f"{name}_bucket"))

    for candidate in candidates:
        for alias in aliases:
            value = candidate.get(alias)
            if isinstance(value, str):
                return value
    raise KeyError(f"Missing bucket id for {host_id}: {', '.join(names)}")


def _build_rhythm(events: list[dict], start: datetime, tz) -> list[int]:
    del start
    rhythm = [0] * 24
    for event in events:
        timestamp = event.get("timestamp")
        if not timestamp:
            continue
        ts = datetime.fromisoformat(timestamp)
        hour = ts.astimezone(tz).hour
        rhythm[hour] += int(event.get("duration", 0))
    return rhythm


def _get_session_value(session: Any, key: str, default: Any = None) -> Any:
    if isinstance(session, dict):
        return session.get(key, default)
    return getattr(session, key, default)


def _normalize_session_id(raw_session_id: str) -> str:
    if len(raw_session_id) == 16 and all(
        ch in "0123456789abcdef" for ch in raw_session_id
    ):
        return raw_session_id
    return hash_session_id(raw_session_id)


def _build_opencode(opencode_sessions: list | None) -> dict[str, Any]:
    if opencode_sessions is None:
        return {"tokens_total": 0, "by_model": [], "sessions": []}

    tokens_total = 0
    tokens_by_model: dict[str, int] = {}
    sessions: list[OpenCodeSession] = []

    for session in opencode_sessions:
        session_tokens = int(
            _get_session_value(
                session, "tokens_total", _get_session_value(session, "tokens", 0)
            )
        )
        tokens_total += session_tokens

        model_name = _get_session_value(
            session, "model", _get_session_value(session, "model_name")
        )
        if model_name:
            tokens_by_model[model_name] = (
                tokens_by_model.get(model_name, 0) + session_tokens
            )

        raw_bursts = _get_session_value(session, "bursts", [])
        bursts = [
            OpenCodeBurst(
                start=_get_session_value(burst, "start"),
                end=_get_session_value(burst, "end"),
            )
            for burst in raw_bursts
        ]
        raw_session_id = str(_get_session_value(session, "session_id", ""))
        sessions.append(
            OpenCodeSession(
                session_id=_normalize_session_id(raw_session_id),
                bursts=bursts,
            )
        )

    by_model = [
        {"model": model, "tokens": tokens}
        for model, tokens in sorted(
            tokens_by_model.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    return {
        "tokens_total": tokens_total,
        "by_model": by_model,
        "sessions": sessions,
    }


def build_host_snapshot(
    client: AWClient,
    host_meta: HostMeta,
    config: Config,
    target_date: date,
    opencode_sessions: list | None = None,
) -> HostSnapshot:
    tz = config.timezone
    start = datetime.combine(target_date, time.min, tzinfo=tz)
    end = start + timedelta(days=1)

    buckets = discover_host_buckets(client)
    window_bucket = _get_bucket_id(buckets, host_meta.id, "window", "currentwindow")
    afk_bucket = _get_bucket_id(buckets, host_meta.id, "afk", "afkstatus")
    events, active_seconds, _afk_seconds = collect_active_windows(
        client,
        window_bucket,
        afk_bucket,
        start,
        end,
    )

    by_category = {"terminal": 0, "browser": 0, "other": 0}
    visible_apps: dict[tuple[str, str], int] = {}
    allowlisted_apps = set(config.categorize_terminal) | set(config.categorize_browser)

    for event in events:
        app_name = str(event.get("data", {}).get("app", ""))
        seconds = int(event.get("duration", 0))
        category = categorize(app_name, config)
        by_category[category] += seconds
        if app_name in allowlisted_apps:
            key = (app_name, category)
            visible_apps[key] = visible_apps.get(key, 0) + seconds

    applications = [
        {"name": name, "category": category, "seconds": seconds}
        for (name, category), seconds in sorted(
            visible_apps.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
        )
    ]

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
        rhythm=_build_rhythm(events, start, tz),
        opencode=_build_opencode(opencode_sessions),
    )
    sanitize_snapshot(asdict(snapshot))
    snapshot.validate()
    return snapshot
