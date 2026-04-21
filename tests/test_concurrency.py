import sys
from datetime import datetime, time, timedelta

import pytest

from ghostwire import concurrency
from ghostwire.concurrency import Burst, ConcurrencyMetrics, compute_concurrency


def burst(start: str, end: str, session_id: str):
    return Burst(
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        session_id=session_id,
    )


def test_empty_input_returns_zero_metrics() -> None:
    metrics = compute_concurrency([])

    assert metrics.avg_concurrent == 0.0
    assert metrics.peak_concurrent == 0
    assert metrics.return_median_seconds == 0.0
    assert metrics.daily_avg_7d == []


def test_single_burst_has_peak_one_and_average_one() -> None:
    metrics = compute_concurrency(
        [burst("2026-04-01T09:00:00+00:00", "2026-04-01T10:00:00+00:00", "s1")]
    )

    assert metrics.peak_concurrent == 1
    assert metrics.avg_concurrent == pytest.approx(1.0)
    assert metrics.return_median_seconds == 0.0
    assert metrics.daily_avg_7d == [pytest.approx(1.0)]


def test_two_overlapping_sessions_raise_peak_to_two() -> None:
    metrics = compute_concurrency(
        [
            burst("2026-04-01T09:00:00+00:00", "2026-04-01T10:00:00+00:00", "s1"),
            burst("2026-04-01T09:30:00+00:00", "2026-04-01T10:30:00+00:00", "s2"),
        ]
    )

    assert metrics.peak_concurrent == 2
    assert metrics.avg_concurrent == pytest.approx(4 / 3)


def test_non_overlapping_bursts_keep_peak_at_one() -> None:
    metrics = compute_concurrency(
        [
            burst("2026-04-01T09:00:00+00:00", "2026-04-01T10:00:00+00:00", "s1"),
            burst("2026-04-01T10:00:00+00:00", "2026-04-01T11:00:00+00:00", "s2"),
        ]
    )

    assert metrics.peak_concurrent == 1
    assert metrics.avg_concurrent == pytest.approx(1.0)


def test_weighted_average_is_not_simple_arithmetic_mean() -> None:
    bursts = [
        burst("2026-04-01T09:00:00+00:00", "2026-04-01T12:00:00+00:00", "s1"),
        burst("2026-04-01T10:00:00+00:00", "2026-04-01T10:15:00+00:00", "s1"),
        burst("2026-04-01T10:00:00+00:00", "2026-04-01T10:40:00+00:00", "s2"),
        burst("2026-04-01T10:00:00+00:00", "2026-04-01T11:00:00+00:00", "s3"),
    ]

    metrics = compute_concurrency(bursts)
    arithmetic_mean = (1 + 4 + 3 + 2 + 1) / 5

    assert metrics.avg_concurrent == pytest.approx(59 / 36)
    assert metrics.avg_concurrent != pytest.approx(arithmetic_mean)


def test_return_median_seconds_uses_session_return_gaps() -> None:
    metrics = compute_concurrency(
        [
            burst("2026-04-01T09:00:00+00:00", "2026-04-01T10:00:00+00:00", "s1"),
            burst("2026-04-01T10:30:00+00:00", "2026-04-01T11:00:00+00:00", "s1"),
            burst("2026-04-01T10:45:00+00:00", "2026-04-01T11:15:00+00:00", "s1"),
            burst("2026-04-01T12:00:00+00:00", "2026-04-01T12:15:00+00:00", "s1"),
        ]
    )

    assert metrics.return_median_seconds == pytest.approx(2250.0)


def test_peak_detection_handles_four_overlapping_bursts() -> None:
    metrics = compute_concurrency(
        [
            burst("2026-04-01T09:00:00+00:00", "2026-04-01T10:00:00+00:00", "a"),
            burst("2026-04-01T09:15:00+00:00", "2026-04-01T10:15:00+00:00", "b"),
            burst("2026-04-01T09:30:00+00:00", "2026-04-01T10:30:00+00:00", "c"),
            burst("2026-04-01T09:45:00+00:00", "2026-04-01T10:45:00+00:00", "d"),
        ]
    )

    assert metrics.peak_concurrent == 4


def test_daily_avg_7d_keeps_only_last_seven_days() -> None:
    start = datetime.fromisoformat("2026-04-01T09:00:00+00:00")
    bursts = [
        Burst(
            start=start + timedelta(days=day),
            end=start + timedelta(days=day, hours=1),
            session_id=f"s{day}",
        )
        for day in range(10)
    ]

    metrics = compute_concurrency(bursts)

    assert len(metrics.daily_avg_7d) == 7
    assert all(day_avg == pytest.approx(1.0) for day_avg in metrics.daily_avg_7d)


def test_daily_avg_7d_respects_custom_day_start() -> None:
    metrics = compute_concurrency(
        [burst("2026-04-01T05:30:00+00:00", "2026-04-01T06:30:00+00:00", "s1")],
        day_start=time(6, 0),
    )

    assert metrics.daily_avg_7d == [pytest.approx(1.0), pytest.approx(1.0)]


def test_seven_day_fixture_hits_expected_peak_and_average_range() -> None:
    start = datetime.fromisoformat("2026-04-01T00:00:00+00:00")
    bursts = []
    for day in range(7):
        day_start = start + timedelta(days=day)
        bursts.extend(
            [
                Burst(
                    start=day_start + timedelta(hours=9),
                    end=day_start + timedelta(hours=12),
                    session_id="session-a",
                ),
                Burst(
                    start=day_start + timedelta(hours=10),
                    end=day_start + timedelta(hours=10, minutes=15),
                    session_id="session-a",
                ),
                Burst(
                    start=day_start + timedelta(hours=10),
                    end=day_start + timedelta(hours=10, minutes=40),
                    session_id="session-b",
                ),
                Burst(
                    start=day_start + timedelta(hours=10),
                    end=day_start + timedelta(hours=11),
                    session_id="session-c",
                ),
            ]
        )

    metrics = compute_concurrency(bursts)

    assert metrics.peak_concurrent == 4
    assert 1.6 <= metrics.avg_concurrent <= 1.8
    assert len(metrics.daily_avg_7d) == 7
