# Deployment Guide

## Self-Hosted Runner Setup

The `collect.yml` workflow must run on a **self-hosted runner** because it needs access to the local ActivityWatch instance at `http://127.0.0.1:5600`.

### macOS (工作机)

1. Download the runner from GitHub: Settings → Actions → Runners → New self-hosted runner
2. Follow the installation instructions for macOS
3. Start the runner as a service: `./svc.sh install && ./svc.sh start`
4. Add a label `work-mac` to the runner

### Arch Linux (家里机)

1. Download the runner for Linux
2. Install as systemd service
3. Add a label `home-arch`

### Required Secrets

Add these secrets to the GitHub repository:

| Secret | Value |
|---|---|
| `SNAPSHOTS_REPO` | `your-username/snapshots-private` |
| `SNAPSHOTS_DEPLOY_KEY` | Private SSH key with write access to the snapshots repo |

### aw-report.toml

Ensure the aw-report.toml on each host has a `[host_meta]` section:

```toml
[host_meta.work-mac]
label = "工作机"
platform = "macOS"

[host_meta.home-arch]
label = "家里机"
platform = "Arch Linux"
```

### Running Manually

Trigger a manual snapshot collection:
```bash
aw-report snapshot day --host work-mac --out /tmp/snap.json
```

Or trigger via GitHub Actions with `workflow_dispatch`.
