from __future__ import annotations

from datetime import date, timedelta

from aw_report.aggregate_dashboard import (
    build_timeline_30d,
    compute_delta_pct,
    compute_rhythm_7d,
)


def test_build_timeline_30d_returns_30_days_in_order() -> None:
    today = date(2026, 4, 21)
    merged_by_date = {
        "2026-03-23": {"by_category": {"terminal": 10, "browser": 20, "other": 30}},
        "2026-04-21": {
            "by_category": {"terminal": 40, "browser": 50, "other": 60},
            "opencode_tokens_total": 70,
        },
    }

    timeline = build_timeline_30d(merged_by_date, today)

    assert len(timeline) == 30
    assert timeline[0].date == "2026-03-23"
    assert timeline[-1].date == "2026-04-21"


def test_build_timeline_30d_zero_fills_missing_dates() -> None:
    today = date(2026, 4, 21)
    merged_by_date = {
        "2026-04-21": {"by_category": {"terminal": 7}, "opencode_tokens_total": 11}
    }

    timeline = build_timeline_30d(merged_by_date, today)

    assert timeline[0].terminal_seconds == 0
    assert timeline[0].browser_seconds == 0
    assert timeline[0].other_seconds == 0
    assert timeline[0].tokens == 0
    assert timeline[-1].terminal_seconds == 7
    assert timeline[-1].tokens == 11


def test_compute_delta_pct_handles_growth_and_zero_previous() -> None:
    assert compute_delta_pct(150, 100) == 50
    assert compute_delta_pct(10, 0) == 0


def test_compute_rhythm_7d_averages_available_days_only() -> None:
    today = date(2026, 4, 21)
    merged_by_date = {
        (today - timedelta(days=1)).isoformat(): {"rhythm": [60] * 24},
        (today - timedelta(days=3)).isoformat(): {"rhythm": [120] * 24},
        (today - timedelta(days=8)).isoformat(): {"rhythm": [999] * 24},
    }

    rhythm = compute_rhythm_7d(merged_by_date, today)

    assert len(rhythm) == 24
    assert rhythm == [90] * 24


def test_compute_rhythm_7d_returns_24_zeros_without_data() -> None:
    rhythm = compute_rhythm_7d({}, date(2026, 4, 21))

    assert rhythm == [0] * 24
