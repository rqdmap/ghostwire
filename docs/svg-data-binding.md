# SVG Data Binding

| Placeholder | Dashboard Field | Notes |
|---|---|---|
| `${ACTIVE_30D_H}` | `cards.active_30d_seconds / 3600` formatted 1dp | e.g. "42.8" |
| `${ACTIVE_DELTA_PCT}` | `cards.active_30d_delta_pct` | integer |
| `${TOKENS_7D_M}` | `cards.tokens_7d // 1_000_000` | integer millions |
| `${TOKENS_DELTA_PCT}` | `cards.tokens_7d_delta_pct` | integer |
| `${WS1_LABEL}` | `cards.workstations[0].label` | |
| `${WS1_PLATFORM}` | `cards.workstations[0].platform` | |
| `${WS1_H}` | `cards.workstations[0].seconds / 3600` formatted 1dp + "h" | |
| `${WS2_LABEL}` | `cards.workstations[1].label` | |
| `${WS2_PLATFORM}` | `cards.workstations[1].platform` | |
| `${WS2_H}` | `cards.workstations[1].seconds / 3600` formatted 1dp + "h" | |
| `${SESSION_AVG}` | `cards.session_load.avg_concurrent` formatted 1dp | |
| `${SESSION_PEAK}` | `cards.session_load.peak_concurrent` | integer |
| `${SESSION_RETURN_M}` | `cards.session_load.return_median_seconds // 60` | minutes |
| `${TOKEN_LINE_POINTS}` | computed from `timeline_30d[*].tokens` mapped to chart y-coords | polyline points string |
| `${BEST_DAY_LABEL}` | `best_day.active_seconds/3600 formatted 1dp + "h · " + best_day.tokens//1000 + "k"` | |
| `${SYNCED_DATE}` | `header.synced_at[:10]` | YYYY-MM-DD |
| `${APP1_H}` | `applications_30d[0].seconds / 3600` formatted 1dp + "h" | terminal |
| `${APP2_H}` | `applications_30d[1].seconds / 3600` formatted 1dp + "h" | browser |
| `${APP3_H}` | `applications_30d[2].seconds / 3600` formatted 1dp + "h" | other |
| `${MODEL1_T}` | `models_30d[0].tokens / 1_000_000` formatted 1dp + "M" | |
| `${MODEL2_T}` | `models_30d[1].tokens / 1_000_000` formatted 1dp + "M" | |
| `${MODEL3_T}` | `models_30d[2].tokens / 1_000_000` formatted 1dp + "M" | |
| `${RHYTHM_PEAK_H}` | computed from `rhythm_7d` — hour with max value, formatted "HH:00" | |
