Appended learnings for T11-T13:
- Keep dashboard builders pure and local to aw_report/aggregate_dashboard.py to avoid circular imports.
- Use zero-fill timelines over the exact 30-day window, and compute 7-day rhythm from the available merged daily rhythm arrays.
- Pyright needs TYPE_CHECKING imports for annotation-only model names when the module stays lightweight.
