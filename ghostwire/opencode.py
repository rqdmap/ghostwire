"""Local OpenCode SQLite reader with fork-message dedupe.

OpenCode forks copy original messages into the new session; if we naively sum
every assistant `usage`, those forks double-count tokens and inflate burst
density.  We mirror mimir's strategy: a message is identified by
``(time_created_ms, role)``; when the same identity appears in multiple
sessions we keep only the copy that lives in the *earliest* session, ordered
by ``session.time_created``.

Public surface:

- :func:`find_db`              - locate the local OpenCode SQLite file
- :func:`read_sessions`        - per-session metadata-only message lists,
                                 fork-deduped
- :func:`extract_bursts`       - turn message timestamps into burst windows
- :func:`extract_token_usage`  - aggregate assistant token usage
- :func:`build_daily_opencode` - one-shot snapshot-shaped output
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .concurrency import Burst
from .sanitize import hash_session_id

OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode_2.db"
DEFAULT_GAP_MINUTES = 10


def find_db() -> Optional[Path]:
    """Locate the OpenCode DB, preferring opencode_2.db then opencode.db"""
    for candidate in (OPENCODE_DB, OPENCODE_DB.with_name("opencode.db")):
        if candidate.exists():
            return candidate
    return None


@dataclass(frozen=True)
class _RawMessage:
    """Internal representation pre-dedupe."""

    raw_session_id: str
    session_created_ms: int
    time_created_ms: int
    time_ended_ms: int
    role: Optional[str]
    model_id: Optional[str]
    provider_id: Optional[str]
    usage: Optional[dict[str, Any]]


def read_sessions(
    target_date: date,
    db_path: Optional[Path] = None,
    *,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Return sessions that touched ``target_date``.

    Each session dict contains a hashed ``session_id`` and a list of message
    metadata dicts.  Fork-copied duplicate messages have already been removed.
    Message bodies are never read.
    """
    resolved = db_path or find_db()
    if resolved is None or not resolved.exists():
        return []

    start_ms, end_ms = _window_bounds_ms(target_date, window_start, window_end)
    filter_date = target_date if window_start is None and window_end is None else None
    raw = _read_raw_messages(resolved, start_ms, end_ms, filter_date)
    deduped = _dedupe_fork_messages(raw)

    grouped: dict[str, list[_RawMessage]] = defaultdict(list)
    for msg in deduped:
        grouped[msg.raw_session_id].append(msg)

    sessions: list[dict[str, Any]] = []
    for raw_session_id, msgs in grouped.items():
        hashed = hash_session_id(raw_session_id)
        messages = []
        for msg in sorted(msgs, key=lambda m: m.time_created_ms):
            entry: dict[str, Any] = {
                "session_id": hashed,
                "role": msg.role,
                "time_created_ms": msg.time_created_ms,
                "time_ended_ms": msg.time_ended_ms,
                "model_id": msg.model_id,
                "provider_id": msg.provider_id,
            }
            if msg.usage is not None:
                entry["usage"] = msg.usage
            messages.append(entry)
        sessions.append({"session_id": hashed, "messages": messages})

    return sessions


def _read_raw_messages(
    db_path: Path,
    start_ms: int,
    end_ms: int,
    filter_date: Optional[date],
) -> list[_RawMessage]:
    try:
        connection = sqlite3.connect(str(db_path))
    except sqlite3.Error:
        return []

    connection.row_factory = sqlite3.Row
    raw: list[_RawMessage] = []

    try:
        rows = _query_messages(connection, start_ms, end_ms)
        message_ids = [row["message_id"] for row in rows if row["message_id"]]
        part_extents = _query_part_extents(connection, message_ids)
        for row in rows:
            payload = _load_payload(row["data"])
            if payload is None:
                continue

            created_ms = _coerce_int(payload.get("time", {}).get("created"))
            if created_ms is None:
                created_ms = _coerce_int(row["time_created"])
            if created_ms is None:
                continue
            if filter_date is not None and _date_from_ms(created_ms) != filter_date:
                continue

            ended_ms = _resolve_message_end_ms(
                payload=payload,
                created_ms=created_ms,
                row_time_updated=_coerce_int(row["time_updated"]),
                part_extent=part_extents.get(row["message_id"]),
            )

            raw.append(
                _RawMessage(
                    raw_session_id=str(row["session_id"]),
                    session_created_ms=int(row["session_created"] or created_ms),
                    time_created_ms=created_ms,
                    time_ended_ms=ended_ms,
                    role=payload.get("role"),
                    model_id=_extract_model_id(payload),
                    provider_id=_extract_provider_id(payload),
                    usage=_extract_usage_dict(payload),
                )
            )
    except sqlite3.Error:
        return []
    finally:
        connection.close()

    return raw


