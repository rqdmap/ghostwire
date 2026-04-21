from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


def render_json(payload: Any) -> str:
    if is_dataclass(payload):
        payload = asdict(payload)  # type: ignore[arg-type]
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
