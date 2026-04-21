from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_CONFIG_PATHS = [
    Path("aw-report.toml"),
    Path.home() / ".config" / "aw-report" / "aw-report.toml",
]


@dataclass
class Config:
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("Asia/Shanghai"))
    base_url: str = "http://127.0.0.1:5600"
    timeout_seconds: int = 30
    hosts: list[str] = field(default_factory=lambda: ["auto"])
    categorize_terminal: list[str] = field(default_factory=list)
    categorize_browser: list[str] = field(default_factory=list)
    default_format: str = "md"
    include_window: bool = True
    include_afk: bool = True
    include_web: bool = True
    include_vim: bool = True
    include_input: bool = True
    dominance_ratio: float = 1.5


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
    report = raw.get("report", {})
    labels = raw.get("input_labels", {})
    categorize = raw.get("categorize", {})
    terminal = categorize.get("terminal", {})
    browser = categorize.get("browser", {})

    tz_name = general.get("timezone", "Asia/Shanghai")

    return Config(
        timezone=ZoneInfo(tz_name),
        base_url=aw.get("base_url", "http://127.0.0.1:5600"),
        timeout_seconds=aw.get("timeout_seconds", 30),
        hosts=aw.get("hosts", ["auto"]),
        categorize_terminal=terminal.get("allow", []),
        categorize_browser=browser.get("allow", []),
        default_format=report.get("default_format", "md"),
        include_window=report.get("include_window", True),
        include_afk=report.get("include_afk", True),
        include_web=report.get("include_web", True),
        include_vim=report.get("include_vim", True),
        include_input=report.get("include_input", True),
        dominance_ratio=labels.get("dominance_ratio", 1.5),
    )
