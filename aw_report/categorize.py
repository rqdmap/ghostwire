from __future__ import annotations

from typing import Literal

from aw_report.config import Config

Category = Literal["terminal", "browser", "other"]


def categorize(app_name: str, config: Config) -> Category:
    if app_name in config.categorize_terminal:
        return "terminal"
    if app_name in config.categorize_browser:
        return "browser"
    return "other"