def _query_messages(connection: sqlite3.Connection, start_ms: int, end_ms: int):
    """Return message rows with session_created. Falls back when no session table.

    Each row exposes ``message_id``, ``session_id``, ``session_created``,
    ``time_created``, ``time_updated`` and ``data``.  Older mock databases that
    lack ``message.time_updated`` get ``time_created`` reused as a stand-in.
    """
    has_time_updated = _column_exists(connection, "message", "time_updated")
    updated_expr = "m.time_updated" if has_time_updated else "m.time_created"
    fallback_updated = "time_updated" if has_time_updated else "time_created"

    join_query = f"""
        SELECT
            m.id                  AS message_id,
            m.session_id          AS session_id,
            COALESCE(s.time_created, m.time_created) AS session_created,
            m.time_created        AS time_created,
            {updated_expr}        AS time_updated,
            m.data                AS data
        FROM message m
        LEFT JOIN session s ON s.id = m.session_id
        WHERE m.time_created >= ? AND m.time_created < ?
    """
    fallback_query = f"""
        SELECT
            id                   AS message_id,
            session_id           AS session_id,
            time_created         AS session_created,
            time_created         AS time_created,
            {fallback_updated}   AS time_updated,
            data                 AS data
        FROM message
        WHERE time_created >= ? AND time_created < ?
    """
    try:
        return list(connection.execute(join_query, (start_ms, end_ms)))
    except sqlite3.OperationalError:
        return list(connection.execute(fallback_query, (start_ms, end_ms)))


def _column_exists(
    connection: sqlite3.Connection, table: str, column: str
) -> bool:
    try:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.OperationalError:
        return False
    for row in rows:
        if row[1] == column:
            return True
    return False


def _query_part_extents(
    connection: sqlite3.Connection, message_ids: list[str]
) -> dict[str, int]:
    """Return ``{message_id: max(part time)}`` when a ``part`` table exists.

    Falls back to ``{}`` when the table is absent (legacy DBs / tests).
    """
    if not message_ids:
        return {}
    try:
        placeholders = ",".join("?" for _ in message_ids)
        query = (
            "SELECT message_id, MAX(time_updated) AS u, MAX(time_created) AS c "
            "FROM part WHERE message_id IN ("
            + placeholders
            + ") GROUP BY message_id"
        )
        rows = connection.execute(query, message_ids).fetchall()
    except sqlite3.OperationalError:
        return {}
    extents: dict[str, int] = {}
    for row in rows:
        u = _coerce_int(row["u"])
        c = _coerce_int(row["c"])
        candidates = [v for v in (u, c) if v is not None]
        if candidates:
            extents[row["message_id"]] = max(candidates)
    return extents


def _resolve_message_end_ms(
    *,
    payload: dict[str, Any],
    created_ms: int,
    row_time_updated: Optional[int],
    part_extent: Optional[int],
) -> int:
    """Pick the best available "end" timestamp for a message.

    Order of preference:

    1. ``data.time.completed`` -- official semantic completion (assistant only)
    2. ``MAX(part.time_updated, part.time_created)`` -- inferred from observed parts
    3. ``message.time_updated`` -- storage-layer last-write time

    All candidates are clamped to ``>= created_ms`` so we never invent intervals
    that end before they started.
    """
    completed = _coerce_int(payload.get("time", {}).get("completed"))
    if completed is not None and completed >= created_ms:
        return completed
    if part_extent is not None and part_extent >= created_ms:
        return part_extent
    if row_time_updated is not None and row_time_updated >= created_ms:
        return row_time_updated
    return created_ms


