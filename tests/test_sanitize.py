import importlib

import pytest

sanitize = importlib.import_module("aw_report.sanitize")
FORBIDDEN_KEYS = sanitize.FORBIDDEN_KEYS
PrivacyViolation = sanitize.PrivacyViolation
hash_session_id = sanitize.hash_session_id
sanitize_snapshot = sanitize.sanitize_snapshot


@pytest.mark.parametrize(
    "payload",
    [
        {"window_title": "secret"},
        {"meta": {"url": "https://example.com"}},
        {"items": [{"file_path": "/tmp/secret.txt"}]},
        {"details": {"project_name": "private"}},
        {"host": {"hostname": "workstation"}},
    ],
)
def test_sanitize_snapshot_rejects_forbidden_keys(payload: dict) -> None:
    with pytest.raises(PrivacyViolation, match="Forbidden field detected"):
        sanitize_snapshot(payload)


def test_sanitize_snapshot_rejects_title_key_in_nested_dict() -> None:
    with pytest.raises(PrivacyViolation, match="Forbidden field detected"):
        sanitize_snapshot({"outer": {"title": "hidden"}})


def test_sanitize_snapshot_rejects_file_key_in_list_item() -> None:
    with pytest.raises(PrivacyViolation, match="Forbidden field detected"):
        sanitize_snapshot({"records": [{"file": "secret.py"}]})


def test_sanitize_snapshot_rejects_path_key_in_deep_structure() -> None:
    with pytest.raises(PrivacyViolation, match="Forbidden field detected"):
        sanitize_snapshot({"a": [{"b": {"path": "/private"}}]})


def test_sanitize_snapshot_returns_clean_dict_unchanged() -> None:
    payload = {"ok": True, "nested": {"value": 1}, "items": [{"safe": "x"}]}

    result = sanitize_snapshot(payload)

    assert result is payload
    assert result == payload


def test_hash_session_id_length_is_16() -> None:
    assert len(hash_session_id("ses_abc")) == 16


def test_hash_session_id_is_deterministic() -> None:
    assert hash_session_id("ses_abc") == hash_session_id("ses_abc")


def test_forbidden_keys_contains_required_fields() -> None:
    assert FORBIDDEN_KEYS == frozenset(
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
