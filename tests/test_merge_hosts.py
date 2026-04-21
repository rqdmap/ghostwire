from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import pytest

from aw_report.aggregate_dashboard import merge_host_snapshots, merge_snapshots_by_date
from aw_report.concurrency import Burst
from aw_report.models import HostMeta, HostSnapshot, OpenCodeBurst, OpenCodeSession

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_snapshot(filename: str) -> HostSnapshot:
    return HostSnapshot.from_json((FIXTURES / filename).read_text())


def make_snapshot(
    date: str = "2026-04-21",
    label: str = "test-host",
    platform: str = "Linux",
    total_seconds: int = 1000,
    terminal: int = 600,
    browser: int = 300,
    other: int = 100,
    applications: list[dict] | None = None,
    rhythm: list[int] | None = None,
    tokens_total: int = 0,
    by_model: list[dict] | None = None,
    sessions: list[OpenCodeSession] | None = None,
) -> HostSnapshot:
    return HostSnapshot(
        host=HostMeta(id="test-id", label=label, platform=platform),
        date=date,
        timezone="UTC",
        generated_at="2026-04-22T00:00:00+00:00",
        active={
            "total_seconds": total_seconds,
            "by_category": {"terminal": terminal, "browser": browser, "other": other},
        },
        applications=applications or [],
        rhythm=rhythm or [0] * 24,
        opencode={
            "tokens_total": tokens_total,
            "by_model": by_model or [],
            "sessions": sessions or [],
        },
    )


class TestActiveTotals:
    def test_active_seconds_summed_across_hosts(self):
        s1 = make_snapshot(total_seconds=24480)
        s2 = make_snapshot(total_seconds=9360)
        result = merge_host_snapshots([s1, s2])
        assert result["active_total_seconds"] == 33840

    def test_by_category_summed_correctly(self):
        s1 = make_snapshot(terminal=15120, browser=7560, other=1800)
        s2 = make_snapshot(terminal=5760, browser=2880, other=720)
        result = merge_host_snapshots([s1, s2])
        assert result["by_category"] == {
            "terminal": 20880,
            "browser": 10440,
            "other": 2520,
        }

    def test_single_snapshot_passthrough(self):
        s = make_snapshot(total_seconds=5000, terminal=3000, browser=1500, other=500)
        result = merge_host_snapshots([s])
        assert result["active_total_seconds"] == 5000
        assert result["by_category"]["terminal"] == 3000


class TestApplicationsMerge:
    def test_same_app_on_both_hosts_merged(self):
        apps1 = [{"name": "Alacritty", "category": "terminal", "seconds": 9600}]
        apps2 = [{"name": "Alacritty", "category": "terminal", "seconds": 5760}]
        result = merge_host_snapshots(
            [
                make_snapshot(applications=apps1),
                make_snapshot(applications=apps2),
            ]
        )
        alacritty = next(a for a in result["applications"] if a["name"] == "Alacritty")
        assert alacritty["seconds"] == 15360

    def test_different_apps_kept_separate(self):
        apps1 = [{"name": "Chrome", "category": "browser", "seconds": 7560}]
        apps2 = [{"name": "Firefox", "category": "browser", "seconds": 2880}]
        result = merge_host_snapshots(
            [
                make_snapshot(applications=apps1),
                make_snapshot(applications=apps2),
            ]
        )
        names = {a["name"] for a in result["applications"]}
        assert "Chrome" in names
        assert "Firefox" in names
        assert len(result["applications"]) == 2

    def test_same_name_different_category_not_merged(self):
        apps1 = [{"name": "Terminal", "category": "terminal", "seconds": 100}]
        apps2 = [{"name": "Terminal", "category": "other", "seconds": 200}]
        result = merge_host_snapshots(
            [
                make_snapshot(applications=apps1),
                make_snapshot(applications=apps2),
            ]
        )
        assert len(result["applications"]) == 2


class TestRhythm:
    def test_rhythm_element_wise_sum(self):
        r1 = [0] * 8 + [
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
        ]
        r2 = [0] * 8 + [
            120,
            180,
            240,
            300,
            360,
            420,
            480,
            540,
            720,
            1080,
            1560,
            1680,
            1800,
            1920,
            2040,
            2160,
        ]
        result = merge_host_snapshots(
            [
                make_snapshot(rhythm=r1),
                make_snapshot(rhythm=r2),
            ]
        )
        expected = [r1[i] + r2[i] for i in range(24)]
        assert result["rhythm"] == expected

    def test_rhythm_always_24_elements(self):
        result = merge_host_snapshots([make_snapshot()])
        assert len(result["rhythm"]) == 24


class TestOpencodeTokens:
    def test_tokens_total_summed(self):
        s1 = make_snapshot(tokens_total=180000)
        s2 = make_snapshot(tokens_total=50000)
        result = merge_host_snapshots([s1, s2])
        assert result["opencode_tokens_total"] == 230000

    def test_by_model_same_model_merged(self):
        s1 = make_snapshot(
            tokens_total=180000,
            by_model=[
                {"model": "claude-sonnet", "tokens": 140000},
                {"model": "gpt-4o", "tokens": 40000},
            ],
        )
        s2 = make_snapshot(
            tokens_total=50000,
            by_model=[{"model": "claude-sonnet", "tokens": 50000}],
        )
        result = merge_host_snapshots([s1, s2])
        assert result["opencode_by_model"]["claude-sonnet"] == 190000
        assert result["opencode_by_model"]["gpt-4o"] == 40000

    def test_by_model_unique_models_preserved(self):
        s1 = make_snapshot(by_model=[{"model": "model-a", "tokens": 100}])
        s2 = make_snapshot(by_model=[{"model": "model-b", "tokens": 200}])
        result = merge_host_snapshots([s1, s2])
        assert result["opencode_by_model"] == {"model-a": 100, "model-b": 200}


