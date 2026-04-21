from __future__ import annotations

from datetime import date

from aw_report.aggregate_dashboard import (
    build_cards,
    compute_delta_pct,
    select_best_day,
)
from aw_report.concurrency import ConcurrencyMetrics
from aw_report.models import TimelineEntry


def make_timeline(days: list[tuple[str, int, int, int, int]]) -> list[TimelineEntry]:
    return [
        TimelineEntry(
            date=day,
            terminal_seconds=terminal,
            browser_seconds=browser,
            other_seconds=other,
            tokens=tokens,
        )
        for day, terminal, browser, other, tokens in days
    ]


def test_select_best_day_uses_total_active_seconds() -> None:
    timeline = make_timeline(
        [
            ("2026-04-19", 10, 20, 30, 100),
            ("2026-04-20", 50, 0, 0, 200),
            ("2026-04-21", 26, 25, 10, 300),
        ]
    )

    best = select_best_day(timeline)

    assert best.date == "2026-04-21"
    assert best.active_seconds == 61
    assert best.tokens == 300


def test_build_cards_sums_active_and_tokens_with_deltas() -> None:
    timeline_30d = make_timeline(
        [(f"2026-04-{day:02d}", 100, 50, 25, 10) for day in range(1, 31)]
    )
    timeline_prev_30d = make_timeline(
        [(f"2026-03-{day:02d}", 50, 25, 25, 5) for day in range(1, 31)]
    )
    cards = build_cards(
        timeline_30d=timeline_30d,
        timeline_prev_30d=timeline_prev_30d,
        concurrency=ConcurrencyMetrics(
            avg_concurrent=1.5,
            peak_concurrent=4,
            return_median_seconds=123.7,
            daily_avg_7d=[1.0] * 24,
        ),
        workstations=[
            {"label": "工作机", "platform": "macOS", "seconds": 1000},
            {"label": "家里机", "platform": "Arch Linux", "seconds": 2000},
        ],
        today=date(2026, 4, 21),
    )

    assert cards.active_30d_seconds == 5250
    assert cards.active_30d_delta_pct == 75
    assert cards.tokens_7d == 70
    assert cards.tokens_7d_delta_pct == 100


def test_build_cards_transfers_workstations_and_session_load() -> None:
    timeline_30d = make_timeline(
        [(f"2026-04-{day:02d}", 0, 0, 0, 0) for day in range(1, 31)]
    )
    cards = build_cards(
        timeline_30d=timeline_30d,
        timeline_prev_30d=timeline_30d,
        concurrency=ConcurrencyMetrics(
            avg_concurrent=2.25,
            peak_concurrent=5,
            return_median_seconds=1800,
            daily_avg_7d=[0.5, 1.5] + [2.0] * 22,
        ),
        workstations=[{"label": "工作机", "platform": "macOS", "seconds": 1234}],
        today=date(2026, 4, 21),
    )

    assert cards.workstations[0].label == "工作机"
    assert cards.workstations[0].platform == "macOS"
    assert cards.workstations[0].seconds == 1234
    assert cards.session_load.avg_concurrent == 2.25
    assert cards.session_load.peak_concurrent == 5
    assert cards.session_load.return_median_seconds == 1800
    assert cards.session_load.trend_7d == [0.5, 1.5] + [2.0] * 22


def test_compute_delta_pct_rounds_as_expected() -> None:
    assert compute_delta_pct(3, 2) == 50
    assert compute_delta_pct(5, 2) == 150
