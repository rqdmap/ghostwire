from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from aw_report.cli import main
from aw_report.models import HostMeta, HostSnapshot


def make_config_file(tmp_path: Path) -> Path:
    config_path = tmp_path / "aw-report.toml"
    config_path.write_text(
        "\n".join(
            [
                "[general]",
                'timezone = "Asia/Shanghai"',
                "",
                "[host_meta.work-mac]",
                'label = "工作机"',
                'platform = "macOS"',
                "",
                "[host_meta.home-arch]",
                'label = "家里机"',
                'platform = "Arch Linux"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def make_snapshot() -> HostSnapshot:
    return HostSnapshot(
        host=HostMeta(id="work-mac", label="工作机", platform="macOS"),
        date="2026-04-21",
        timezone="Asia/Shanghai",
        generated_at="2026-04-21T10:00:00+08:00",
        active={
            "total_seconds": 3600,
            "by_category": {"terminal": 1800, "browser": 1200, "other": 600},
        },
        applications=[{"name": "Safari", "category": "browser", "seconds": 1200}],
        rhythm=[0] * 24,
        opencode={"tokens_total": 0, "by_model": [], "sessions": []},
    )


def test_snapshot_day_help_shows_options() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["snapshot", "day", "--help"])

    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--date" in result.output
    assert "--out" in result.output
    assert "--skip-opencode" in result.output


def test_snapshot_day_outputs_valid_json(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = make_config_file(tmp_path)
    snapshot = make_snapshot()

    with patch(
        "aw_report.cli.build_host_snapshot", return_value=snapshot
    ) as mock_build:
        result = runner.invoke(
            main,
            [
                "--config",
                str(config_path),
                "snapshot",
                "day",
                "--host",
                "work-mac",
                "--date",
                "2026-04-21",
                "--skip-opencode",
            ],
        )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["host"] == {"id": "work-mac", "label": "工作机", "platform": "macOS"}
    assert payload["date"] == "2026-04-21"
    assert payload["opencode"] == {"tokens_total": 0, "by_model": [], "sessions": []}
    mock_build.assert_called_once()
    host_meta = mock_build.call_args.kwargs["host_meta"]
    target_date = mock_build.call_args.kwargs["target_date"]
    opencode_sessions = mock_build.call_args.kwargs["opencode_sessions"]
    assert host_meta == HostMeta(id="work-mac", label="工作机", platform="macOS")
    assert target_date == date(2026, 4, 21)
    assert opencode_sessions is None


def test_snapshot_day_missing_host_exits_with_error(tmp_path: Path) -> None:
    runner = CliRunner()
    config_path = make_config_file(tmp_path)

    result = runner.invoke(
        main,
        [
            "--config",
            str(config_path),
            "snapshot",
            "day",
            "--host",
            "nonexistent",
        ],
    )

    assert result.exit_code == 1
    assert "host config not found: nonexistent" in result.output
