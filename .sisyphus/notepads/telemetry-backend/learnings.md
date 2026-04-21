Appended learnings for T11-T13:
- Keep dashboard builders pure and local to aw_report/aggregate_dashboard.py to avoid circular imports.
- Use zero-fill timelines over the exact 30-day window, and compute 7-day rhythm from the available merged daily rhythm arrays.
- Pyright needs TYPE_CHECKING imports for annotation-only model names when the module stays lightweight.

Appended learnings for T14:
- The top-level dashboard aggregator can stay deterministic by wiring existing pure helpers in sequence: merge by date, derive windows, compute concurrency, then materialize dataclasses.
- Fixture-driven end-to-end tests are enough to lock the 30-day window shape, category rollups, and best-day selection without re-testing each helper in detail.

Appended learnings for T15:
- SVG templates stay simplest when they only use `string.Template` placeholders and keep all geometry, fills, and classes untouched.
- A single data-binding table is enough to map every placeholder back to Dashboard fields for later rendering code.

Appended learnings for T16:
- Rendering stays robust when every text placeholder is XML-escaped before `safe_substitute()`, while geometry fields like polyline points stay raw.
- Snapshot-driven dashboard fixtures are sufficient to test SVG rendering end-to-end without introducing a second renderer-specific fixture schema.

- 2026-04-21 audit finding: the new telemetry backend modules and tests are present and passing (`106 passed`), but compliance still fails if legacy entrypoints or legacy module paths are removed

- Restoring the legacy CLI commands required adding compatibility modules for `AWClient`, report rendering, and time-range helpers so `aw_report.cli` could import cleanly.
- `aw-report report|facts|inspect --help` works once the commands are registered at module import time and the missing helpers resolve.
