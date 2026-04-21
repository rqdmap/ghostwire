 # Architecture

 ## Overview

 The system is intentionally split into three layers:

 1. **Local collectors**, one per host, running on the machines that actually hold the data
 2. **Private telemetry server**, running on your VPS, storing daily snapshots and serving aggregated results
 3. **GitHub publisher**, running in GitHub Actions, fetching the final SVG from the server and committing it into the profile repository

 This design exists for one reason: **ActivityWatch and OpenCode are local data sources**. They should be collected locally, not through GitHub runners trying to reach a laptop's `127.0.0.1`.

 ## Data flow

 ```text
 [macOS work machine]                    [Arch home machine]
   launchd                                 systemd timer
      ghostwire collect-and-upload            ghostwire collect-and-upload
       ├─ ActivityWatch HTTP                   ├─ ActivityWatch HTTP
       ├─ OpenCode SQLite                      ├─ OpenCode SQLite
       ├─ sanitize + validate                  ├─ sanitize + validate
       └────────────── PUT HostSnapshot ───────┘
                            │
                            ▼
                  [private telemetry server]
                    ├─ PUT /api/v1/snapshots/{host}/{date}
                    ├─ atomic file storage
                    ├─ aggregate(snapshots) -> Dashboard
                    └─ render_dashboard(dashboard) -> SVG
                            │
                            ▼
                    [GitHub Actions publish]
                      curl /api/v1/dashboard.svg
                      commit assets/dashboard.svg
                      push to rqdmap/rqdmap
 ```

 ## Component responsibilities

 **Local collector**

 The local collector is the only place allowed to touch raw local sources:

 - ActivityWatch at `http://127.0.0.1:5600`
 - OpenCode SQLite at `~/.local/share/opencode/opencode_2.db`, fallback `opencode.db`

 Its responsibilities are:

 - read local raw data
 - classify apps into `terminal`, `browser`, `other`
 - compute daily rhythm and session bursts
 - sanitize the result before it leaves the machine
 - upload a single **HostSnapshot** document to the server

 It does **not** aggregate across hosts, and it does **not** publish to GitHub.

 **Telemetry server**

 The server is deliberately small. It is a snapshot receiver plus dashboard producer.

 Its responsibilities are:

 - authenticate uploads
 - validate uploaded HostSnapshot payloads
 - persist snapshots by `(host_id, date)`
 - aggregate all stored snapshots into a Dashboard view
 - render `dashboard.svg` on demand

 It does **not** access ActivityWatch, and it does **not** need OpenCode installed.

 **GitHub publisher**

 GitHub Actions only performs publication:

 - fetch `dashboard.svg` from the telemetry server
 - write it into `assets/dashboard.svg` in the profile repository
 - commit only if content changed

 GitHub Actions does **not** collect local data and does **not** need self-hosted runners.

 ## Storage model

 The storage model is file-based and idempotent.

 ```text
 <data_dir>/
   work-mac/
     2026-04-21.json
     2026-04-22.json
   home-arch/
     2026-04-21.json
 ```

 The key is `(host_id, date)`, so uploads use **PUT**, not POST. Re-uploading the same host/day overwrites the previous file atomically. This makes retries safe and makes scheduled collection easy to reason about.

 Atomicity is implemented as **tmp file + rename**, which prevents partial writes from becoming visible.

 ## Contracts and privacy boundary

 There are two public data contracts inside the codebase:

 | Contract | Produced by | Consumed by | Purpose |
 |---|---|---|---|
 | `HostSnapshot` | local collector | telemetry server | one host, one day |
 | `Dashboard` | telemetry server | SVG renderer | aggregated dashboard view |

 The privacy boundary is at the collector. The collector must never upload raw private fields. The server should only ever see sanitized aggregates.

 Forbidden fields include:

 - window titles
 - URLs
 - file paths
 - project names
 - real hostnames
 - raw OpenCode session IDs

 OpenCode session IDs are hashed locally before leaving the machine.

 ## OpenCode token accounting

 OpenCode forks copy earlier messages into the forked session. If token usage is summed naively over all assistant messages, token totals become inflated.

 The collector fixes this before building the snapshot:

 - messages are read from the local OpenCode SQLite database
 - cross-session duplicates are identified by `(time_created_ms, role)`
 - when duplicates exist across sessions, only the copy belonging to the earliest session is kept
 - token usage and burst extraction both run on this deduped message set

 This keeps token totals and concurrency metrics aligned. The behavior mirrors the known-good approach already used in `mimir`, but implemented here as a focused Python read-time dedupe step.

 ## Authentication model

 The server uses two bearer tokens with separate capabilities.

 | Token | Used by | Scope |
 |---|---|---|
 | **host token** | macOS / Arch collectors | upload snapshots via PUT |
 | **read token** | GitHub Actions, operators | read dashboard JSON / SVG |

 This split prevents the GitHub publishing path from gaining write access to snapshot storage.

 ## Why this architecture

 This architecture intentionally rejects the older self-hosted-runner approach.

 **Reason 1: locality**

 ActivityWatch and OpenCode live on the host machines. The clean design is to collect data where it lives.

 **Reason 2: debuggability**

 A local scheduled command can be re-run by hand immediately. A GitHub self-hosted runner adds another execution layer, queueing model, runner state, and label routing, which makes failures harder to diagnose.

 **Reason 3: simpler trust boundary**

 GitHub only needs read access to the final rendered output. It does not need write access to the telemetry store and does not need access to local raw sources.

 **Reason 4: idempotence**

 `(host, date)` snapshot upserts are a natural fit for intermittent laptop connectivity. Machines can upload whenever they are online; the latest daily snapshot simply replaces the old one.

 ## Operational model

 **Normal operation**

 - each host runs one scheduled `collect-and-upload`
 - the server accumulates daily snapshots
 - GitHub fetches `dashboard.svg` on its own schedule

 **Backfill**

 Backfill is done from the source host by passing `--date YYYY-MM-DD` to the same collector command and uploading that historical day.

 **Failure handling**

 - if the local collector fails, rerun the same command manually on that machine
 - if upload fails, fix auth or connectivity and rerun the same command
 - if publishing fails, the server remains the source of truth and GitHub can retry later

 ## Key files

 | File | Role |
 |---|---|
 | `ghostwire/collect.py` | ActivityWatch collection and AFK clipping |
 | `ghostwire/opencode.py` | OpenCode SQLite reading, fork dedupe, token extraction |
 | `ghostwire/snapshot.py` | HostSnapshot assembly |
 | `ghostwire/uploader.py` | PUT upload client |
 | `ghostwire/server.py` | FastAPI server and file-backed storage |
 | `ghostwire/aggregate_dashboard.py` | cross-host and cross-day aggregation |
 | `ghostwire/render_svg.py` | Dashboard -> SVG rendering |
 | `docs/deployment.md` | installation and operational setup |

 ## Non-goals

 The current architecture intentionally does **not** include:

 - a relational database
 - WebSocket or realtime transport
 - GitHub self-hosted runners
 - raw event storage on the server
 - public snapshot exposure

 Those would only be justified if the system grows beyond a few hosts or if near-realtime product requirements appear.