def _dedupe_fork_messages(messages: list[_RawMessage]) -> list[_RawMessage]:
    """Drop fork-copied duplicates by ``(time_created_ms, role)``.

    When the same ``(time_created_ms, role)`` appears in multiple raw sessions,
    keep only the message belonging to the session whose ``session_created_ms``
    is smallest (earliest).  Ties resolved by raw session id for determinism.
    """
    if not messages:
        return []

    by_identity: dict[tuple[int, Optional[str]], list[_RawMessage]] = defaultdict(list)
    for msg in messages:
        by_identity[(msg.time_created_ms, msg.role)].append(msg)

    kept: list[_RawMessage] = []
    for group in by_identity.values():
        if len(group) == 1:
            kept.extend(group)
            continue
        # Multiple sessions share this identity → fork duplicates.  Keep the
        # message that lives in the earliest session.
        winner = min(group, key=lambda m: (m.session_created_ms, m.raw_session_id))
        kept.append(winner)

    kept.sort(key=lambda m: (m.time_created_ms, m.raw_session_id))
    return kept


# ── Burst extraction ──────────────────────────────────────────────────────


def extract_bursts(
    messages: list[dict[str, Any]], gap_minutes: int = DEFAULT_GAP_MINUTES
) -> list[Burst]:
    """Group assistant message intervals into per-session bursts.

    Only ``assistant`` messages contribute, because they are the only role with
    a meaningful ``[time_created_ms, time_ended_ms]`` envelope (covering model
    generation + reasoning + tool execution).  Each interval is clamped so that
    ``end > start``; zero-length / inverted intervals are dropped rather than
    backfilled with synthetic grace periods.
    """
    intervals: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for message in messages:
        if message.get("role") != "assistant":
            continue
        start_ms = _coerce_int(message.get("time_created_ms"))
        if start_ms is None:
            continue
        end_ms = _coerce_int(message.get("time_ended_ms"))
        if end_ms is None or end_ms <= start_ms:
            continue
        intervals[str(message.get("session_id", ""))].append((start_ms, end_ms))

    gap_ms = gap_minutes * 60 * 1000
    bursts: list[Burst] = []

    for session_id in sorted(intervals):
        ordered = sorted(intervals[session_id])
        burst_start, burst_end = ordered[0]
        for start_ms, end_ms in ordered[1:]:
            if start_ms - burst_end <= gap_ms:
                if end_ms > burst_end:
                    burst_end = end_ms
                continue
            bursts.append(_make_burst(burst_start, burst_end, session_id))
            burst_start, burst_end = start_ms, end_ms
        bursts.append(_make_burst(burst_start, burst_end, session_id))

    bursts.sort(key=lambda b: (b.start, b.end, b.session_id))
    return bursts


def _make_burst(start_ms: int, end_ms: int, session_id: str) -> Burst:
    return Burst(
        start=_datetime_from_ms(start_ms),
        end=_datetime_from_ms(end_ms),
        session_id=session_id,
    )


