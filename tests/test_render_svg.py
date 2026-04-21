from __future__ import annotations

import json
import re
from datetime import date
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree

from ghostwire.aggregate_dashboard import aggregate
from ghostwire.models import HostSnapshot, TimelineEntry

render_svg = import_module("ghostwire.render_svg")
_token_line_points = render_svg._token_line_points
render_dashboard = render_svg.render_dashboard

FIXTURES = Path(__file__).parent / "fixtures"


def load_snapshot(filename: str) -> HostSnapshot:
    return HostSnapshot.from_json((FIXTURES / filename).read_text(encoding="utf-8"))


def load_dashboard_fixture() -> dict:
    return json.loads(
        (FIXTURES / "dashboard-expected.json").read_text(encoding="utf-8")
    )


def build_dashboard():
    snapshots = [
        load_snapshot("snapshot-work-mac-2026-04-21.json"),
        load_snapshot("snapshot-home-arch-2026-04-21.json"),
        load_snapshot("snapshot-work-mac-2026-04-20.json"),
    ]
    return aggregate(snapshots, today=date(2026, 4, 21))


def test_render_dashboard_returns_non_empty_string() -> None:
    dashboard = build_dashboard()

    assert render_dashboard(dashboard).strip()


def test_render_dashboard_returns_valid_svg_xml() -> None:
    dashboard = build_dashboard()

    svg = render_dashboard(dashboard)
    root = ElementTree.fromstring(svg)

    assert root.tag.endswith("svg")


def test_render_dashboard_resolves_template_placeholders() -> None:
    dashboard = build_dashboard()

    svg = render_dashboard(dashboard)

    assert "${ACTIVE_30D_H}" not in svg
    assert re.search(r"\$\{[A-Z0-9_]+\}", svg) is None


def test_render_dashboard_includes_fixture_values() -> None:
    dashboard = build_dashboard()
    fixture = load_dashboard_fixture()

    svg = render_dashboard(dashboard)

    assert fixture["workstations"][0]["label"] in svg
    assert fixture["workstations"][1]["platform"] in svg


def test_token_line_points_returns_comma_separated_coordinates() -> None:
    points = _token_line_points(
        [
            TimelineEntry(
                date="2026-04-19",
                terminal_seconds=0,
                browser_seconds=0,
                other_seconds=0,
                tokens=100,
            ),
            TimelineEntry(
                date="2026-04-20",
                terminal_seconds=0,
                browser_seconds=0,
                other_seconds=0,
                tokens=300,
            ),
            TimelineEntry(
                date="2026-04-21",
                terminal_seconds=0,
                browser_seconds=0,
                other_seconds=0,
                tokens=200,
            ),
        ]
    )

    assert points
    assert re.fullmatch(r"\d+,\d+( \d+,\d+)+", points) is not None
