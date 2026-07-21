# Operator onboard — willow-mcp

One-time setup so network tasks work without OpenSSL, hand-edited `mcp.json`, or
knowing which `willow-mcp` binary is which.

## New install (copy/paste)

Use the **venv CLI** (`wmc` or `…/venvs/willow-mcp/bin/willow-mcp`). Do **not**
use bare `willow-mcp` on PATH if the legacy Willow 2.0 `sap_mcp.py` server is
installed — it does not have these commands.

```bash
pip install -e ~/github/willow-mcp
willow-mcp-init
willow-mcp onboard --project-root ~/github/willow --enable-internet --app-id willow
```

Reload the IDE window, then (from willow-2.0 fleet installs):

```bash
cd ~/github/willow-2.0 && ./willow.sh project sync willow
```

Check health:

```bash
willow-mcp doctor --app-id willow --project-root ~/github/willow
```

## Run a network task (one operator command)

```bash
willow-mcp run-net willow --task-file /path/to/script.sh --ttl 30m
willow-mcp worker --lane fast --once
```

`run-net` grants a lease (if needed), signs the exact task, and queues it.
Agents still cannot mint authority — only an interactive operator terminal can.

## What gets created

| Artifact | Location |
|----------|----------|
| Egress private key | `~/.config/willow-mcp/egress/private.pem` |
| Egress public key | `~/.config/willow-mcp/egress/public.pem` |
| Manifest | `~/.config/willow-mcp/egress/manifest.json` |
| MCP env | `WILLOW_MCP_EGRESS_PUBLIC_KEY` in `.cursor/mcp.json` (via onboard or project sync) |

Keys live **outside** `WILLOW_HOME` so Kart sandboxes cannot read the signing key.

## Troubleshooting

```bash
willow-mcp doctor --app-id willow
willow-mcp gates
willow-mcp net-status
```

If `doctor` reports missing egress keys: `willow-mcp setup-egress` (idempotent).
