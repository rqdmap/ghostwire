from __future__ import annotations

import os
from datetime import date

import httpx

from .models import HostSnapshot


class UploadError(RuntimeError):
    pass


def upload_snapshot(
    snapshot: HostSnapshot,
    server_url: str,
    token: str,
    timeout_seconds: float = 30.0,
) -> str:
    target = _endpoint(server_url, snapshot.host.id, snapshot.date)
    payload = snapshot.to_json().encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.put(
            target, content=payload, headers=headers, timeout=timeout_seconds
        )
    except httpx.HTTPError as exc:
        raise UploadError(f"PUT {target} failed: {exc}") from exc

    if response.status_code >= 400:
        raise UploadError(
            f"PUT {target} returned {response.status_code}: {response.text[:200]}"
        )
    return target


def _endpoint(server_url: str, host_id: str, date_str: str) -> str:
    base = server_url.rstrip("/")
    return f"{base}/api/v1/snapshots/{host_id}/{date_str}"


def resolve_token(token: str | None, env_var: str | None) -> str:
    if token:
        return token
    if env_var:
        value = os.environ.get(env_var)
        if value:
            return value
    raise UploadError("no upload token: pass --token or set --token-env")


def parse_date(value: str | None) -> date:
    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise UploadError(f"invalid date: {value!r}") from exc
