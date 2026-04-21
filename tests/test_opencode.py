import json
import importlib.util
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


concurrency = load_module("aw_report.concurrency", "aw_report/concurrency.py")
sanitize = load_module("aw_report.sanitize", "aw_report/sanitize.py")
opencode = load_module("aw_report.opencode", "aw_report/opencode.py")

Burst = concurrency.Burst
OPENCODE_DB = opencode.OPENCODE_DB
extract_bursts = opencode.extract_bursts
extract_token_usage = opencode.extract_token_usage
find_db = opencode.find_db
read_sessions = opencode.read_sessions
hash_session_id = sanitize.hash_session_id


def to_ms(iso_value: str) -> int:
    return int(datetime.fromisoformat(iso_value).timestamp() * 1000)


def build_connection(rows: list[tuple[str, int, dict]]) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        )
        """
    )

    for index, (session_id, created_ms, payload) in enumerate(rows, start=1):
        connection.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
            (
                f"msg-{index}",
                session_id,
                created_ms,
                created_ms,
                json.dumps(payload),
            ),
        )

    connection.commit()
    return connection


def test_find_db_prefers_opencode_2_db(monkeypatch) -> None:
    monkeypatch.setattr(Path, "exists", lambda path: path.name == "opencode_2.db")

    assert find_db() == OPENCODE_DB


def test_find_db_falls_back_to_legacy_name(monkeypatch) -> None:
    monkeypatch.setattr(Path, "exists", lambda path: path.name == "opencode.db")

    assert find_db() == OPENCODE_DB.with_name("opencode.db")


def test_read_sessions_hashes_session_ids_and_keeps_metadata_only(
    monkeypatch, tmp_path
) -> None:
    target_day = date(2026, 4, 21)
    raw_session_id = "ses-raw-123"
    connection = build_connection(
        [
            (
                raw_session_id,
                to_ms("2026-04-21T09:00:00+00:00"),
                {
                    "role": "user",
                    "time": {"created": to_ms("2026-04-21T09:00:00+00:00")},
                    "model": {
                        "providerID": "github-copilot",
                        "modelID": "claude-sonnet-4.6",
                    },
                    "content": [{"type": "text", "text": "secret"}],
                },
            ),
            (
                raw_session_id,
                to_ms("2026-04-21T09:03:00+00:00"),
                {
                    "role": "assistant",
                    "time": {"created": to_ms("2026-04-21T09:03:00+00:00")},
                    "providerID": "github-copilot",
                    "modelID": "claude-sonnet-4.6",
                    "metadata": {"usage": {"inputTokens": 120, "outputTokens": 30}},
                    "summary": "secret",
                },
            ),
            (
                raw_session_id,
                to_ms("2026-04-22T09:00:00+00:00"),
                {
                    "role": "assistant",
                    "time": {"created": to_ms("2026-04-22T09:00:00+00:00")},
                    "providerID": "github-copilot",
                    "modelID": "ignored-on-other-day",
                },
            ),
        ]
    )
    db_path = tmp_path / "mock.db"
    db_path.touch()
    monkeypatch.setattr(opencode.sqlite3, "connect", lambda _: connection)

    sessions = read_sessions(target_day, db_path=db_path)

    assert sessions == [
        {
            "session_id": hash_session_id(raw_session_id),
            "messages": [
                {
                    "session_id": hash_session_id(raw_session_id),
                    "role": "user",
                    "time_created_ms": to_ms("2026-04-21T09:00:00+00:00"),
                    "model_id": "claude-sonnet-4.6",
                    "provider_id": "github-copilot",
                },
                {
                    "session_id": hash_session_id(raw_session_id),
                    "role": "assistant",
                    "time_created_ms": to_ms("2026-04-21T09:03:00+00:00"),
                    "model_id": "claude-sonnet-4.6",
                    "provider_id": "github-copilot",
                    "usage": {"inputTokens": 120, "outputTokens": 30},
                },
            ],
        }
    ]
    assert "content" not in sessions[0]["messages"][0]
    assert "summary" not in sessions[0]["messages"][1]


def test_read_sessions_returns_empty_when_db_is_missing(tmp_path) -> None:
    missing = tmp_path / "missing.db"

    assert read_sessions(date(2026, 4, 21), db_path=missing) == []


def test_extract_bursts_keeps_boundary_gap_in_same_burst() -> None:
    session_id = hash_session_id("ses-boundary")
    messages = [
        {
            "session_id": session_id,
            "time_created_ms": to_ms("2026-04-21T09:00:00+00:00"),
        },
        {
            "session_id": session_id,
            "time_created_ms": to_ms("2026-04-21T09:10:00+00:00"),
        },
    ]

    bursts = extract_bursts(messages, gap_minutes=10)

    assert bursts == [
        Burst(
            start=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
            end=datetime(2026, 4, 21, 9, 10, tzinfo=timezone.utc),
            session_id=session_id,
        )
    ]


def test_extract_bursts_splits_when_gap_exceeds_boundary() -> None:
    session_id = hash_session_id("ses-split")
    messages = [
        {
            "session_id": session_id,
            "time_created_ms": to_ms("2026-04-21T09:00:00+00:00"),
        },
        {
            "session_id": session_id,
            "time_created_ms": to_ms("2026-04-21T09:11:00+00:00"),
        },
    ]

    bursts = extract_bursts(messages, gap_minutes=10)

    assert bursts == [
        Burst(
            start=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
            end=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
            session_id=session_id,
        ),
        Burst(
            start=datetime(2026, 4, 21, 9, 11, tzinfo=timezone.utc),
            end=datetime(2026, 4, 21, 9, 11, tzinfo=timezone.utc),
            session_id=session_id,
        ),
    ]


def test_extract_bursts_groups_each_session_independently() -> None:
    first_session = hash_session_id("ses-a")
    second_session = hash_session_id("ses-b")
    messages = [
        {
            "session_id": first_session,
            "time_created_ms": to_ms("2026-04-21T09:00:00+00:00"),
        },
        {
            "session_id": second_session,
            "time_created_ms": to_ms("2026-04-21T09:02:00+00:00"),
        },
        {
            "session_id": first_session,
            "time_created_ms": to_ms("2026-04-21T09:05:00+00:00"),
        },
        {
            "session_id": second_session,
            "time_created_ms": to_ms("2026-04-21T09:20:00+00:00"),
        },
    ]

    bursts = extract_bursts(messages, gap_minutes=10)

    assert bursts == [
        Burst(
            start=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
            end=datetime(2026, 4, 21, 9, 5, tzinfo=timezone.utc),
            session_id=first_session,
        ),
        Burst(
            start=datetime(2026, 4, 21, 9, 2, tzinfo=timezone.utc),
            end=datetime(2026, 4, 21, 9, 2, tzinfo=timezone.utc),
            session_id=second_session,
        ),
        Burst(
            start=datetime(2026, 4, 21, 9, 20, tzinfo=timezone.utc),
            end=datetime(2026, 4, 21, 9, 20, tzinfo=timezone.utc),
            session_id=second_session,
        ),
    ]


def test_extract_token_usage_supports_multiple_usage_shapes() -> None:
    messages = [
        {
            "role": "assistant",
            "model_id": "claude-sonnet-4.6",
            "usage": {"inputTokens": 100, "outputTokens": 25},
        },
        {
            "role": "assistant",
            "model_id": "gpt-5.4",
            "usage": {"input_tokens": 60, "output_tokens": 15},
        },
        {
            "role": "assistant",
            "model_id": "claude-sonnet-4.6",
            "metadata": {"usage": {"promptTokens": 40, "completionTokens": 10}},
        },
        {
            "role": "user",
            "model_id": "ignored",
            "usage": {"inputTokens": 999, "outputTokens": 1},
        },
    ]

    usage = extract_token_usage(messages)

    assert usage == {
        "total": 250,
        "by_model": {
            "claude-sonnet-4.6": 175,
            "gpt-5.4": 75,
        },
    }


def test_extract_token_usage_returns_zero_without_usage() -> None:
    usage = extract_token_usage(
        [{"role": "assistant", "model_id": "claude-sonnet-4.6"}, {"role": "tool"}]
    )

    assert usage == {"total": 0, "by_model": {}}
