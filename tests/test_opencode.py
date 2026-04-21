import json
import importlib.util
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


concurrency = load_module("ghostwire.concurrency", "ghostwire/concurrency.py")
sanitize = load_module("ghostwire.sanitize", "ghostwire/sanitize.py")
opencode = load_module("ghostwire.opencode", "ghostwire/opencode.py")

Burst = concurrency.Burst
OPENCODE_DB = opencode.OPENCODE_DB
extract_bursts = opencode.extract_bursts
build_daily_opencode = opencode.build_daily_opencode
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
        completed_ms = (payload.get("time") or {}).get("completed")
        time_updated = int(completed_ms) if completed_ms is not None else int(created_ms)
        connection.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
            (
                f"msg-{index}",
                session_id,
                created_ms,
                time_updated,
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
    user_created = to_ms("2026-04-21T09:00:00+00:00")
    asst_created = to_ms("2026-04-21T09:03:00+00:00")
    asst_completed = to_ms("2026-04-21T09:03:45+00:00")
    connection = build_connection(
        [
            (
                raw_session_id,
                user_created,
                {
                    "role": "user",
                    "time": {"created": user_created},
                    "model": {
                        "providerID": "github-copilot",
                        "modelID": "claude-sonnet-4.6",
                    },
                    "content": [{"type": "text", "text": "secret"}],
                },
            ),
            (
                raw_session_id,
                asst_created,
                {
                    "role": "assistant",
                    "time": {"created": asst_created, "completed": asst_completed},
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
                    "time_created_ms": user_created,
                    "time_ended_ms": user_created,
                    "model_id": "claude-sonnet-4.6",
                    "provider_id": "github-copilot",
                },
                {
                    "session_id": hash_session_id(raw_session_id),
                    "role": "assistant",
                    "time_created_ms": asst_created,
                    "time_ended_ms": asst_completed,
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


def test_read_sessions_supports_custom_reporting_window(
    monkeypatch, tmp_path
) -> None:
    target_day = date(2026, 4, 21)
    sh_tz = timezone(timedelta(hours=8))
    raw_session_id = "ses-custom-window"
    connection = build_connection(
        [
            (
                raw_session_id,
                to_ms("2026-04-22T00:30:00+08:00"),
                {
                    "role": "user",
                    "time": {"created": to_ms("2026-04-22T00:30:00+08:00")},
                },
            ),
            (
                raw_session_id,
                to_ms("2026-04-22T06:01:00+08:00"),
                {
                    "role": "user",
                    "time": {"created": to_ms("2026-04-22T06:01:00+08:00")},
                },
            ),
        ]
    )
    db_path = tmp_path / "mock.db"
    db_path.touch()
    monkeypatch.setattr(opencode.sqlite3, "connect", lambda _: connection)

    sessions = read_sessions(
        target_day,
        db_path=db_path,
        window_start=datetime(2026, 4, 21, 6, 0, tzinfo=sh_tz),
        window_end=datetime(2026, 4, 22, 6, 0, tzinfo=sh_tz),
    )

    assert sessions == [
        {
            "session_id": hash_session_id(raw_session_id),
            "messages": [
                {
                    "session_id": hash_session_id(raw_session_id),
                    "role": "user",
                    "time_created_ms": to_ms("2026-04-22T00:30:00+08:00"),
                    "time_ended_ms": to_ms("2026-04-22T00:30:00+08:00"),
                    "model_id": None,
                    "provider_id": None,
                }
            ],
        }
    ]


def test_extract_bursts_keeps_boundary_gap_in_same_burst() -> None:
    session_id = hash_session_id("ses-boundary")
    messages = [
        {
            "session_id": session_id,
            "role": "assistant",
            "time_created_ms": to_ms("2026-04-21T09:00:00+00:00"),
            "time_ended_ms": to_ms("2026-04-21T09:00:30+00:00"),
        },
        {
            "session_id": session_id,
            "role": "assistant",
            "time_created_ms": to_ms("2026-04-21T09:10:00+00:00"),
            "time_ended_ms": to_ms("2026-04-21T09:10:30+00:00"),
        },
    ]

    bursts = extract_bursts(messages, gap_minutes=10)

    assert bursts == [
        Burst(
            start=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
            end=datetime(2026, 4, 21, 9, 10, 30, tzinfo=timezone.utc),
            session_id=session_id,
        )
    ]


def test_extract_bursts_splits_when_gap_exceeds_boundary() -> None:
    session_id = hash_session_id("ses-split")
    messages = [
        {
            "session_id": session_id,
            "role": "assistant",
            "time_created_ms": to_ms("2026-04-21T09:00:00+00:00"),
            "time_ended_ms": to_ms("2026-04-21T09:00:30+00:00"),
        },
        {
            "session_id": session_id,
            "role": "assistant",
            "time_created_ms": to_ms("2026-04-21T09:11:00+00:00"),
            "time_ended_ms": to_ms("2026-04-21T09:11:30+00:00"),
        },
    ]

    bursts = extract_bursts(messages, gap_minutes=10)

    assert bursts == [
        Burst(
            start=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
            end=datetime(2026, 4, 21, 9, 0, 30, tzinfo=timezone.utc),
            session_id=session_id,
        ),
        Burst(
            start=datetime(2026, 4, 21, 9, 11, tzinfo=timezone.utc),
            end=datetime(2026, 4, 21, 9, 11, 30, tzinfo=timezone.utc),
            session_id=session_id,
        ),
    ]


def test_extract_bursts_groups_each_session_independently() -> None:
    first_session = hash_session_id("ses-a")
    second_session = hash_session_id("ses-b")
    messages = [
        {
            "session_id": first_session,
            "role": "assistant",
            "time_created_ms": to_ms("2026-04-21T09:00:00+00:00"),
            "time_ended_ms": to_ms("2026-04-21T09:01:00+00:00"),
        },
        {
            "session_id": second_session,
            "role": "assistant",
            "time_created_ms": to_ms("2026-04-21T09:02:00+00:00"),
            "time_ended_ms": to_ms("2026-04-21T09:03:00+00:00"),
        },
        {
            "session_id": first_session,
            "role": "assistant",
            "time_created_ms": to_ms("2026-04-21T09:05:00+00:00"),
            "time_ended_ms": to_ms("2026-04-21T09:06:00+00:00"),
        },
        {
            "session_id": second_session,
            "role": "assistant",
            "time_created_ms": to_ms("2026-04-21T09:20:00+00:00"),
            "time_ended_ms": to_ms("2026-04-21T09:21:00+00:00"),
        },
    ]

    bursts = extract_bursts(messages, gap_minutes=10)

    assert bursts == [
        Burst(
            start=datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc),
            end=datetime(2026, 4, 21, 9, 6, tzinfo=timezone.utc),
            session_id=first_session,
        ),
        Burst(
            start=datetime(2026, 4, 21, 9, 2, tzinfo=timezone.utc),
            end=datetime(2026, 4, 21, 9, 3, tzinfo=timezone.utc),
            session_id=second_session,
        ),
        Burst(
            start=datetime(2026, 4, 21, 9, 20, tzinfo=timezone.utc),
            end=datetime(2026, 4, 21, 9, 21, tzinfo=timezone.utc),
            session_id=second_session,
        ),
    ]


def test_extract_bursts_ignores_user_messages_without_completed() -> None:
    session_id = hash_session_id("ses-user-only")
    messages = [
        {
            "session_id": session_id,
            "role": "user",
            "time_created_ms": to_ms("2026-04-21T09:00:00+00:00"),
            "time_ended_ms": to_ms("2026-04-21T09:00:00+00:00"),
        },
    ]

    assert extract_bursts(messages, gap_minutes=10) == []


def test_extract_bursts_drops_assistant_without_observed_end() -> None:
    session_id = hash_session_id("ses-incomplete")
    messages = [
        {
            "session_id": session_id,
            "role": "assistant",
            "time_created_ms": to_ms("2026-04-21T09:00:00+00:00"),
            "time_ended_ms": to_ms("2026-04-21T09:00:00+00:00"),
        },
    ]

    assert extract_bursts(messages, gap_minutes=10) == []


def test_extract_bursts_respects_configurable_gap_minutes() -> None:
    session_id = hash_session_id("ses-gap")
    messages = [
        {
            "session_id": session_id,
            "role": "assistant",
            "time_created_ms": to_ms("2026-04-21T09:00:00+00:00"),
            "time_ended_ms": to_ms("2026-04-21T09:00:30+00:00"),
        },
        {
            "session_id": session_id,
            "role": "assistant",
            "time_created_ms": to_ms("2026-04-21T09:04:00+00:00"),
            "time_ended_ms": to_ms("2026-04-21T09:04:30+00:00"),
        },
    ]

    short_gap = extract_bursts(messages, gap_minutes=2)
    long_gap = extract_bursts(messages, gap_minutes=10)

    assert len(short_gap) == 2
    assert len(long_gap) == 1


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


def test_build_daily_opencode_preserves_exact_per_session_model_breakdown(
    monkeypatch, tmp_path
) -> None:
    raw_session_id = "ses-mixed-models"
    connection = build_connection(
        [
            (
                raw_session_id,
                to_ms("2026-04-21T09:00:00+00:00"),
                {
                    "role": "assistant",
                    "time": {
                        "created": to_ms("2026-04-21T09:00:00+00:00"),
                        "completed": to_ms("2026-04-21T09:00:30+00:00"),
                    },
                    "modelID": "claude-sonnet-4.6",
                    "metadata": {"usage": {"inputTokens": 100, "outputTokens": 20}},
                },
            ),
            (
                raw_session_id,
                to_ms("2026-04-21T09:05:00+00:00"),
                {
                    "role": "assistant",
                    "time": {
                        "created": to_ms("2026-04-21T09:05:00+00:00"),
                        "completed": to_ms("2026-04-21T09:05:30+00:00"),
                    },
                    "modelID": "gpt-5.4",
                    "metadata": {"usage": {"inputTokens": 50, "outputTokens": 10}},
                },
            ),
        ]
    )
    db_path = tmp_path / "mock.db"
    db_path.touch()
    monkeypatch.setattr(opencode.sqlite3, "connect", lambda _: connection)

    sessions = build_daily_opencode(date(2026, 4, 21), db_path=db_path)

    assert sessions == [
        {
            "session_id": hash_session_id(raw_session_id),
            "model": "claude-sonnet-4.6",
            "tokens_total": 180,
            "by_model": [
                {"model": "claude-sonnet-4.6", "tokens": 120},
                {"model": "gpt-5.4", "tokens": 60},
            ],
            "bursts": [
                {
                    "start": "2026-04-21T09:00:00+00:00",
                    "end": "2026-04-21T09:05:30+00:00",
                }
            ],
        }
    ]


def test_extract_token_usage_returns_zero_without_usage() -> None:
    usage = extract_token_usage(
        [{"role": "assistant", "model_id": "claude-sonnet-4.6"}, {"role": "tool"}]
    )

    assert usage == {"total": 0, "by_model": {}}


def _build_connection_with_parts(
    rows: list[tuple[str, int, dict, list[tuple[int, int]]]],
) -> sqlite3.Connection:
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
    connection.execute(
        """
        CREATE TABLE part (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL
        )
        """
    )
    for index, (session_id, created_ms, payload, parts) in enumerate(rows, start=1):
        message_id = f"msg-{index}"
        completed_ms = (payload.get("time") or {}).get("completed")
        time_updated = int(completed_ms) if completed_ms is not None else int(created_ms)
        connection.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            (
                message_id,
                session_id,
                created_ms,
                time_updated,
                json.dumps(payload),
            ),
        )
        for part_index, (part_created, part_updated) in enumerate(parts, start=1):
            connection.execute(
                "INSERT INTO part VALUES (?, ?, ?, ?)",
                (
                    f"prt-{index}-{part_index}",
                    message_id,
                    part_created,
                    part_updated,
                ),
            )
    connection.commit()
    return connection


def test_read_sessions_falls_back_to_part_time_when_completed_missing(
    monkeypatch, tmp_path
) -> None:
    raw_session_id = "ses-fallback-part"
    created = to_ms("2026-04-21T09:00:00+00:00")
    last_part = to_ms("2026-04-21T09:01:30+00:00")
    connection = _build_connection_with_parts(
        [
            (
                raw_session_id,
                created,
                {
                    "role": "assistant",
                    "time": {"created": created},
                    "modelID": "claude-sonnet-4.6",
                },
                [
                    (created + 1_000, created + 1_000),
                    (created + 30_000, last_part),
                ],
            ),
        ]
    )
    db_path = tmp_path / "mock.db"
    db_path.touch()
    monkeypatch.setattr(opencode.sqlite3, "connect", lambda _: connection)

    sessions = read_sessions(date(2026, 4, 21), db_path=db_path)

    assert sessions[0]["messages"][0]["time_ended_ms"] == last_part


def test_read_sessions_falls_back_to_message_time_updated_when_no_parts(
    monkeypatch, tmp_path
) -> None:
    raw_session_id = "ses-fallback-updated"
    created = to_ms("2026-04-21T09:00:00+00:00")
    updated = to_ms("2026-04-21T09:00:45+00:00")
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
    payload = {
        "role": "assistant",
        "time": {"created": created},
        "modelID": "claude-sonnet-4.6",
    }
    connection.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
        ("m1", raw_session_id, created, updated, json.dumps(payload)),
    )
    connection.commit()

    db_path = tmp_path / "mock.db"
    db_path.touch()
    monkeypatch.setattr(opencode.sqlite3, "connect", lambda _: connection)

    sessions = read_sessions(date(2026, 4, 21), db_path=db_path)

    assert sessions[0]["messages"][0]["time_ended_ms"] == updated


def test_build_daily_opencode_threads_burst_gap_minutes(monkeypatch, tmp_path) -> None:
    raw_session_id = "ses-gap-config"
    base = to_ms("2026-04-21T09:00:00+00:00")
    payload_a = {
        "role": "assistant",
        "time": {"created": base, "completed": base + 30_000},
        "modelID": "gpt-5.4",
        "metadata": {"usage": {"inputTokens": 10, "outputTokens": 5}},
    }
    later = base + 4 * 60 * 1000
    payload_b = {
        "role": "assistant",
        "time": {"created": later, "completed": later + 30_000},
        "modelID": "gpt-5.4",
        "metadata": {"usage": {"inputTokens": 10, "outputTokens": 5}},
    }

    rows = [
        (raw_session_id, base, payload_a),
        (raw_session_id, later, payload_b),
    ]
    real_connect = opencode.sqlite3.connect
    db_path = tmp_path / "mock.db"
    db_path.touch()

    def make_connection(_path):
        connection = real_connect(":memory:")
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
            completed_ms = (payload.get("time") or {}).get("completed")
            time_updated = int(completed_ms) if completed_ms is not None else int(created_ms)
            connection.execute(
                "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
                (
                    f"msg-{index}",
                    session_id,
                    created_ms,
                    time_updated,
                    json.dumps(payload),
                ),
            )
        connection.commit()
        return connection

    monkeypatch.setattr(opencode.sqlite3, "connect", make_connection)

    short = build_daily_opencode(
        date(2026, 4, 21), db_path=db_path, burst_gap_minutes=2
    )
    long = build_daily_opencode(
        date(2026, 4, 21), db_path=db_path, burst_gap_minutes=10
    )

    assert len(short[0]["bursts"]) == 2
    assert len(long[0]["bursts"]) == 1
