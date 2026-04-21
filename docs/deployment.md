# Deployment

Three independent pieces:

1. **Server** — runs on your VPS, accepts uploads and serves the rendered dashboard.
2. **Local collector** — runs on each machine (macOS, Arch), uploads daily snapshot.
3. **GitHub Action** — pulls `dashboard.svg` from the server and commits it into your profile repo.

There is no GitHub self-hosted runner anywhere in this design.

---

## 1. Server (your VPS)

### Install

```bash
git clone https://github.com/<you>/ghostwire.git
cd ghostwire
pip install -e ".[server]"
```

### Generate two tokens

```bash
ghostwire gen-token   # → host token   (used by macOS / Arch to PUT)
ghostwire gen-token   # → read token   (used by GitHub Action to GET)
```

Keep both somewhere safe. The host token is a write capability, the read token is a read capability.

### Run

```bash
export GHOSTWIRE_HOST_TOKEN=<host-token>
export GHOSTWIRE_READ_TOKEN=<read-token>
ghostwire serve --data-dir /var/lib/ghostwire --host 0.0.0.0 --port 8000
```

Put it behind nginx / Caddy with TLS. Example Caddy block:

```
telemetry.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

### Storage layout

```
/var/lib/ghostwire/
    work-mac/2026-04-21.json
    home-arch/2026-04-21.json
    ...
```

Writes are atomic (`tmp + rename`). Snapshots are upserted by `(host, date)`.

### systemd unit

`/etc/systemd/system/ghostwire.service`:

```ini
[Unit]
Description=Ghostwire telemetry server
After=network.target

[Service]
ExecStart=/usr/local/bin/ghostwire serve --data-dir /var/lib/ghostwire --port 8000
Environment=GHOSTWIRE_HOST_TOKEN=...
Environment=GHOSTWIRE_READ_TOKEN=...
Restart=on-failure
User=ghostwire

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now ghostwire
journalctl -u ghostwire -f
```

---

## 2. Local collector

### Install on each machine

```bash
git clone https://github.com/<you>/ghostwire.git
cd ghostwire
pip install -e .
```

Make sure `~/.config/ghostwire/ghostwire.toml` (or `./ghostwire.toml`) defines a `[host_meta.<host_id>]` matching the host you'll pass on the CLI.

### Test once by hand

```bash
export GHOSTWIRE_UPLOAD_TOKEN=<host-token>
ghostwire collect-and-upload \
    --host work-mac \
    --server https://telemetry.example.com
```

If this works, the only remaining job is "run the same command every day".

### macOS — launchd

`~/Library/LaunchAgents/com.rqdmap.ghostwire.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.rqdmap.ghostwire</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/ghostwire</string>
        <string>collect-and-upload</string>
        <string>--host</string>
        <string>work-mac</string>
        <string>--server</string>
        <string>https://telemetry.example.com</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>GHOSTWIRE_UPLOAD_TOKEN</key><string>...</string>
    </dict>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>23</integer>
        <key>Minute</key><integer>30</integer>
    </dict>
    <key>StandardOutPath</key><string>/tmp/ghostwire.log</string>
    <key>StandardErrorPath</key><string>/tmp/ghostwire.log</string>
</dict>
</plist>
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.rqdmap.ghostwire.plist
launchctl start com.rqdmap.ghostwire
tail -f /tmp/ghostwire.log
```

### Arch — systemd timer

`~/.config/systemd/user/ghostwire.service`:

```ini
[Unit]
Description=Ghostwire collect+upload

[Service]
Type=oneshot
Environment=GHOSTWIRE_UPLOAD_TOKEN=...
ExecStart=/usr/bin/ghostwire collect-and-upload --host home-arch --server https://telemetry.example.com
StandardOutput=append:%h/.cache/ghostwire.log
StandardError=append:%h/.cache/ghostwire.log
```

`~/.config/systemd/user/ghostwire.timer`:

```ini
[Unit]
Description=Run Ghostwire daily

[Timer]
OnCalendar=*-*-* 23:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now ghostwire.timer
systemctl --user list-timers | grep ghostwire
```

### Debugging

The local collector is a normal command. If a scheduled run fails, run the exact command yourself:

```bash
GHOSTWIRE_UPLOAD_TOKEN=... ghostwire collect-and-upload --host work-mac --server https://telemetry.example.com
```

Common failure modes:

- `connect refused 127.0.0.1:5600` → ActivityWatch isn't running.
- `host config not found` → missing `[host_meta.<host_id>]` in `ghostwire.toml`.
- `PUT ... 401/403` → wrong upload token.
- `PUT ... 400 host_id mismatch` → URL host doesn't match the snapshot body.

---

## 3. GitHub Actions publish

In your **profile** repo (e.g. `rqdmap/rqdmap`), add a `assets/` directory and reference `assets/dashboard.svg` in the README:

```markdown
<picture>
  <img src="assets/dashboard.svg" alt="dashboard"/>
</picture>
```

In **this** repo (`ghostwire`), `.github/workflows/publish.yml` is already wired. Set these repo secrets:

| Secret | Value |
|---|---|
| `TELEMETRY_URL` | `https://telemetry.example.com` |
| `TELEMETRY_READ_TOKEN` | the read token from step 1 |
| `PROFILE_REPO` | e.g. `rqdmap/rqdmap` |
| `PROFILE_REPO_TOKEN` | a PAT with `contents:write` on the profile repo |

The workflow runs daily on cron and is also `workflow_dispatch`-triggerable. It only `curl`s the SVG from your server and commits it.

---

## End-to-end check

```bash
curl -H "Authorization: Bearer $READ" https://telemetry.example.com/api/v1/dashboard.json | jq .header
curl -H "Authorization: Bearer $READ" https://telemetry.example.com/api/v1/dashboard.svg | xmllint --noout - && echo OK
```
