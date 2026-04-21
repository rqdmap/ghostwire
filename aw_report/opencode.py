from __future__ import annotations

import json
import importlib.util
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode_2.db"
MODULE_DIR = Path(__file__).resolve().parent


def _load_sibling_module(module_name: str, file_name: str) -> Any:
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    spec = importlib.util.spec_from_file_location(module_name, MODULE_DIR / file_name)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {module_name}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


Burst = _load_sibling_module("aw_report.concurrency", "concurrency.py").Burst
hash_session_id = _load_sibling_module(
    "aw_report.sanitize", "sanitize.py"
).hash_session_id


def find_db() -> Optional[Path]:
    """Try opencode_2.db then opencode.db"""
    candidates = (OPENCODE_DB, OPENCODE_DB.with_name("opencode.db"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def read_sessions(
    target_date: date, db_path: Optional[Path] = None
) -> list[dict[str, Any]]:
    """
    Query sessions that have messages on target_date.
    Returns list of dicts: {
        "session_id": str (hashed with hash_session_id),
        "messages": list[dict] with at least "role", "time_created_ms", "model_id", "provider_id"
    }
    Reads only message metadata, never message text/content.
    """
    resolved_path = db_path or find_db()
    if resolved_path is None or not resolved_path.exists():
        return []

    start_ms, end_ms = _day_bounds_ms(target_date)
    sessions: dict[str, dict[str, Any]] = {}

    try:
        connection = sqlite3.connect(str(resolved_path))
    except sqlite3.Error:
        return []

    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(
            """
            SELECT session_id, time_created, data
            FROM message
            WHERE time_created >= ? AND time_created < ?
            ORDER BY session_id, time_created
            """,
            (start_ms, end_ms),
        )

        for row in rows:
            payload = _load_payload(row["data"])
            if payload is None:
                continue

            created_ms = _coerce_int(payload.get("time", {}).get("created"))
            if created_ms is None:
                created_ms = _coerce_int(row["time_created"])
            if created_ms is None or _date_from_ms(created_ms) != target_date:
                continue

            raw_session_id = str(row["session_id"])
            session_id = hash_session_id(raw_session_id)
            message = {
                "session_id": session_id,
                "role": payload.get("role"),
                "time_created_ms": created_ms,
                "model_id": _extract_model_id(payload),
                "provider_id": _extract_provider_id(payload),
            }

            usage = _extract_usage_dict(payload)
            if usage:
                message["usage"] = usage

            session = sessions.setdefault(
                session_id, {"session_id": session_id, "messages": []}
            )
            session["messages"].append(message)
    except sqlite3.Error:
        return []
    finally:
        connection.close()

    return list(sessions.values())


def extract_bursts(messages: list[dict[str, Any]], gap_minutes: int = 10) -> list[Any]:
    """Group consecutive messages into bursts when the gap is within the threshold."""
    grouped_messages: dict[str, list[int]] = defaultdict(list)
    for message in messages:
        created_ms = _coerce_int(message.get("time_created_ms"))
        if created_ms is None:
            continue
        session_id = str(message.get("session_id", ""))
        grouped_messages[session_id].append(created_ms)

    bursts: list[Any] = []
    gap_ms = gap_minutes * 60 * 1000

    for session_id in sorted(grouped_messages):
        timestamps = sorted(grouped_messages[session_id])
        if not timestamps:
            continue

        burst_start = timestamps[0]
        burst_end = timestamps[0]

        for timestamp in timestamps[1:]:
            if timestamp - burst_end <= gap_ms:
                burst_end = timestamp
                continue

            bursts.append(
                Burst(
                    start=_datetime_from_ms(burst_start),
                    end=_datetime_from_ms(burst_end),
                    session_id=session_id,
                )
            )
            burst_start = timestamp
            burst_end = timestamp

        bursts.append(
            Burst(
                start=_datetime_from_ms(burst_start),
                end=_datetime_from_ms(burst_end),
                session_id=session_id,
            )
        )

    return sorted(bursts, key=lambda burst: (burst.start, burst.end, burst.session_id))


def extract_token_usage(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate assistant token usage totals across supported usage shapes."""
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


def _day_bounds_ms(target_date: date) -> tuple[int, int]:
    local_tz = datetime.now().astimezone().tzinfo
    start = datetime.combine(target_date, time.min, tzinfo=local_tz)
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _date_from_ms(timestamp_ms: int) -> date:
    return datetime.fromtimestamp(timestamp_ms / 1000).date()


def _datetime_from_ms(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def _load_payload(raw_data: str) -> Optional[dict[str, Any]]:
    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_model_id(payload: dict[str, Any]) -> Optional[str]:
    model = payload.get("model")
    if isinstance(model, dict):
        model_id = model.get("modelID")
        if isinstance(model_id, str) and model_id:
            return model_id
    model_id = payload.get("modelID")
    return model_id if isinstance(model_id, str) and model_id else None


def _extract_provider_id(payload: dict[str, Any]) -> Optional[str]:
    model = payload.get("model")
    if isinstance(model, dict):
        provider_id = model.get("providerID")
        if isinstance(provider_id, str) and provider_id:
            return provider_id
    provider_id = payload.get("providerID")
    return provider_id if isinstance(provider_id, str) and provider_id else None


def _extract_usage_dict(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        usage = metadata.get("usage")
        if isinstance(usage, dict):
            return usage

    usage = payload.get("usage")
    if isinstance(usage, dict):
        return usage

    return None


def _usage_total(message: dict[str, Any]) -> int:
    candidates: list[dict[str, Any]] = []

    usage = message.get("usage")
    if isinstance(usage, dict):
        candidates.append(usage)

    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        nested_usage = metadata.get("usage")
        if isinstance(nested_usage, dict):
            candidates.append(nested_usage)

    candidates.append(message)

    for candidate in candidates:
        total = _sum_usage_fields(candidate)
        if total is not None:
            return total

    return 0


def _sum_usage_fields(usage: dict[str, Any]) -> Optional[int]:
    field_pairs = (
        ("inputTokens", "outputTokens"),
        ("input_tokens", "output_tokens"),
        ("promptTokens", "completionTokens"),
        ("prompt_tokens", "completion_tokens"),
    )

    for input_key, output_key in field_pairs:
        input_tokens = _coerce_int(usage.get(input_key))
        output_tokens = _coerce_int(usage.get(output_key))
        if input_tokens is not None or output_tokens is not None:
            return (input_tokens or 0) + (output_tokens or 0)

    for total_key in ("totalTokens", "total_tokens", "tokens"):
        total_tokens = _coerce_int(usage.get(total_key))
        if total_tokens is not None:
            return total_tokens

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
