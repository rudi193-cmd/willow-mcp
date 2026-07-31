# Operator onboard — willow-mcp
> **Scope (2026-07-22):** this is the appendix for operators who **already run a
> fleet** — key ceremony, net leases, IDE wiring against existing state. A new,
> standalone install starts from README.md's **Install** section instead
> (`pip install willow-mcp`, or `bash scripts/sandbox-bootstrap.sh` for a
> contributor sandbox).

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

## Trust-root hardening (B-32, B-44)

When the agent and MCP server share your uid, the agent can forge egress authority
by editing its manifest or lease files — **or simply read the egress private key**
(B-44/issue #182): a `chmod 600` file owned by your own uid is not protected
from you. Close the host lane:

```bash
sudo useradd -r -s /usr/sbin/nologin willow-operator   # once per machine
willow-mcp harden-trust-root --project-root ~/github/willow
```

This chowns the manifest/lease roots **and** the egress key directory to
`willow-operator` — the key at owner-only `0600`, stricter than the
world-readable manifests/leases (which the gate still needs to read as an
unprivileged process; the signing key does not).

Reload the IDE. Issue grants, signed tasks, and consent as the trust owner:

```bash
sudo -u willow-operator willow-mcp grant-net hanuman --ttl 30m --reason "push branch"
sudo -u willow-operator willow-mcp sign-net-task hanuman --task-file /path/to/task.sh
sudo -u willow-operator willow-mcp consent set internet true
```

Dry-run first: `willow-mcp harden-trust-root --dry-run`

Verify: `willow-mcp doctor` should report the egress key as no longer
self-readable (`private_key_readable: false` in `net_lease`); as the agent's
own uid, `cat ~/.config/willow-mcp/egress/private.pem` should now fail with
`Permission denied`.

If `doctor` reports the SOIL store is not writable after hardening, restore runtime
paths (store, dispatch, sessions, …) for the MCP server user:

```bash
willow-mcp repair-runtime-perms
```

This keeps `mcp_apps/` and `config/` owned by `willow-operator` while giving the
runtime user write access to `store/` and other MCP working directories.

## PGP-enforced manifests (B-45, issue #183)

`mcp_apps/` ownership above stops the agent from *writing* a manifest, but on
an install that hasn't hardened yet — or any process that reaches the file a
different way — an unsigned manifest is still honored as-is. Set
`WILLOW_PGP_FINGERPRINT` to close that gap outright: an unsigned, tampered,
or wrong-signer manifest gets denied exactly like a missing one.

```bash
willow-mcp sign-manifest hanuman
```

Interactive operator terminal only (same as `sign-net-task`/`sign-db-task` —
`gpg-agent` is unreachable inside Kart). Re-run after any manifest edit; a
changed manifest with a stale signature is denied too.
