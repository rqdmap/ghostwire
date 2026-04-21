from __future__ import annotations

from datetime import date, datetime, time
from importlib import import_module
from unittest.mock import patch
from zoneinfo import ZoneInfo

from ghostwire.config import Config
from ghostwire.models import HostMeta

hash_session_id = import_module("ghostwire.sanitize").hash_session_id
build_host_snapshot = import_module("ghostwire.snapshot").build_host_snapshot


def make_config() -> Config:
    return Config(
        timezone=ZoneInfo("Asia/Shanghai"),
        categorize_terminal=["WezTerm", "Neovim"],
        categorize_browser=["Safari"],
    )


def make_events() -> list[dict]:
    return [
        {
            "timestamp": "2026-04-21T09:15:00+08:00",
            "duration": 600,
            "data": {"app": "WezTerm", "title": "hidden terminal title"},
        },
        {
            "timestamp": "2026-04-21T09:45:00+08:00",
            "duration": 1200,
            "data": {"app": "Safari", "title": "hidden browser title"},
        },
        {
            "timestamp": "2026-04-21T10:05:00+08:00",
            "duration": 300,
            "data": {"app": "Slack", "title": "private chat"},
        },
        {
            "timestamp": "2026-04-21T10:25:00+08:00",
            "duration": 900,
            "data": {"app": "Neovim", "title": "secret file"},
        },
    ]


def make_opencode_sessions() -> list[dict]:
    return [
        {
            "session_id": "ses_raw_1",
            "model": "claude-sonnet",
            "tokens_total": 1200,
            "bursts": [
                {
                    "start": "2026-04-21T09:00:00+08:00",
                    "end": "2026-04-21T09:30:00+08:00",
                }
            ],
        },
        {
            "session_id": "ses_raw_2",
            "model": "gpt-4o",
            "tokens_total": 800,
            "bursts": [
                {
                    "start": "2026-04-21T11:00:00+08:00",
                    "end": "2026-04-21T11:10:00+08:00",
                }
            ],
        },
    ]


def build_snapshot(opencode_sessions=None):
    config = make_config()
    host_meta = HostMeta(id="work-mac-2024", label="工作机", platform="macOS")
    mock_buckets = {
        "work-mac-2024": {
            "window_bucket": "aw-watcher-window_work-mac-2024",
            "afk_bucket": "aw-watcher-afk_work-mac-2024",
        }
    }

    with (
        patch(
            "ghostwire.snapshot.discover_host_buckets", return_value=mock_buckets
        ) as mock_discover,
        patch(
            "ghostwire.snapshot.collect_active_windows",
            return_value=(make_events(), 3000, 0),
        ) as mock_collect,
        patch(
            "ghostwire.snapshot.sanitize_snapshot",
            side_effect=lambda payload: payload,
        ) as mock_sanitize,
        patch("ghostwire.snapshot.build_daily_opencode", return_value=[]),
    ):
        snapshot = build_host_snapshot(
            client=object(),
            host_meta=host_meta,
            config=config,
            target_date=date(2026, 4, 21),
            opencode_sessions=opencode_sessions,
        )

    return snapshot, mock_discover, mock_collect, mock_sanitize


def test_build_host_snapshot_uses_aw_collectors_with_day_window() -> None:
    snapshot, mock_discover, mock_collect, _ = build_snapshot(make_opencode_sessions())

    assert snapshot.date == "2026-04-21"
    mock_discover.assert_called_once()
    mock_collect.assert_called_once()
    _, window_bucket, afk_bucket, start, end = mock_collect.call_args.args
    assert window_bucket == "aw-watcher-window_work-mac-2024"
    assert afk_bucket == "aw-watcher-afk_work-mac-2024"
    assert start == datetime(2026, 4, 21, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert end == datetime(2026, 4, 22, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_build_host_snapshot_respects_configured_day_start() -> None:
    config = Config(
        timezone=ZoneInfo("Asia/Shanghai"),
        day_start=time(6, 0),
        categorize_terminal=["WezTerm", "Neovim"],
        categorize_browser=["Safari"],
    )
    host_meta = HostMeta(id="work-mac-2024", label="工作机", platform="macOS")
    mock_buckets = {
        "work-mac-2024": {
            "window_bucket": "aw-watcher-window_work-mac-2024",
            "afk_bucket": "aw-watcher-afk_work-mac-2024",
        }
    }

    with (
        patch("ghostwire.snapshot.discover_host_buckets", return_value=mock_buckets),
        patch(
            "ghostwire.snapshot.collect_active_windows",
            return_value=(make_events(), 3000, 0),
        ) as mock_collect,
        patch("ghostwire.snapshot.sanitize_snapshot", side_effect=lambda payload: payload),
        patch("ghostwire.snapshot.build_daily_opencode", return_value=[]),
    ):
        build_host_snapshot(
            client=object(),
            host_meta=host_meta,
            config=config,
            target_date=date(2026, 4, 21),
            opencode_sessions=[],
        )

    _, _, _, start, end = mock_collect.call_args.args
    assert start == datetime(2026, 4, 21, 6, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert end == datetime(2026, 4, 22, 6, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_rhythm_has_24_elements_and_buckets_seconds_by_hour() -> None:
    snapshot, _, _, _ = build_snapshot(make_opencode_sessions())

    assert len(snapshot.rhythm) == 24
    assert snapshot.rhythm[9] == 1800
    assert snapshot.rhythm[10] == 1200
    assert sum(snapshot.rhythm) == 3000


def test_by_category_sums_match_total_seconds() -> None:
    snapshot, _, _, _ = build_snapshot(make_opencode_sessions())

    assert snapshot.active["by_category"] == {
        "terminal": 1500,
        "browser": 1200,
        "other": 300,
    }
    assert (
        sum(snapshot.active["by_category"].values()) == snapshot.active["total_seconds"]
    )


def test_applications_list_excludes_non_allowlisted_apps() -> None:
    snapshot, _, _, _ = build_snapshot(make_opencode_sessions())

    assert snapshot.applications == [
        {"name": "Safari", "category": "browser", "seconds": 1200},
        {"name": "Neovim", "category": "terminal", "seconds": 900},
        {"name": "WezTerm", "category": "terminal", "seconds": 600},
    ]
    assert all(app["name"] != "Slack" for app in snapshot.applications)


def test_sanitize_snapshot_is_called() -> None:
    _, _, _, mock_sanitize = build_snapshot(make_opencode_sessions())

    mock_sanitize.assert_called_once()


def test_build_host_snapshot_returns_empty_opencode_when_not_provided() -> None:
    snapshot, _, _, _ = build_snapshot()

    assert snapshot.opencode == {"tokens_total": 0, "by_model": [], "sessions": []}


def test_build_host_snapshot_aggregates_opencode_and_hashes_session_ids() -> None:
    snapshot, _, _, _ = build_snapshot(make_opencode_sessions())

    assert snapshot.opencode["tokens_total"] == 2000
    assert snapshot.opencode["by_model"] == [
        {"model": "claude-sonnet", "tokens": 1200},
        {"model": "gpt-4o", "tokens": 800},
    ]
    assert [session.session_id for session in snapshot.opencode["sessions"]] == [
        hash_session_id("ses_raw_1"),
        hash_session_id("ses_raw_2"),
    ]
