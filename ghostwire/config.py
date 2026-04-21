from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_CONFIG_PATHS = [
    Path("ghostwire.toml"),
    Path.home() / ".config" / "ghostwire" / "ghostwire.toml",
]


@dataclass
class Config:
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("Asia/Shanghai"))
    base_url: str = "http://127.0.0.1:5600"
    timeout_seconds: int = 30
    hosts: list[str] = field(default_factory=lambda: ["auto"])
    categorize_terminal: list[str] = field(default_factory=list)
    categorize_browser: list[str] = field(default_factory=list)


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

    return Config(
        timezone=ZoneInfo(general.get("timezone", "Asia/Shanghai")),
        base_url=aw.get("base_url", "http://127.0.0.1:5600"),
        timeout_seconds=aw.get("timeout_seconds", 30),
        hosts=aw.get("hosts", ["auto"]),
        categorize_terminal=terminal.get("allow", []),
        categorize_browser=browser.get("allow", []),
    )
