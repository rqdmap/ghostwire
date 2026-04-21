"""Telemetry server.

PUT  /api/v1/snapshots/{host_id}/{date}  - host uploads (Bearer host token)
GET  /api/v1/dashboard.json              - aggregated dashboard JSON
GET  /api/v1/dashboard.svg               - rendered dashboard SVG
GET  /healthz                            - liveness, no auth

Storage layout::

    <data_dir>/
        <host_id>/
            <YYYY-MM-DD>.json

Writes are atomic (tmp + rename).  Aggregation re-reads the directory on each
GET; cheap because a daily snapshot is a few KB.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from .aggregate_dashboard import aggregate
from .models import HostSnapshot
from .render_svg import render_dashboard

HOST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class ServerConfig:
    data_dir: Path
    host_token: str
    read_token: str
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("Asia/Shanghai"))
    day_start: time = field(default_factory=lambda: time(0, 0))


def create_app(config: ServerConfig) -> FastAPI:
    app = FastAPI(title="Ghostwire telemetry server", version="1.0")
    config.data_dir.mkdir(parents=True, exist_ok=True)

    def require_token(authorization: Optional[str], expected: str) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "missing bearer token")
        token = authorization[len("Bearer ") :].strip()
        if not secrets.compare_digest(token, expected):
            raise HTTPException(403, "invalid token")

    @app.get("/healthz")
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.put("/api/v1/snapshots/{host_id}/{date_str}")
    async def put_snapshot(
        host_id: str,
        date_str: str,
        request: Request,
        authorization: Optional[str] = Header(default=None),
    ) -> JSONResponse:
        require_token(authorization, config.host_token)
        if not HOST_ID_RE.match(host_id):
            raise HTTPException(400, "invalid host_id")
        if not DATE_RE.match(date_str):
            raise HTTPException(400, "invalid date")

        body = await request.body()
        try:
            snapshot = HostSnapshot.from_json(body.decode("utf-8"))
            snapshot.validate()
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            raise HTTPException(400, f"invalid snapshot: {exc}") from exc

        if snapshot.host.id != host_id:
            raise HTTPException(
                400, f"host_id mismatch: url={host_id} body={snapshot.host.id}"
            )
        if snapshot.date != date_str:
            raise HTTPException(
                400, f"date mismatch: url={date_str} body={snapshot.date}"
            )

        _atomic_write(config.data_dir / host_id / f"{date_str}.json", body)
        return JSONResponse(
            {"stored": True, "host_id": host_id, "date": date_str},
            status_code=200,
        )

    @app.get("/api/v1/dashboard.json")
    def get_dashboard_json(
        today: Optional[str] = None,
        authorization: Optional[str] = Header(default=None),
    ) -> Response:
        require_token(authorization, config.read_token)
        dashboard = _build_dashboard(config, today)
        return Response(
            content=json.dumps(dashboard.to_json(), ensure_ascii=False, indent=2),
            media_type="application/json",
        )

    @app.get("/api/v1/dashboard.svg")
    def get_dashboard_svg(
        today: Optional[str] = None,
        authorization: Optional[str] = Header(default=None),
    ) -> Response:
        require_token(authorization, config.read_token)
        dashboard = _build_dashboard(config, today)
        svg = render_dashboard(dashboard)
        return Response(content=svg, media_type="image/svg+xml")

    return app


def _atomic_write(target: Path, body: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def _load_snapshots(data_dir: Path) -> list[HostSnapshot]:
    snapshots: list[HostSnapshot] = []
    for host_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        for snap_file in sorted(host_dir.glob("*.json")):
            try:
                snapshots.append(
                    HostSnapshot.from_json(snap_file.read_text(encoding="utf-8"))
                )
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
    return snapshots


def _build_dashboard(config: ServerConfig, today_str: Optional[str]):
    snapshots = _load_snapshots(config.data_dir)
    today = date.fromisoformat(today_str) if today_str else _logical_today(config)
    return aggregate(
        snapshots,
        today=today,
        timezone_name=str(config.timezone),
        day_start=config.day_start,
    )


def _logical_today(config: ServerConfig) -> date:
    current = datetime.now(config.timezone)
    boundary = datetime.combine(current.date(), config.day_start, tzinfo=config.timezone)
    if current < boundary:
        return current.date() - timedelta(days=1)
    return current.date()


def run(
    data_dir: Path,
    host_token: str,
    read_token: str,
    timezone: ZoneInfo = ZoneInfo("Asia/Shanghai"),
    day_start: time = time(0, 0),
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    import uvicorn

    config = ServerConfig(
        data_dir=data_dir,
        host_token=host_token,
        read_token=read_token,
        timezone=timezone,
        day_start=day_start,
    )
    app = create_app(config)
    uvicorn.run(app, host=host, port=port, log_level="info")