def extract_token_usage(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate assistant token usage across multiple usage shapes."""
    total = 0
    by_model: dict[str, int] = defaultdict(int)

    for message in messages:
        if message.get("role") != "assistant":
            continue

        message_total = _usage_total(message)
        if message_total <= 0:
            continue

        total += message_total
        model_id = message.get("model_id")
        if isinstance(model_id, str) and model_id:
            by_model[model_id] += message_total

    return {"total": total, "by_model": dict(sorted(by_model.items()))}


def build_daily_opencode(
    target_date: date,
    db_path: Optional[Path] = None,
    *,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    burst_gap_minutes: int = DEFAULT_GAP_MINUTES,
) -> list[dict[str, Any]]:
    """Return the OpenCode payload shape expected by ``build_host_snapshot``.

    Each list item is::

        {
            "session_id": "<sha256-truncated>",
            "model": "<dominant model id or None>",
            "tokens_total": int,
            "by_model": [{"model": str, "tokens": int}],
            "bursts": [{"start": "...iso...", "end": "...iso..."}],
        }
    """
    sessions = read_sessions(
        target_date,
        db_path=db_path,
        window_start=window_start,
        window_end=window_end,
    )
    out: list[dict[str, Any]] = []
    for session in sessions:
        messages = session["messages"]
        usage = extract_token_usage(messages)
        bursts = extract_bursts(messages, gap_minutes=burst_gap_minutes)
        dominant_model: Optional[str] = None
        if usage["by_model"]:
            dominant_model = max(usage["by_model"], key=usage["by_model"].get)
        by_model = [
            {"model": model, "tokens": tokens}
            for model, tokens in sorted(
                usage["by_model"].items(), key=lambda kv: (-kv[1], kv[0])
            )
        ]
        out.append(
            {
                "session_id": session["session_id"],
                "model": dominant_model,
                "tokens_total": usage["total"],
                "by_model": by_model,
                "bursts": [
                    {"start": b.start.isoformat(), "end": b.end.isoformat()}
                    for b in bursts
                ],
            }
        )
    return out


def _day_bounds_ms(target_date: date) -> tuple[int, int]:
    local_tz = datetime.now().astimezone().tzinfo
    start = datetime.combine(target_date, time.min, tzinfo=local_tz)
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _window_bounds_ms(
    target_date: date,
    window_start: Optional[datetime],
    window_end: Optional[datetime],
) -> tuple[int, int]:
    if window_start is None and window_end is None:
        return _day_bounds_ms(target_date)
    if window_start is None or window_end is None:
        raise ValueError("window_start and window_end must be provided together")
    return int(window_start.timestamp() * 1000), int(window_end.timestamp() * 1000)


def _date_from_ms(timestamp_ms: int) -> date:
    return datetime.fromtimestamp(timestamp_ms / 1000).date()


def _datetime_from_ms(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def _load_payload(raw_data: str) -> Optional[dict[str, Any]]:
    try:
        payload = json.loads(raw_data)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _extract_model_id(payload: dict[str, Any]) -> Optional[str]:
    model = payload.get("model")
    if isinstance(model, dict):
        mid = model.get("modelID")
        if isinstance(mid, str) and mid:
            return mid
    mid = payload.get("modelID")
    return mid if isinstance(mid, str) and mid else None


def _extract_provider_id(payload: dict[str, Any]) -> Optional[str]:
    model = payload.get("model")
    if isinstance(model, dict):
        pid = model.get("providerID")
        if isinstance(pid, str) and pid:
            return pid
    pid = payload.get("providerID")
    return pid if isinstance(pid, str) and pid else None


def _extract_usage_dict(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        usage = metadata.get("usage")
        if isinstance(usage, dict):
            return usage
    usage = payload.get("usage")
    if isinstance(usage, dict):
        return usage
    # OpenCode upstream often stores tokens at payload.tokens
    tokens = payload.get("tokens")
    if isinstance(tokens, dict):
        return tokens
    return None


def _usage_total(message: dict[str, Any]) -> int:
    candidates: list[dict[str, Any]] = []

    tokens = message.get("tokens")
    if isinstance(tokens, dict):
        candidates.append(tokens)

    usage = message.get("usage")
    if isinstance(usage, dict):
        candidates.append(usage)

    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        nested = metadata.get("usage")
        if isinstance(nested, dict):
            candidates.append(nested)

    candidates.append(message)

    for candidate in candidates:
        total = _sum_usage_fields(candidate)
        if total is not None:
            return total
    return 0


def _sum_usage_fields(usage: dict[str, Any]) -> Optional[int]:
    cache = usage.get("cache")
    cache_read = _coerce_int(cache.get("read") if isinstance(cache, dict) else None) or 0
    cache_write = _coerce_int(cache.get("write") if isinstance(cache, dict) else None) or 0

    pairs = (
        ("inputTokens", "outputTokens"),
        ("input_tokens", "output_tokens"),
        ("promptTokens", "completionTokens"),
        ("prompt_tokens", "completion_tokens"),
        ("input", "output"),
    )
    for in_key, out_key in pairs:
        in_tok = _coerce_int(usage.get(in_key))
        out_tok = _coerce_int(usage.get(out_key))
        if in_tok is not None or out_tok is not None:
            return (in_tok or 0) + (out_tok or 0) + cache_read + cache_write

    for total_key in ("totalTokens", "total_tokens"):
        total = _coerce_int(usage.get(total_key))
        if total is not None:
            return total + cache_read + cache_write
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
