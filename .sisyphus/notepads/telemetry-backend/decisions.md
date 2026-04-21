Appended decisions for T11-T13:
- Implemented timeline, rhythm, best-day, and cards builders as pure functions in aw_report/aggregate_dashboard.py.
- Kept model construction inside function bodies for minimal import surface and to preserve the no-circular-dependency constraint.

Appended decisions for T14:
- Added aggregate() at the bottom of aw_report/aggregate_dashboard.py so the existing helper layout remains intact and unchanged.
- Reused the merged daily snapshots as the single source for concurrency, workstation totals, category totals, and model totals to keep the dashboard assembly path consistent.

Appended decisions for T15:
- Chose `string.Template`-style `${VAR}` placeholders for the SVG so rendering can stay dependency-light.
- Kept the template as a plain `.tmpl` SVG document to preserve xmllint compatibility.

Appended decisions for T16:
- Implemented SVG rendering in `aw_report/render_svg.py` by loading the template from disk and binding an explicit placeholder map from `Dashboard` data.
- Added focused renderer tests around XML validity, placeholder resolution, fixture-backed content, and token polyline serialization.

- 2026-04-21 audit verdict basis: keep the audit strict to the supplied checklist, including legacy CLI compatibility and literal grep cleanliness checks

- Added lightweight compatibility shims for the removed report pipeline instead of changing the existing snapshot, aggregate, and render commands.
- Kept the new `snapshot`, `aggregate`, `render`, and `version` commands untouched, then appended the restored legacy commands at the bottom of `cli.py`.
