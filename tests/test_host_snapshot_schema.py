import pytest

from ghostwire.models import HostMeta, HostSnapshot, OpenCodeBurst, OpenCodeSession


def make_snapshot(
    *, label: str = "工作机", platform: str = "macOS", date: str = "2026-04-21"
) -> HostSnapshot:
    return HostSnapshot(
        host=HostMeta(id="work-mac-2024", label=label, platform=platform),
        date=date,
        timezone="Asia/Shanghai",
        generated_at="2026-04-22T03:00:00+08:00",
        active={
            "total_seconds": 22680,
            "by_category": {"terminal": 14040, "browser": 6120, "other": 2520},
        },
        applications=[{"name": "Alacritty", "category": "terminal", "seconds": 9600}],
        rhythm=[0] * 24,
        opencode={
            "tokens_total": 230000,
            "by_model": [{"model": "claude-sonnet", "tokens": 180000}],
            "sessions": [
                OpenCodeSession(
                    session_id="abc123def456gh78",
                    bursts=[
                        OpenCodeBurst(
                            start="2026-04-21T14:32:00+08:00",
                            end="2026-04-21T15:18:00+08:00",
                        )
                    ],
                )
            ],
        },
    )


def test_construction_uses_expected_shape() -> None:
    snapshot = make_snapshot()

    assert snapshot.schema_version == "1.0"
    assert snapshot.host.id == "work-mac-2024"
    assert (
        snapshot.opencode["sessions"][0].bursts[0].start == "2026-04-21T14:32:00+08:00"
    )


def test_roundtrip_preserves_nested_dataclasses() -> None:
    snapshot = make_snapshot()

    restored = HostSnapshot.from_json(snapshot.to_json())

    assert restored == snapshot
    assert isinstance(restored.host, HostMeta)
    assert isinstance(restored.opencode["sessions"][0], OpenCodeSession)
    assert isinstance(restored.opencode["sessions"][0].bursts[0], OpenCodeBurst)


def test_validate_passes_for_complete_snapshot() -> None:
    make_snapshot().validate()


def test_validate_rejects_missing_host_label() -> None:
    with pytest.raises(ValueError, match="host.label"):
        make_snapshot(label="").validate()


def test_validate_rejects_missing_host_platform() -> None:
    with pytest.raises(ValueError, match="host.platform"):
        make_snapshot(platform="").validate()


def test_validate_rejects_bad_date_format() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        make_snapshot(date="2026/04/21").validate()