class TestBursts:
    def test_bursts_converted_to_burst_objects(self):
        session = OpenCodeSession(
            session_id="sess-001",
            bursts=[
                OpenCodeBurst(
                    start="2026-04-21T09:30:00+08:00",
                    end="2026-04-21T10:15:00+08:00",
                ),
            ],
        )
        s = make_snapshot(sessions=[session])
        result = merge_host_snapshots([s])
        assert len(result["bursts"]) == 1
        b = result["bursts"][0]
        assert isinstance(b, Burst)
        assert isinstance(b.start, datetime)
        assert isinstance(b.end, datetime)
        assert b.session_id == "sess-001"

    def test_bursts_collected_from_all_hosts(self):
        sess1 = OpenCodeSession(
            session_id="s1",
            bursts=[
                OpenCodeBurst(
                    start="2026-04-21T09:00:00+08:00", end="2026-04-21T10:00:00+08:00"
                )
            ],
        )
        sess2 = OpenCodeSession(
            session_id="s2",
            bursts=[
                OpenCodeBurst(
                    start="2026-04-21T14:00:00+08:00", end="2026-04-21T15:00:00+08:00"
                ),
                OpenCodeBurst(
                    start="2026-04-21T19:00:00+08:00", end="2026-04-21T20:00:00+08:00"
                ),
            ],
        )
        result = merge_host_snapshots(
            [
                make_snapshot(sessions=[sess1]),
                make_snapshot(sessions=[sess2]),
            ]
        )
        assert len(result["bursts"]) == 3

    def test_empty_sessions_yields_no_bursts(self):
        result = merge_host_snapshots([make_snapshot(sessions=[])])
        assert result["bursts"] == []


class TestWorkstations:
    def test_one_workstation_entry_per_snapshot(self):
        s1 = make_snapshot(label="工作机", platform="macOS", total_seconds=24480)
        s2 = make_snapshot(label="家里机", platform="Arch Linux", total_seconds=9360)
        result = merge_host_snapshots([s1, s2])
        assert len(result["workstations"]) == 2

    def test_workstation_fields_correct(self):
        s = make_snapshot(label="工作机", platform="macOS", total_seconds=24480)
        result = merge_host_snapshots([s])
        ws = result["workstations"][0]
        assert ws == {"label": "工作机", "platform": "macOS", "seconds": 24480}


class TestMergeSnapshotsByDate:
    def test_groups_by_date(self):
        s1 = make_snapshot(date="2026-04-21", total_seconds=1000)
        s2 = make_snapshot(date="2026-04-22", total_seconds=2000)
        result = merge_snapshots_by_date([s1, s2])
        assert set(result.keys()) == {"2026-04-21", "2026-04-22"}
        assert result["2026-04-21"]["active_total_seconds"] == 1000
        assert result["2026-04-22"]["active_total_seconds"] == 2000

    def test_same_date_multiple_hosts_merged(self):
        s1 = make_snapshot(date="2026-04-21", total_seconds=1000)
        s2 = make_snapshot(date="2026-04-21", total_seconds=500)
        result = merge_snapshots_by_date([s1, s2])
        assert len(result) == 1
        assert result["2026-04-21"]["active_total_seconds"] == 1500

    def test_empty_list_returns_empty_dict(self):
        assert merge_snapshots_by_date([]) == {}

    def test_date_field_in_merged_dict(self):
        s = make_snapshot(date="2026-04-21")
        result = merge_snapshots_by_date([s])
        assert result["2026-04-21"]["date"] == "2026-04-21"


class TestFixtureIntegration:
    def test_merge_two_fixture_snapshots(self):
        work = load_snapshot("snapshot-work-mac-2026-04-21.json")
        home = load_snapshot("snapshot-home-arch-2026-04-21.json")
        result = merge_host_snapshots([work, home])

        assert result["date"] == "2026-04-21"
        assert result["active_total_seconds"] == 24480 + 9360
        assert result["by_category"]["terminal"] == 15120 + 5760
        assert result["by_category"]["browser"] == 7560 + 2880
        assert result["opencode_tokens_total"] == 180000 + 50000
        assert result["opencode_by_model"]["claude-sonnet"] == 140000 + 50000
        assert result["opencode_by_model"]["gpt-4o"] == 40000
        assert len(result["bursts"]) == 4
        assert len(result["workstations"]) == 2

    def test_fixture_rhythm_sum(self):
        work = load_snapshot("snapshot-work-mac-2026-04-21.json")
        home = load_snapshot("snapshot-home-arch-2026-04-21.json")
        result = merge_host_snapshots([work, home])

        expected_h8 = 1800 + 120
        assert result["rhythm"][8] == expected_h8

    def test_fixture_applications_alacritty_merged(self):
        work = load_snapshot("snapshot-work-mac-2026-04-21.json")
        home = load_snapshot("snapshot-home-arch-2026-04-21.json")
        result = merge_host_snapshots([work, home])

        alacritty = next(
            a
            for a in result["applications"]
            if a["name"] == "Alacritty" and a["category"] == "terminal"
        )
        assert alacritty["seconds"] == 9600 + 5760

    def test_merge_snapshots_by_date_with_fixtures(self):
        work = load_snapshot("snapshot-work-mac-2026-04-21.json")
        home = load_snapshot("snapshot-home-arch-2026-04-21.json")
        by_date = merge_snapshots_by_date([work, home])
        assert list(by_date.keys()) == ["2026-04-21"]
        assert by_date["2026-04-21"]["active_total_seconds"] == 33840
