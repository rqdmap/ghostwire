from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def _default_config_paths() -> list[Path]:
    paths = [
        Path("ghostwire.toml"),
        Path.home() / ".config" / "ghostwire" / "ghostwire.toml",
    ]
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        win_base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        paths.append(win_base / "ghostwire" / "ghostwire.toml")
    return paths


DEFAULT_CONFIG_PATHS = _default_config_paths()


@dataclass
class Config:
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("Asia/Shanghai"))
    day_start: time = field(default_factory=lambda: time(0, 0))
    base_url: str = "http://127.0.0.1:5600"
    timeout_seconds: int = 30
    hosts: list[str] = field(default_factory=lambda: ["auto"])
    categorize_terminal: list[str] = field(default_factory=list)
    categorize_browser: list[str] = field(default_factory=list)
    opencode_burst_gap_minutes: int = 10

    def reporting_window(self, target_date: date) -> tuple[datetime, datetime]:
        start = datetime.combine(target_date, self.day_start, tzinfo=self.timezone)
        return start, start + timedelta(days=1)

    def reporting_date(self, now: datetime | None = None) -> date:
        current = now or datetime.now(self.timezone)
        if current.tzinfo is None:
            current = current.replace(tzinfo=self.timezone)
        else:
            current = current.astimezone(self.timezone)

        boundary = datetime.combine(current.date(), self.day_start, tzinfo=self.timezone)
        if current < boundary:
            return current.date() - timedelta(days=1)
        return current.date()


def load_config(path: Path | None = None) -> Config:
    if path and path.exists():
        return _parse(path)
    for p in DEFAULT_CONFIG_PATHS:
        if p.exists():
            return _parse(p)
    return Config()


def _parse(path: Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    general = raw.get("general", {})
    aw = raw.get("activitywatch", {})
    categorize = raw.get("categorize", {})
    terminal = categorize.get("terminal", {})
    browser = categorize.get("browser", {})
    opencode = raw.get("opencode", {})

    return Config(
        timezone=ZoneInfo(general.get("timezone", "Asia/Shanghai")),
        day_start=_parse_day_start(general.get("day_start", "00:00")),
        base_url=aw.get("base_url", "http://127.0.0.1:5600"),
        timeout_seconds=aw.get("timeout_seconds", 30),
        hosts=aw.get("hosts", ["auto"]),
        categorize_terminal=terminal.get("allow", []),
        categorize_browser=browser.get("allow", []),
        opencode_burst_gap_minutes=_parse_burst_gap_minutes(
            opencode.get("burst_gap_minutes", 10)
        ),
    )


def _parse_burst_gap_minutes(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError(f"invalid opencode.burst_gap_minutes: {value!r}")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        parsed = int(value)
    elif isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(
                f"invalid opencode.burst_gap_minutes: {value!r}"
            ) from exc
    else:
        raise ValueError(f"invalid opencode.burst_gap_minutes: {value!r}")
    if parsed < 0:
        raise ValueError("opencode.burst_gap_minutes must be >= 0")
    return parsed


def _parse_day_start(value: object) -> time:
    if isinstance(value, time):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"invalid general.day_start: {value!r}") from exc
    else:
        raise ValueError(f"invalid general.day_start: {value!r}")

    if parsed.tzinfo is not None:
        raise ValueError("general.day_start must not include timezone info")
    return parsed.replace(microsecond=0)
