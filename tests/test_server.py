from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ghostwire.models import HostMeta, HostSnapshot  # noqa: E402
from ghostwire.server import ServerConfig, create_app  # noqa: E402

HOST_TOKEN = "host-secret"
READ_TOKEN = "read-secret"


@pytest.fixture
def server(tmp_path: Path):
    config = ServerConfig(
        data_dir=tmp_path / "data",
        host_token=HOST_TOKEN,
        read_token=READ_TOKEN,
    )
    app = create_app(config)
    return TestClient(app), config


def make_snapshot_payload(host_id: str, date_str: str) -> bytes:
    snap = HostSnapshot(
        host=HostMeta(id=host_id, label="工作机", platform="macOS"),
        date=date_str,
        timezone="Asia/Shanghai",
        generated_at=f"{date_str}T22:00:00+08:00",
        active={
            "total_seconds": 100,
            "by_category": {"terminal": 60, "browser": 30, "other": 10},
        },
        applications=[],
        rhythm=[0] * 24,
        opencode={"tokens_total": 0, "by_model": [], "sessions": []},
    )
    return snap.to_json().encode("utf-8")


def test_healthz_no_auth(server):
    client, _ = server
    assert client.get("/healthz").status_code == 200


def test_put_requires_bearer(server):
    client, _ = server
    body = make_snapshot_payload("work-mac", "2026-04-21")
    r = client.put("/api/v1/snapshots/work-mac/2026-04-21", content=body)
    assert r.status_code == 401


def test_put_rejects_wrong_token(server):
    client, _ = server
    body = make_snapshot_payload("work-mac", "2026-04-21")
    r = client.put(
        "/api/v1/snapshots/work-mac/2026-04-21",
        content=body,
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 403


def test_put_writes_atomic_file(server):
    client, config = server
    body = make_snapshot_payload("work-mac", "2026-04-21")
    r = client.put(
        "/api/v1/snapshots/work-mac/2026-04-21",
        content=body,
        headers={"Authorization": f"Bearer {HOST_TOKEN}"},
    )
    assert r.status_code == 200, r.text
    target = config.data_dir / "work-mac" / "2026-04-21.json"
    assert target.exists()
    assert target.read_bytes() == body


def test_put_rejects_host_id_mismatch(server):
    client, _ = server
    body = make_snapshot_payload("work-mac", "2026-04-21")
    r = client.put(
        "/api/v1/snapshots/home-arch/2026-04-21",
        content=body,
        headers={"Authorization": f"Bearer {HOST_TOKEN}"},
    )
    assert r.status_code == 400
    assert "host_id mismatch" in r.text


def test_put_rejects_date_mismatch(server):
    client, _ = server
    body = make_snapshot_payload("work-mac", "2026-04-21")
    r = client.put(
        "/api/v1/snapshots/work-mac/2026-04-22",
        content=body,
        headers={"Authorization": f"Bearer {HOST_TOKEN}"},
    )
    assert r.status_code == 400
    assert "date mismatch" in r.text


def test_put_rejects_invalid_host_id(server):
    client, _ = server
    body = make_snapshot_payload("work-mac", "2026-04-21")
    r = client.put(
        "/api/v1/snapshots/has spaces/2026-04-21",
        content=body,
        headers={"Authorization": f"Bearer {HOST_TOKEN}"},
    )
    assert r.status_code == 400


def test_put_rejects_invalid_date_format(server):
    client, _ = server
    body = make_snapshot_payload("work-mac", "2026-04-21")
    r = client.put(
        "/api/v1/snapshots/work-mac/04-21-2026",
        content=body,
        headers={"Authorization": f"Bearer {HOST_TOKEN}"},
    )
    assert r.status_code == 400


def test_put_is_idempotent_upsert(server):
    client, config = server
    body1 = make_snapshot_payload("work-mac", "2026-04-21")

    client.put(
        "/api/v1/snapshots/work-mac/2026-04-21",
        content=body1,
        headers={"Authorization": f"Bearer {HOST_TOKEN}"},
    )

    snap2 = HostSnapshot(
        host=HostMeta(id="work-mac", label="工作机", platform="macOS"),
        date="2026-04-21",
        timezone="Asia/Shanghai",
        generated_at="2026-04-21T23:00:00+08:00",
        active={
            "total_seconds": 999,
            "by_category": {"terminal": 999, "browser": 0, "other": 0},
        },
        applications=[],
        rhythm=[0] * 24,
        opencode={"tokens_total": 0, "by_model": [], "sessions": []},
    )
    body2 = snap2.to_json().encode("utf-8")
    client.put(
        "/api/v1/snapshots/work-mac/2026-04-21",
        content=body2,
        headers={"Authorization": f"Bearer {HOST_TOKEN}"},
    )

    target = config.data_dir / "work-mac" / "2026-04-21.json"
    assert target.read_bytes() == body2


def test_dashboard_json_requires_read_token(server):
    client, _ = server
    r = client.get("/api/v1/dashboard.json")
    assert r.status_code == 401


def test_dashboard_json_uses_host_token_is_rejected(server):
    client, _ = server
    r = client.get(
        "/api/v1/dashboard.json",
        headers={"Authorization": f"Bearer {HOST_TOKEN}"},
    )
    assert r.status_code == 403


def test_dashboard_json_aggregates_uploaded_snapshots(server):
    client, _ = server
    today = date.today().isoformat()
    body = make_snapshot_payload("work-mac", today)
    client.put(
        f"/api/v1/snapshots/work-mac/{today}",
        content=body,
        headers={"Authorization": f"Bearer {HOST_TOKEN}"},
    )
    r = client.get(
        "/api/v1/dashboard.json",
        params={"today": today},
        headers={"Authorization": f"Bearer {READ_TOKEN}"},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["header"]["hosts_count"] == 1
    assert len(payload["timeline_30d"]) == 30


def test_dashboard_svg_renders_xml(server):
    client, _ = server
    today = date.today().isoformat()
    body = make_snapshot_payload("work-mac", today)
    client.put(
        f"/api/v1/snapshots/work-mac/{today}",
        content=body,
        headers={"Authorization": f"Bearer {HOST_TOKEN}"},
    )
    r = client.get(
        "/api/v1/dashboard.svg",
        params={"today": today},
        headers={"Authorization": f"Bearer {READ_TOKEN}"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert r.text.lstrip().startswith("<")
