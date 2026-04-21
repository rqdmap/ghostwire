Appended decisions for T11-T13:
- Implemented timeline, rhythm, best-day, and cards builders as pure functions in aw_report/aggregate_dashboard.py.
- Kept model construction inside function bodies for minimal import surface and to preserve the no-circular-dependency constraint.

Appended decisions for T14:
- Added aggregate() at the bottom of aw_report/aggregate_dashboard.py so the existing helper layout remains intact and unchanged.
- Reused the merged daily snapshots as the single source for concurrency, workstation totals, category totals, and model totals to keep the dashboard assembly path consistent.
