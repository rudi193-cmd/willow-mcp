---
name: willow-serve
description: Turn willow-mcp OAuth HTTP serve mode on or off on request, toggling both the systemd --user service and the .mcp.json client entry
---

# /willow-serve

Turns willow-mcp's OAuth serve mode **on** or **off** without hand-editing
config. Wraps `scripts/willow-serve`, which manages a systemd `--user` service
for the `--serve` process and adds/removes the matching http entry in
`.mcp.json` so the MCP client connects only while serve is on.

## When to use this

- The user asks to "turn on/off", "start/stop", or "enable/disable" willow-mcp
  serve mode / the OAuth server.
- The user wants to check whether serve mode is currently running.

## Steps

**1. Map the request to an action.**

| User intent | Command |
|-------------|---------|
| turn on / start / enable | `scripts/willow-serve on` |
| turn off / stop / disable | `scripts/willow-serve off` |
| is it on? / status | `scripts/willow-serve status` |
| see logs | `scripts/willow-serve logs` |

**2. First run only — install the unit.** If `on` reports
`unit not installed`, run `scripts/willow-serve install` once (writes the
systemd user unit), then `on` again. Port/host default to `8766`/`127.0.0.1`;
to change them set `WILLOW_MCP_PORT` / `WILLOW_MCP_HOST` before `install`.

**3. Run the command** from the repo root.

**4. After `on` or `off`, tell the user to run `/mcp`.** The `.mcp.json` entry
changed, so the client must reconnect to pick it up. On `on`, if they already
signed in once, the cached credential is reused — no OAuth screen reappears
unless the credential was cleared (that is expected, not a failure).

## What this skill will not do

- It does not hand-edit `.mcp.json` directly — the script owns that toggle so
  the entry and the running service never drift apart.
- It does not disable OAuth or the identity-binding gate to make serve mode
  "easier". Serve mode is auth-gated by design; leave it that way.
