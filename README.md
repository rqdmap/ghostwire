# Ghostwire

Ghostwire is a private telemetry pipeline for turning local **ActivityWatch** and **OpenCode** usage into a sanitized dashboard that can be published to a GitHub profile.

The system is intentionally split into three parts:

- a **local collector** that reads ActivityWatch and OpenCode on each machine
- a **private telemetry server** that stores one daily snapshot per host and builds the aggregated dashboard
- a **GitHub Actions publisher** that fetches the final SVG and commits it into a profile repository

This architecture exists to keep raw local data on the machines that generated it. GitHub never talks to your laptop's `127.0.0.1`, and the server never needs access to raw ActivityWatch events or the local OpenCode database.

## What Ghostwire does

- Collects **active window time** from ActivityWatch and groups it into `terminal`, `browser`, and `other`
- Reads **OpenCode** sessions from the local SQLite database and dedupes fork-copied messages before token accounting
- Builds a per-host **HostSnapshot** for a single logical day
- Uploads snapshots with idempotent **PUT** semantics to a small private FastAPI server
- Aggregates stored snapshots into a **Dashboard** JSON document and renders a publishable **SVG**
- Publishes that SVG into a GitHub profile repository through `.github/workflows/publish.yml`

## Architecture

```text
[local host: macOS / Linux / Windows]
  ghostwire collect-and-upload
    ├─ ActivityWatch HTTP
    ├─ OpenCode SQLite
    ├─ sanitize + validate
    └─ PUT /api/v1/snapshots/{host}/{date}
                      │
                      ▼
            [private telemetry server]
              ├─ file-backed snapshot storage
              ├─ aggregate(...) -> Dashboard
              └─ render_dashboard(...) -> SVG
                      │
                      ▼
              [GitHub Actions publisher]
                fetch dashboard.svg
                commit to profile repo
```

The storage model is file-based and keyed by **`(host_id, date)`**. Re-uploading the same day overwrites the previous snapshot atomically via **tmp file + rename**, which makes retries safe and keeps the operational model simple.

## Quick start

**Requirements**: Python 3.11+, ActivityWatch on collector hosts, and optionally OpenCode on machines where you want token/session metrics. The server path additionally needs `fastapi` and `uvicorn`, which are exposed through the `server` extra.

**1. Install**

```bash
pip install -e .
pip install -e ".[server]"
```

Typical usage is:

- collector host: `pip install -e .`
- telemetry server: `pip install -e ".[server]"`

**2. Create a config file**

Ghostwire looks for config in `./ghostwire.toml`, `~/.config/ghostwire/ghostwire.toml`, and on Windows `%APPDATA%\ghostwire\ghostwire.toml`.

```toml
[general]
timezone = "Asia/Shanghai"
day_start = "06:00"

[activitywatch]
base_url = "http://127.0.0.1:5600"
timeout_seconds = 30
hosts = ["auto"]

[upload]
server_url = "https://telemetry.example.com"

[categorize.terminal]
allow = ["Alacritty", "iTerm2", "kitty", "WezTerm", "Code", "Terminal"]

[categorize.browser]
allow = ["Google Chrome", "Chromium", "Firefox", "Safari", "Arc"]

[host_meta.work-mac]
label = "Work"
platform = "macOS"

[host_meta.home-arch]
label = "Home"
platform = "Arch Linux"
```

**3. Start the telemetry server**

```bash
ghostwire gen-token   # host token
ghostwire gen-token   # read token

export GHOSTWIRE_HOST_TOKEN=<host-token>
export GHOSTWIRE_READ_TOKEN=<read-token>

ghostwire serve --data-dir /var/lib/ghostwire --host 0.0.0.0 --port 8000
```

Server endpoints:

| Endpoint | Purpose |
|---|---|
| `PUT /api/v1/snapshots/{host_id}/{date}` | store one host/day snapshot |
| `GET /api/v1/dashboard.json` | return aggregated dashboard JSON |
| `GET /api/v1/dashboard.svg` | return rendered SVG dashboard |
| `GET /healthz` | liveness probe |

**4. Collect and upload from a machine**

```bash
export GHOSTWIRE_UPLOAD_TOKEN=<host-token>

ghostwire collect-and-upload \
  --host work-mac \
  --server https://telemetry.example.com
```

For a dry run or inspection, write a local snapshot instead:

```bash
ghostwire collect --host work-mac --out snapshot.json
```

**5. Publish to a profile repository**

The included workflow `.github/workflows/publish.yml` fetches `dashboard.svg` from the telemetry server and commits it into a GitHub profile repo. In that profile repo, reference the generated asset from the profile README:

```markdown
<picture>
  <img src="assets/dashboard.svg" alt="dashboard" />
</picture>
```

## CLI surface

| Command | Purpose |
|---|---|
| `ghostwire version` | print package version |
| `ghostwire collect --host <id>` | build a local `HostSnapshot` JSON |
| `ghostwire upload --in <file>` | upload an existing snapshot |
| `ghostwire collect-and-upload --host <id>` | one-shot local collection plus upload |
| `ghostwire serve` | run the telemetry server |
| `ghostwire gen-token` | generate bearer tokens |

Useful flags include `--date YYYY-MM-DD` for backfill, `--skip-opencode` when OpenCode is unavailable, `--save <path>` to keep a copy during upload, and `--config <path>` to override config discovery.

## Privacy model

Ghostwire is designed around a hard privacy boundary at the collector.

- The collector may read raw local sources.
- The server only receives **sanitized aggregates**.
- The dashboard must not expose raw hostnames, raw OpenCode session IDs, window titles, URLs, paths, or project names.
- OpenCode session IDs are hashed locally before leaving the host.

This is the core design constraint of the project, not an implementation detail.

## Documentation

- `docs/architecture.md` explains the system split, storage model, contracts, and privacy boundary.
- `docs/deployment.md` covers VPS setup, local scheduling, and GitHub publication.
- `docs/svg-data-binding.md` documents how dashboard fields map into the rendered SVG.
