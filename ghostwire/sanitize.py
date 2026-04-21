from __future__ import annotations

import hashlib


class PrivacyViolation(Exception):
    pass


FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "window_title",
        "url",
        "file_path",
        "project_name",
        "hostname",
        "title",
        "file",
        "project",
        "path",
    }
)


def _scan_value(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_KEYS:
                raise PrivacyViolation("Forbidden field detected")
            _scan_value(nested)
    elif isinstance(value, list):
        for item in value:
            _scan_value(item)


def sanitize_snapshot(raw: dict) -> dict:
    _scan_value(raw)
    return raw


def hash_session_id(raw_id: str) -> str:
    return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]
