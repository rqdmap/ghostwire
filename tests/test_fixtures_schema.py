from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"


def load_json(name: str):
    with (FIXTURES / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def test_snapshot_fixtures_are_valid_json():
    for name in [
        "snapshot-work-mac-2026-04-21.json",
        "snapshot-home-arch-2026-04-21.json",
        "snapshot-work-mac-2026-04-20.json",
    ]:
        data = load_json(name)
        assert data["schema_version"]
        assert data["host"]["label"]
        assert data["host"]["platform"]


def test_dashboard_fixture_is_valid_json():
    data = load_json("dashboard-expected.json")
    required_keys = {
        "active_30d_seconds",
        "tokens_7d",
        "workstations",
        "session_load",
        "timeline_30d",
        "applications_30d",
        "models_30d",
        "rhythm_7d",
    }
    assert required_keys.issubset(data)
    assert len(data["timeline_30d"]) == 30
    assert len(data["rhythm_7d"]) == 24
