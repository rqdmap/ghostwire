Appended issues for T15:
- The source `assets/dashboard-demo.svg` was not present in the working tree, so the template was produced directly from the requested binding set and dashboard schema.

- 2026-04-21 compliance audit: `aw-report report day --help` fails with `No such command 'report'`, so legacy CLI compatibility is broken
- 2026-04-21 compliance audit: `aw_report/aggregate.py` is missing, so the legacy aggregate module/functions were removed or not preserved
- 2026-04-21 compliance audit: privacy-key grep is not clean because `aw_report/sanitize.py` contains `window_title`, `file_path`, and `project_name`, and `aw_report/cli.py` uses a `file_path` variable

- The restored CLI imports depended on helper modules that were no longer present, so small shims were added to preserve the old command surface.
