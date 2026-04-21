"""Fork-dedupe regression: mirror mimir's TestForkDedup case.

session-1 has the original (user, assistant) pair.  session-2 forks and
re-copies that same pair (same time_created_ms, same role) and adds one
extra follow-up turn.  Tokens must be 150, not 250.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load("ghostwire.concurrency", "ghostwire/concurrency.py")
_load("ghostwire.sanitize", "ghostwire/sanitize.py")
opencode = _load("ghostwire.opencode", "ghostwire/opencode.py")


def _ts(iso: str) -> int:
    from datetime import datetime

    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def _build_db(messages: list[tuple[str, int, int, dict]]) -> sqlite3.Connection:
    """messages = list[(session_id, session_created_ms, msg_created_ms, payload)]"""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session (id TEXT PRIMARY KEY, time_created INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, "
        "time_created INTEGER, data TEXT)"
    )
    seen_sessions: dict[str, int] = {}
    for idx, (sid, sess_ts, msg_ts, payload) in enumerate(messages, start=1):
        if sid not in seen_sessions:
            conn.execute(
                "INSERT INTO session(id, time_created) VALUES (?, ?)", (sid, sess_ts)
            )
            seen_sessions[sid] = sess_ts
        conn.execute(
            "INSERT INTO message(id, session_id, time_created, data) VALUES (?,?,?,?)",
            (f"m-{idx}", sid, msg_ts, json.dumps(payload)),
        )
    conn.commit()
    return conn


def test_fork_duplicate_messages_are_not_double_counted(monkeypatch, tmp_path):
    user_ts = _ts("2026-04-21T09:00:00+00:00")
    asst_ts = _ts("2026-04-21T09:01:00+00:00")
    fork_extra_user_ts = _ts("2026-04-21T10:00:00+00:00")
    fork_extra_asst_ts = _ts("2026-04-21T10:01:00+00:00")

    user_msg = {
        "role": "user",
        "time": {"created": user_ts},
    }
    asst_msg = {
        "role": "assistant",
        "modelID": "claude-sonnet-4-5",
        "providerID": "anthropic",
        "time": {"created": asst_ts},
        "tokens": {"input": 100, "output": 20},
    }
    fork_extra_user = {"role": "user", "time": {"created": fork_extra_user_ts}}
    fork_extra_asst = {
        "role": "assistant",
        "modelID": "claude-sonnet-4-5",
        "providerID": "anthropic",
        "time": {"created": fork_extra_asst_ts},
        "tokens": {"input": 50, "output": 10},
    }

    conn = _build_db(
        [
            ("session-1", 100, user_ts, user_msg),
            ("session-1", 100, asst_ts, asst_msg),
            ("session-2", 200, user_ts, user_msg),
            ("session-2", 200, asst_ts, asst_msg),
            ("session-2", 200, fork_extra_user_ts, fork_extra_user),
            ("session-2", 200, fork_extra_asst_ts, fork_extra_asst),
        ]
    )

    db_file = tmp_path / "fake.db"
    db_file.touch()
    monkeypatch.setattr(opencode.sqlite3, "connect", lambda _: conn)

    sessions = opencode.read_sessions(date(2026, 4, 21), db_path=db_file)

    by_hashed = {s["session_id"]: s for s in sessions}
    assert len(by_hashed) == 2

    flat_messages = [m for s in sessions for m in s["messages"]]
    usage = opencode.extract_token_usage(flat_messages)

    assert usage["total"] == 180, (
        f"expected 100+20 (original) + 50+10 (fork unique) = 180, got {usage['total']}"
    )

    s1_hash = opencode.hash_session_id("session-1")
    s2_hash = opencode.hash_session_id("session-2")
    s1_assistant = [
        m for m in by_hashed[s1_hash]["messages"] if m["role"] == "assistant"
    ]
    s2_assistant = [
        m for m in by_hashed[s2_hash]["messages"] if m["role"] == "assistant"
    ]
    assert len(s1_assistant) == 1, "original session-1 keeps its 1 assistant"
    assert len(s2_assistant) == 1, "fork session-2 keeps only the unique follow-up"
    assert s2_assistant[0]["time_created_ms"] == fork_extra_asst_ts


def test_build_daily_opencode_uses_deduped_messages(monkeypatch, tmp_path):
    user_ts = _ts("2026-04-21T09:00:00+00:00")
    asst_ts = _ts("2026-04-21T09:01:00+00:00")
    payload_user = {"role": "user", "time": {"created": user_ts}}
    payload_asst = {
        "role": "assistant",
        "modelID": "claude-sonnet-4-5",
        "time": {"created": asst_ts},
        "tokens": {"input": 100, "output": 20},
    }

    conn = _build_db(
        [
            ("session-1", 100, user_ts, payload_user),
            ("session-1", 100, asst_ts, payload_asst),
            ("session-2", 200, user_ts, payload_user),
            ("session-2", 200, asst_ts, payload_asst),
        ]
    )

    db_file = tmp_path / "fake.db"
    db_file.touch()
    monkeypatch.setattr(opencode.sqlite3, "connect", lambda _: conn)

    sessions = opencode.build_daily_opencode(date(2026, 4, 21), db_path=db_file)

    total_tokens = sum(s["tokens_total"] for s in sessions)
    assert total_tokens == 120, (
        f"deduped total should be 120 (one assistant kept), got {total_tokens}"
    )
