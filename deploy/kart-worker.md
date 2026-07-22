# Kart worker cutover — operator install note

Decommission slice 2 delivers **successor unit files** only. Installing or
restarting services on the host is the operator's act.

## Prerequisites

- `willow-mcp` installed in a venv (paths below assume `%h/github/willow-mcp/.venv`)
- Postgres `willow_20` reachable with schema mapping confirmed for `tasks`
- `~/github/.willow/env` exports `WILLOW_HOME`, `WILLOW_STORE_ROOT`, `WILLOW_APP_ID`, PG vars

## One-liner (user units)

```bash
install -D -m 0644 deploy/kart-worker.service \
  ~/.config/systemd/user/kart-worker.service && \
install -D -m 0644 deploy/kart-worker-batch.service \
  ~/.config/systemd/user/kart-worker-batch.service && \
systemctl --user daemon-reload
```

Edit `ExecStart` / `WorkingDirectory` in the installed files if your checkout or
venv path differs from `%h/github/willow-mcp`.

## Cutover (when ready)

1. Stop legacy workers: `systemctl --user stop kart-worker kart-worker-batch`
2. Install units above (or symlink from this repo)
3. Start successors: `systemctl --user start kart-worker kart-worker-batch`
4. Verify: `willow-mcp fleet-health` shows alive workers; SOIL
   `willow/loops/heartbeat` records `kart_worker` / `kart_worker_batch` tick

Rollback: restore the previous unit files from backup and restart the legacy
`willow-2.0/willow.sh kart-worker` ExecStart lines.

## Manual drain (no systemd)

```bash
cd ~/github/willow-mcp && .venv/bin/python -m willow_mcp.worker --lane fast --once
```
