from __future__ import annotations

from pathlib import Path
from string import Template
from xml.sax.saxutils import escape

from aw_report.models import Dashboard, TimelineEntry

TEMPLATE_PATH = Path(__file__).parent / "templates" / "dashboard.svg.tmpl"


def _rhythm_peak_hour(rhythm_7d: list[int]) -> str:
    if not rhythm_7d:
        return "00:00"
    peak_h = rhythm_7d.index(max(rhythm_7d))
    return f"{peak_h:02d}:00"


def _h(seconds: int | float) -> str:
    return f"{seconds / 3600:.1f}h"


def _token_line_points(
    timeline_30d: list[TimelineEntry],
    chart_width: int = 688,
    chart_baseline: int = 240,
    chart_top: int = 8,
) -> str:
    """Map 30 days of token totals to polyline points using the SVG chart scale."""
    if not timeline_30d:
        return ""

    tokens = [entry.tokens for entry in timeline_30d]
    max_t = max(tokens) if max(tokens) > 0 else 1
    span = chart_baseline - chart_top
    slot = chart_width / len(tokens)
    points: list[str] = []

    for index, token_total in enumerate(tokens):
        cx = int(slot * index + slot / 2)
        y = int(chart_baseline - (token_total / max_t) * span)
        y = max(chart_top, min(chart_baseline, y))
        points.append(f"{cx},{y}")

    return " ".join(points)


def _xml_text(value: object) -> str:
    return escape(str(value))


def render_dashboard(dashboard: Dashboard) -> str:
    tmpl = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))

    cards = dashboard.cards
    workstations = cards.workstations
    session_load = cards.session_load
    applications = dashboard.applications_30d
    models = dashboard.models_30d
    best_day = dashboard.best_day

    variables = {
        "ACTIVE_30D_H": _xml_text(f"{cards.active_30d_seconds / 3600:.1f}"),
        "ACTIVE_DELTA_PCT": _xml_text(cards.active_30d_delta_pct),
        "TOKENS_7D_M": _xml_text(cards.tokens_7d // 1_000_000),
        "TOKENS_DELTA_PCT": _xml_text(cards.tokens_7d_delta_pct),
        "WS1_LABEL": _xml_text(workstations[0].label if len(workstations) > 0 else ""),
        "WS1_PLATFORM": _xml_text(
            workstations[0].platform if len(workstations) > 0 else ""
        ),
        "WS1_H": _xml_text(
            _h(workstations[0].seconds) if len(workstations) > 0 else "0.0h"
        ),
        "WS2_LABEL": _xml_text(workstations[1].label if len(workstations) > 1 else ""),
        "WS2_PLATFORM": _xml_text(
            workstations[1].platform if len(workstations) > 1 else ""
        ),
        "WS2_H": _xml_text(
            _h(workstations[1].seconds) if len(workstations) > 1 else "0.0h"
        ),
        "SESSION_AVG": _xml_text(f"{session_load.avg_concurrent:.1f}"),
        "SESSION_PEAK": _xml_text(session_load.peak_concurrent),
        "SESSION_RETURN_M": _xml_text(session_load.return_median_seconds // 60),
        "TOKEN_LINE_POINTS": _token_line_points(dashboard.timeline_30d),
        "BEST_DAY_LABEL": _xml_text(
            f"{best_day.active_seconds / 3600:.1f}h · {best_day.tokens // 1000}k"
        ),
        "SYNCED_DATE": _xml_text(dashboard.header.synced_at[:10]),
        "APP1_H": _xml_text(
            _h(applications[0].seconds) if len(applications) > 0 else "0.0h"
        ),
        "APP2_H": _xml_text(
            _h(applications[1].seconds) if len(applications) > 1 else "0.0h"
        ),
        "APP3_H": _xml_text(
            _h(applications[2].seconds) if len(applications) > 2 else "0.0h"
        ),
        "MODEL1_T": _xml_text(
            f"{models[0].tokens / 1_000_000:.1f}M" if len(models) > 0 else "0.0M"
        ),
        "MODEL2_T": _xml_text(
            f"{models[1].tokens / 1_000_000:.1f}M" if len(models) > 1 else "0.0M"
        ),
        "MODEL3_T": _xml_text(
            f"{models[2].tokens / 1_000_000:.1f}M" if len(models) > 2 else "0.0M"
        ),
        "RHYTHM_PEAK_H": _xml_text(_rhythm_peak_hour(dashboard.rhythm_7d)),
    }

    return tmpl.safe_substitute(variables)
