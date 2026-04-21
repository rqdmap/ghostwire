from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def render_markdown(payload: Any) -> str:
    if is_dataclass(payload):
        payload = asdict(payload)  # type: ignore[arg-type]
    lines = ["# Report", ""]
    for key, value in payload.items():
        lines.append(f"- **{key}**: {value}")
    return "\n".join(lines) + "\n"
