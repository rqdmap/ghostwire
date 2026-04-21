from __future__ import annotations

from dataclasses import dataclass

import httpx

from .models import BucketInfo


@dataclass
class AWClient:
    base_url: str
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            base_url=self.base_url.rstrip("/"), timeout=self.timeout_seconds
        )

    def close(self) -> None:
        self._client.close()

    def list_buckets(self) -> dict[str, BucketInfo]:
        try:
            response = self._client.get("/api/0/buckets")
            response.raise_for_status()
        except Exception:
            return {}

        payload = response.json()
        if not isinstance(payload, dict):
            return {}

        buckets: dict[str, BucketInfo] = {}
        for bid, info in payload.items():
            if not isinstance(info, dict):
                continue
            buckets[str(bid)] = BucketInfo(
                id=str(info.get("id", bid)),
                type=str(info.get("type", "")),
                hostname=str(info.get("hostname", "")),
            )
        return buckets


def discover_host_buckets(client: AWClient) -> dict[str, dict[str, str]]:
    buckets = client.list_buckets()
    host_buckets: dict[str, dict[str, str]] = {}
    for bid, info in buckets.items():
        host = info.hostname or "unknown"
        logical = info.type or bid
        host_buckets.setdefault(host, {})[logical] = bid
    return host_buckets
