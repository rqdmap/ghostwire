from __future__ import annotations

from datetime import date

from ghostwire.aggregate_dashboard import aggregate
from ghostwire.models import HostMeta, HostSnapshot, OpenCodeBurst, OpenCodeSession


def make_snapshot(
    *,
    host_id: str,
    date_str: str,
    label: str = "Home",
    platform: str = "Arch Linux",
    terminal: int = 0,
    browser: int = 0,
    other: int = 0,
    tokens_total: int = 0,
    by_model: list[dict] | None = None,
    sessions: list[OpenCodeSession] | None = None,
) -> HostSnapshot:
    total_seconds = terminal + browser + other
    return HostSnapshot(
        host=HostMeta(id=host_id, label=label, platform=platform),
        date=date_str,
        timezone="Asia/Shanghai",
        generated_at=f"{date_str}T23:59:59+08:00",
        active={
            "total_seconds": total_seconds,
            "by_category": {
                "terminal": terminal,
                "browser": browser,
                "other": other,
            },
        },
        applications=[],
        rhythm=[0] * 24,
        opencode={
            "tokens_total": tokens_total,
            "by_model": by_model or [],
            "sessions": sessions or [],
        },
    )


def test_aggregate_limits_window_summaries_to_last_30_days() -> None:
    today = date(2026, 4, 30)
    old_session = OpenCodeSession(
        session_id="old-session",
        bursts=[
            OpenCodeBurst(
                start="2026-03-01T09:00:00+08:00",
                end="2026-03-01T10:00:00+08:00",
            )
        ],
    )
    current_snapshot = make_snapshot(
        host_id="home-arch",
        date_str="2026-04-30",
        terminal=120,
        browser=30,
        other=0,
        tokens_total=55,
        by_model=[{"model": "gpt-5.4", "tokens": 55}],
    )
    old_snapshot = make_snapshot(
        host_id="home-arch",
        date_str="2026-03-01",
        terminal=999,
        browser=111,
        other=222,
        tokens_total=777,
        by_model=[{"model": "claude-opus-4.6", "tokens": 777}],
        sessions=[old_session],
    )

    dashboard = aggregate([current_snapshot, old_snapshot], today=today)

    assert dashboard.cards.workstations == [
        type(dashboard.cards.workstations[0])(
            label="Home",
            platform="Arch Linux",
            seconds=150,
        )
    ]
    assert dashboard.cards.session_load.avg_concurrent == 0.0
    assert dashboard.cards.session_load.peak_concurrent == 0
    assert dashboard.cards.session_load.return_median_seconds == 0
    assert dashboard.applications_30d[0].category == "terminal"
    assert dashboard.applications_30d[0].seconds == 120
    assert [entry.model for entry in dashboard.models_30d] == ["gpt-5.4"]
    assert dashboard.models_30d[0].tokens == 55


def test_aggregate_previous_window_includes_cutoff_day() -> None:
    today = date(2026, 4, 30)
    cutoff_day_snapshot = make_snapshot(
        host_id="home-arch",
        date_str="2026-03-31",
        terminal=100,
    )

    dashboard = aggregate([cutoff_day_snapshot], today=today)

    assert dashboard.cards.active_30d_seconds == 0
    assert dashboard.cards.active_30d_delta_pct == -100
