from __future__ import annotations

from importlib import import_module

from aw_report.config import Config, load_config

categorize = import_module("aw_report.categorize").categorize


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
    path = tmp_path / "aw-report.toml"
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

[categorize.terminal]
allow = ["Neovim"]

[categorize.browser]
allow = ["Safari"]
""".strip(),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.categorize_terminal == ["Neovim"]
    assert config.categorize_browser == ["Safari"]


def test_load_config_without_categorize_sections_still_works(tmp_path) -> None:
    path = tmp_path / "aw-report.toml"
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
