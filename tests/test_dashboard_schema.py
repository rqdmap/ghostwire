from __future__ import annotations

import pytest

from aw_report.models import (
    ApplicationEntry,
    BestDay,
    Cards,
    Dashboard,
    DashboardHeader,
    DashboardRange,
    ModelEntry,
    SessionLoad,
    TimelineEntry,
    WorkstationEntry,
)


def build_dashboard() -> Dashboard:
    return Dashboard(
        generated_at="2026-04-22T03:00:00+08:00",
        range=DashboardRange(
            days=30, start="2026-03-23", end="2026-04-21", timezone="Asia/Shanghai"
        ),
        header=DashboardHeader(hosts_count=2, synced_at="2026-04-21T08:00:00+08:00"),
        cards=Cards(
            active_30d_seconds=154080,
            active_30d_delta_pct=9,
            tokens_7d=1820000,
            tokens_7d_delta_pct=28,
            workstations=[
                WorkstationEntry(label="工作机", platform="macOS", seconds=69840),
                WorkstationEntry(label="家里机", platform="Arch Linux", seconds=33120),
            ],
            session_load=SessionLoad(
                avg_concurrent=1.7,
                peak_concurrent=4,
                return_median_seconds=1080,
                trend_7d=[1.4, 1.8, 2.1, 0.8, 1.3, 2.6, 1.5],
            ),
        ),
        timeline_30d=[
            TimelineEntry(
                date="2026-03-23",
                terminal_seconds=7200,
                browser_seconds=4800,
                other_seconds=2160,
                tokens=230000,
            )
        ],
        best_day=BestDay(date="2026-04-19", active_seconds=24480, tokens=541000),
        applications_30d=[
            ApplicationEntry(category="terminal", label="终端", seconds=92520)
        ],
        models_30d=[ModelEntry(model="claude-sonnet", tokens=98400000)],
        rhythm_7d=[
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            120,
            1800,
            2400,
            2700,
            1900,
            1500,
            2100,
            2700,
            2400,
            1800,
            1200,
            2100,
            2700,
            3000,
            3300,
            3540,
            1500,
        ],
    )


def test_roundtrip_json_dict() -> None:
    dashboard = build_dashboard()

    assert Dashboard.from_json(dashboard.to_json()) == dashboard


def test_validate_passes() -> None:
    dashboard = build_dashboard()

    dashboard.validate()


def test_validate_rejects_host_id() -> None:
    payload = build_dashboard().to_json()
    payload["cards"]["workstations"][0]["label"] = "host_id"

    with pytest.raises(ValueError, match="host_id"):
        Dashboard.from_json(payload).validate()


def test_validate_rejects_session_id() -> None:
    payload = build_dashboard().to_json()
    payload["best_day"]["date"] = "session_id"

    with pytest.raises(ValueError, match="session_id"):
        Dashboard.from_json(payload).validate()


def test_validate_rejects_hostname() -> None:
    payload = build_dashboard().to_json()
    payload["header"]["synced_at"] = "hostname"

    with pytest.raises(ValueError, match="hostname"):
        Dashboard.from_json(payload).validate()


def test_validate_rejects_bad_rhythm_length() -> None:
    dashboard = build_dashboard()
    dashboard.rhythm_7d = dashboard.rhythm_7d[:-1]

    with pytest.raises(ValueError, match="24"):
        dashboard.validate()
