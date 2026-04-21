Appended decisions for T11-T13:
- Implemented timeline, rhythm, best-day, and cards builders as pure functions in aw_report/aggregate_dashboard.py.
- Kept model construction inside function bodies for minimal import surface and to preserve the no-circular-dependency constraint.
