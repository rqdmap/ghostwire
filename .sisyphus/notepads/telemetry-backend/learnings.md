Appended learnings for T11-T13:
- Keep dashboard builders pure and local to aw_report/aggregate_dashboard.py to avoid circular imports.
- Use zero-fill timelines over the exact 30-day window, and compute 7-day rhythm from the available merged daily rhythm arrays.
- Pyright needs TYPE_CHECKING imports for annotation-only model names when the module stays lightweight.

Appended learnings for T14:
- The top-level dashboard aggregator can stay deterministic by wiring existing pure helpers in sequence: merge by date, derive windows, compute concurrency, then materialize dataclasses.
- Fixture-driven end-to-end tests are enough to lock the 30-day window shape, category rollups, and best-day selection without re-testing each helper in detail.
