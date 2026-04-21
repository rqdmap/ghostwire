from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from dataclasses import asdict
from typing import Any


@dataclass
class BucketInfo:
    id: str
    type: str
    hostname: str


@dataclass
class HostMeta:
    id: str
    label: str
    platform: str


@dataclass
class OpenCodeBurst:
    start: str
    end: str


@dataclass
class OpenCodeSession:
    session_id: str
    bursts: list[OpenCodeBurst]

    @classmethod
    def from_dict(cls, payload: dict) -> "OpenCodeSession":
        return cls(
            session_id=payload["session_id"],
            bursts=[OpenCodeBurst(**burst) for burst in payload.get("bursts", [])],
        )


@dataclass
class HostSnapshot:
    host: HostMeta
    date: str
    timezone: str
    generated_at: str
    active: dict = field(default_factory=dict)
    applications: list[dict] = field(default_factory=list)
    rhythm: list[int] = field(default_factory=list)
    opencode: dict = field(default_factory=dict)
    schema_version: str = "1.0"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, payload: str) -> "HostSnapshot":
        data = json.loads(payload)
        opencode = data.get("opencode", {})
        return cls(
            host=HostMeta(**data["host"]),
            date=data["date"],
            timezone=data["timezone"],
            generated_at=data["generated_at"],
            active=data.get("active", {}),
            applications=list(data.get("applications", [])),
            rhythm=list(data.get("rhythm", [])),
            opencode={
                "tokens_total": opencode.get("tokens_total", 0),
                "by_model": list(opencode.get("by_model", [])),
                "sessions": [
                    OpenCodeSession.from_dict(session)
                    for session in opencode.get("sessions", [])
                ],
            },
            schema_version=data.get("schema_version", "1.0"),
        )

    def validate(self) -> None:
        if not self.host.label.strip():
            raise ValueError("host.label is required")
        if not self.host.platform.strip():
            raise ValueError("host.platform is required")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.date):
            raise ValueError("date must use YYYY-MM-DD format")


@dataclass
class WorkstationEntry:
    label: str
    platform: str
    seconds: int


@dataclass
class SessionLoad:
    avg_concurrent: float
    peak_concurrent: int
    return_median_seconds: int
    trend_7d: list[float]


@dataclass
class Cards:
    active_30d_seconds: int
    active_30d_delta_pct: int
    tokens_7d: int
    tokens_7d_delta_pct: int
    workstations: list[WorkstationEntry]
    session_load: SessionLoad


@dataclass
class TimelineEntry:
    date: str
    terminal_seconds: int
    browser_seconds: int
    other_seconds: int
    tokens: int


@dataclass
class BestDay:
    date: str
    active_seconds: int
    tokens: int


@dataclass
class ApplicationEntry:
    category: str
    label: str
    seconds: int


@dataclass
class ModelEntry:
    model: str
    tokens: int


@dataclass
class DashboardRange:
    days: int
    start: str
    end: str
    timezone: str


@dataclass
class DashboardHeader:
    hosts_count: int
    synced_at: str


@dataclass
class Dashboard:
    generated_at: str
    range: DashboardRange
    header: DashboardHeader
    cards: Cards
    timeline_30d: list[TimelineEntry]
    best_day: BestDay
    applications_30d: list[ApplicationEntry]
    models_30d: list[ModelEntry]
    rhythm_7d: list[int]
    schema_version: str = "1.0"

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "range": asdict(self.range),
            "header": asdict(self.header),
            "cards": asdict(self.cards),
            "timeline_30d": [asdict(item) for item in self.timeline_30d],
            "best_day": asdict(self.best_day),
            "applications_30d": [asdict(item) for item in self.applications_30d],
            "models_30d": [asdict(item) for item in self.models_30d],
            "rhythm_7d": list(self.rhythm_7d),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any] | str) -> "Dashboard":
        data = json.loads(payload) if isinstance(payload, str) else dict(payload)
        return cls(
            generated_at=data["generated_at"],
            range=DashboardRange(**data["range"]),
            header=DashboardHeader(**data["header"]),
            cards=Cards(
                active_30d_seconds=data["cards"]["active_30d_seconds"],
                active_30d_delta_pct=data["cards"]["active_30d_delta_pct"],
                tokens_7d=data["cards"]["tokens_7d"],
                tokens_7d_delta_pct=data["cards"]["tokens_7d_delta_pct"],
                workstations=[
                    WorkstationEntry(**item) for item in data["cards"]["workstations"]
                ],
                session_load=SessionLoad(**data["cards"]["session_load"]),
            ),
            timeline_30d=[
                TimelineEntry(**item) for item in data.get("timeline_30d", [])
            ],
            best_day=BestDay(**data["best_day"]),
            applications_30d=[
                ApplicationEntry(**item) for item in data.get("applications_30d", [])
            ],
            models_30d=[ModelEntry(**item) for item in data.get("models_30d", [])],
            rhythm_7d=list(data.get("rhythm_7d", [])),
            schema_version=data.get("schema_version", "1.0"),
        )

    def validate(self) -> None:
        if len(self.rhythm_7d) != 24:
            raise ValueError("rhythm_7d must contain exactly 24 values")
        json_text = json.dumps(self.to_json(), ensure_ascii=False)
        if any(banned in json_text for banned in ("host_id", "session_id", "hostname")):
            raise ValueError(
                "dashboard JSON must not include host_id, session_id, or hostname"
            )
