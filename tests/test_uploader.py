from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from ghostwire.models import HostMeta, HostSnapshot
from ghostwire.uploader import (
    UploadError,
    parse_date,
    resolve_token,
    upload_snapshot,
)


def make_snapshot(
    host_id: str = "work-mac", date_str: str = "2026-04-21"
) -> HostSnapshot:
    return HostSnapshot(
        host=HostMeta(id=host_id, label="工作机", platform="macOS"),
        date=date_str,
        timezone="Asia/Shanghai",
        generated_at="2026-04-21T22:00:00+08:00",
        active={
            "total_seconds": 0,
            "by_category": {"terminal": 0, "browser": 0, "other": 0},
        },
        applications=[],
        rhythm=[0] * 24,
        opencode={"tokens_total": 0, "by_model": [], "sessions": []},
    )


def test_resolve_token_prefers_explicit():
    assert resolve_token("explicit", "ANYTHING") == "explicit"


def test_resolve_token_reads_env(monkeypatch):
    monkeypatch.setenv("GHOSTWIRE_TEST_TOKEN", "from-env")
    assert resolve_token(None, "GHOSTWIRE_TEST_TOKEN") == "from-env"


def test_resolve_token_raises_when_missing(monkeypatch):
    monkeypatch.delenv("GHOSTWIRE_MISSING", raising=False)
    with pytest.raises(UploadError):
        resolve_token(None, "GHOSTWIRE_MISSING")


def test_parse_date_defaults_to_today():
    assert parse_date(None) == date.today()


def test_parse_date_invalid_raises():
    with pytest.raises(UploadError):
        parse_date("not-a-date")


def test_upload_snapshot_puts_to_correct_endpoint(monkeypatch):
    seen = {}

    def fake_put(url, content, headers, timeout):
        seen["url"] = url
        seen["body"] = content
        seen["headers"] = headers
        return httpx.Response(200, json={"stored": True})

    monkeypatch.setattr(httpx, "put", fake_put)

    snapshot = make_snapshot("work-mac", "2026-04-21")
    endpoint = upload_snapshot(snapshot, "https://srv.example/", "tok-1")

    assert endpoint == "https://srv.example/api/v1/snapshots/work-mac/2026-04-21"
    assert seen["url"] == endpoint
    assert seen["headers"]["Authorization"] == "Bearer tok-1"
    body = json.loads(seen["body"])
    assert body["host"]["id"] == "work-mac"
    assert body["date"] == "2026-04-21"


def test_upload_snapshot_raises_on_http_error(monkeypatch):
    def fake_put(*_args, **_kwargs):
        return httpx.Response(403, text="forbidden")

    monkeypatch.setattr(httpx, "put", fake_put)

    with pytest.raises(UploadError) as excinfo:
        upload_snapshot(make_snapshot(), "https://srv", "wrong")
    assert "403" in str(excinfo.value)


def test_upload_snapshot_raises_on_transport_error(monkeypatch):
    def fake_put(*_args, **_kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "put", fake_put)

    with pytest.raises(UploadError) as excinfo:
        upload_snapshot(make_snapshot(), "https://srv", "any")
    assert "refused" in str(excinfo.value)
