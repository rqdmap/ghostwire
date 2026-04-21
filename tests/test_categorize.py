from __future__ import annotations

from datetime import date, datetime, time
from importlib import import_module
from zoneinfo import ZoneInfo

from ghostwire.config import Config, load_config

categorize = import_module("ghostwire.categorize").categorize


def test_categorize_terminal_hit() -> None:
    config = Config(categorize_terminal=["WezTerm"], categorize_browser=[])

    assert categorize("WezTerm", config) == "terminal"


def test_categorize_browser_hit() -> None:
    config = Config(categorize_terminal=[], categorize_browser=["Firefox"])

    assert categorize("Firefox", config) == "browser"


def test_categorize_terminal_wins_when_app_is_in_both_lists() -> None:
    config = Config(categorize_terminal=["Code"], categorize_browser=["Code"])

    assert categorize("Code", config) == "terminal"


def test_categorize_is_case_sensitive() -> None:
    config = Config(categorize_terminal=["iTerm2"], categorize_browser=[])

    assert categorize("iterm2", config) == "other"


def test_categorize_returns_other_for_unknown_app() -> None:
    config = Config()

    assert categorize("Slack", config) == "other"


def test_load_config_parses_categorize_sections(tmp_path) -> None:
    path = tmp_path / "ghostwire.toml"
    path.write_text(
        """
[general]
timezone = "Asia/Shanghai"
day_start = "06:00"

[activitywatch]
base_url = "http://127.0.0.1:5600"
timeout_seconds = 30
hosts = ["auto"]

[report]
default_format = "md"
include_window = true
include_afk = true
include_web = true
include_vim = true
include_input = true

[input_labels]
dominance_ratio = 1.5

[categorize.terminal]
allow = ["Neovim"]

[categorize.browser]
allow = ["Safari"]
""".strip(),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.day_start == time(6, 0)
    assert config.categorize_terminal == ["Neovim"]
    assert config.categorize_browser == ["Safari"]


def test_load_config_without_categorize_sections_still_works(tmp_path) -> None:
    path = tmp_path / "ghostwire.toml"
    path.write_text(
        """
[general]
timezone = "Asia/Shanghai"

[activitywatch]
base_url = "http://127.0.0.1:5600"
timeout_seconds = 30
hosts = ["auto"]

[report]
default_format = "md"
include_window = true
include_afk = true
include_web = true
include_vim = true
include_input = true

[input_labels]
dominance_ratio = 1.5
""".strip(),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.categorize_terminal == []
    assert config.categorize_browser == []
    assert categorize("Terminal.app", config) == "other"


def test_reporting_window_uses_configured_day_start() -> None:
    config = Config(timezone=ZoneInfo("Asia/Shanghai"), day_start=time(6, 0))

    start, end = config.reporting_window(date(2026, 4, 21))

    assert start == datetime(2026, 4, 21, 6, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert end == datetime(2026, 4, 22, 6, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_reporting_date_rolls_back_before_day_start() -> None:
    config = Config(timezone=ZoneInfo("Asia/Shanghai"), day_start=time(6, 0))

    assert (
        config.reporting_date(datetime(2026, 4, 22, 5, 59, tzinfo=ZoneInfo("Asia/Shanghai")))
        == date(2026, 4, 21)
    )
    assert (
        config.reporting_date(datetime(2026, 4, 22, 6, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
        == date(2026, 4, 22)
    )
