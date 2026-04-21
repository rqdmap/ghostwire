from __future__ import annotations

import pathlib
from datetime import date

from aw_report.aggregate_dashboard import aggregate
from aw_report.models import Dashboard, HostSnapshot

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_snapshot(filename: str) -> HostSnapshot:
    return HostSnapshot.from_json((FIXTURES / filename).read_text())


def load_all_snapshots() -> list[HostSnapshot]:
    return [
        load_snapshot("snapshot-work-mac-2026-04-21.json"),
        load_snapshot("snapshot-home-arch-2026-04-21.json"),
        load_snapshot("snapshot-work-mac-2026-04-20.json"),
    ]


def test_aggregate_returns_dashboard_from_fixture_snapshots() -> None:
    dashboard = aggregate(load_all_snapshots(), today=date(2026, 4, 21))

    assert isinstance(dashboard, Dashboard)


def test_aggregate_builds_30_day_timeline() -> None:
    dashboard = aggregate(load_all_snapshots(), today=date(2026, 4, 21))

    assert len(dashboard.timeline_30d) == 30
    assert dashboard.timeline_30d[0].date == "2026-03-23"
    assert dashboard.timeline_30d[-1].date == "2026-04-21"


def test_aggregate_builds_application_summary_and_best_day() -> None:
    dashboard = aggregate(load_all_snapshots(), today=date(2026, 4, 21))

    assert len(dashboard.applications_30d) == 3
    assert [entry.category for entry in dashboard.applications_30d] == [
        "terminal",
        "browser",
        "other",
    ]
    assert dashboard.best_day is not None
    assert dashboard.best_day.date == "2026-04-21"
