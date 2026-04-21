from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from aw_report.cli import main
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


def make_dashboard() -> Dashboard:
    return Dashboard(
        generated_at="2026-04-21T10:00:00+08:00",
        range=DashboardRange(
            days=30,
            start="2026-03-23",
            end="2026-04-21",
            timezone="Asia/Shanghai",
        ),
        header=DashboardHeader(hosts_count=2, synced_at="2026-04-21T10:00:00+08:00"),
        cards=Cards(
            active_30d_seconds=154080,
            active_30d_delta_pct=12,
            tokens_7d=1820000,
            tokens_7d_delta_pct=8,
            workstations=[
                WorkstationEntry(label="工作机", platform="macOS", seconds=24480),
                WorkstationEntry(label="家里机", platform="Arch Linux", seconds=9360),
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
                date="2026-04-21",
                terminal_seconds=2400,
                browser_seconds=1800,
                other_seconds=930,
                tokens=42000,
            )
        ],
        best_day=BestDay(date="2026-04-21", active_seconds=5130, tokens=42000),
        applications_30d=[
            ApplicationEntry(category="terminal", label="终端", seconds=92520),
            ApplicationEntry(category="browser", label="浏览器", seconds=43200),
            ApplicationEntry(category="other", label="其他", seconds=18360),
        ],
        models_30d=[
            ModelEntry(model="claude-sonnet", tokens=98400000),
            ModelEntry(model="claude-opus", tokens=52100000),
            ModelEntry(model="gpt-4o", tokens=31700000),
        ],
        rhythm_7d=[0] * 24,
    )


def test_aggregate_and_render_help_show_options() -> None:
    runner = CliRunner()

    aggregate_help = runner.invoke(main, ["aggregate", "--help"])
    render_help = runner.invoke(main, ["render", "--help"])

    assert aggregate_help.exit_code == 0
    assert "--in" in aggregate_help.output
    assert "--out" in aggregate_help.output
    assert render_help.exit_code == 0
    assert "--in" in render_help.output
    assert "--out" in render_help.output


def test_aggregate_writes_dashboard_json(tmp_path: Path) -> None:
    runner = CliRunner()
    out_path = tmp_path / "dashboard.json"
    dashboard = make_dashboard()
    fixture_dir = Path(__file__).resolve().parent / "fixtures"

    with patch("aw_report.cli.aggregate", return_value=dashboard) as mock_aggregate:
        result = runner.invoke(
            main,
            [
                "aggregate",
                "--in",
                str(fixture_dir),
                "--out",
                str(out_path),
                "--today",
                "2026-04-21",
            ],
        )

    assert result.exit_code == 0
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["generated_at"] == dashboard.generated_at
    assert payload["header"] == {"hosts_count": 2, "synced_at": dashboard.generated_at}
    mock_aggregate.assert_called_once()
    assert len(mock_aggregate.call_args.args[0]) == 3
    assert mock_aggregate.call_args.kwargs["today"] == date(2026, 4, 21)


def test_render_writes_svg(tmp_path: Path) -> None:
    runner = CliRunner()
    in_path = tmp_path / "dashboard.json"
    out_path = tmp_path / "dashboard.svg"
    in_path.write_text(json.dumps(make_dashboard().to_json()), encoding="utf-8")

    with patch(
        "aw_report.cli.render_dashboard", return_value="<svg/>\n"
    ) as mock_render:
        result = runner.invoke(
            main,
            ["render", "--in", str(in_path), "--out", str(out_path)],
        )

    assert result.exit_code == 0
    assert out_path.read_text(encoding="utf-8") == "<svg/>\n"
    mock_render.assert_called_once()
