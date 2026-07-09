# willow-mcp

[![PyPI](https://img.shields.io/pypi/v/willow-mcp)](https://pypi.org/project/willow-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-1.0-blue)](https://modelcontextprotocol.io)

Agent-neutral MCP server with persistent memory and task execution. Works with any MCP client: Claude Code, Claude Desktop, Cursor, or any custom agent that speaks stdio MCP.

**Three storage backends in one server:**
- **SOIL store** — SQLite-backed local key/value store with full-text search and soft delete
- **Postgres knowledge base** — multi-keyword searchable knowledge graph
- **Kart task queue** — sandboxed task executor for shell commands and scripts

Every tool call is authorized via a filesystem-based manifest ACL — no ACL database, no external auth service. See [Authorization](#authorization).

## Install

```bash
pip install willow-mcp
```

Requires Python 3.11+. Postgres is optional — SOIL store works standalone.

```bash
willow-mcp-init    # scaffold $WILLOW_HOME (idempotent)
```

Runtime layout: [docs/design/product-layout.md](docs/design/product-layout.md) (LOCKED).

## Tools

| Tool | Description |
|------|-------------|
| `store_put` | Write record (JSON object) to SQLite store |
| `store_get` | Read record by `record_id` |
| `store_list` | List all records in a collection |
| `store_update` | Update an existing record |
| `store_search` | Multi-keyword AND search in a collection |
| `store_delete` | Soft-delete a record by `record_id` |
| `store_search_all` | Search across all collections |
| `knowledge_ingest` | Add a knowledge atom (requires a confirmed schema mapping — see `schema_confirm_mapping`) |
| `knowledge_search` | Multi-keyword search in the Postgres knowledge base |
| `kb_at` | Fetch a single knowledge atom by ID |
| `kb_promote` | Change an atom's domain (requires a confirmed schema mapping) |
| `kb_journal` | Add a journal-domain knowledge atom (requires a confirmed schema mapping) |
| `kb_startup_continuity` | Fetch atoms tagged/domained for startup continuity |
| `schema_confirm_mapping` | Confirm (optionally correct) a table's column mapping, unlocking its write tools. `preview=True` dry-runs it and renders a **sample row** so you can see what each field actually resolves to before trusting a name match — see [docs/design/schema-adaptation.md](docs/design/schema-adaptation.md) |
| `task_submit` | Submit task to Kart queue |
| `task_status` | Check task status |
| `task_list` | List pending tasks |
| `agent_route` | Route a task to a target agent, recording the decision |
| `agent_dispatch_result` | Record the result of a dispatched agent task |
| `dispatch_send` | Create dispatch packet (`meta.json` + `assignment.md`) |
| `dispatch_read` | Read dispatch assignment and status |
| `dispatch_list` | List dispatch packets |
| `dispatch_accept` | Specialist accepts packet (pending → working) |
| `handoff_write_v4` | Complete work — `handoff.json` + `closeout.md` |
| `handoff_read` | Read handoff for a dispatch |
| `verify_handoff` | Orchestrator verifies completion |
| `agent_clear` | Clear specialist for next packet |
| `session_read` | Read thin session state file |
| `fleet_status` | List agents registered in the fleet |
| `fleet_health` | Task queue counts by status, live worker heartbeats, and whether the queue is `stranded` |
| `context_save` | Save ephemeral per-identity working state under a key, with an optional TTL (SOIL-backed, no Postgres) |
| `context_get` | Read a saved context; `expired` (and purged) once its TTL passes |
| `context_list` | List your saved context keys and expiry times (expired ones skipped) |
| `context_expire` | Delete a saved context before its TTL |
| `receipts_tail` | Read your own most-recent tool-call receipts — a self-audit trail scoped to your `app_id` |
| `diagnostic_summary` | Self-check: store/Postgres/schema/manifest/bindings/worker/consent/egress-lease/env health, with a verdict and named fixes. Ungated — see below |

### Egress needs three keys

A task that reaches the network requires **all three** of these, and any one
missing denies before anything is written:

| Key | Question | Where | Turned by |
|---|---|---|---|
| `task_net` | May this app *ever* request egress? | `mcp_apps/<app_id>/manifest.json` | operator, granted once |
| `consent.internet` | Is egress permitted *right now*? | `$WILLOW_HOME/settings.global.json` | operator, flipped freely |
| egress lease | For *this app*, until *when*? | `mcp_apps/_net_leases/<app_id>.json` | operator, `willow-mcp grant-net`, expires on its own |

```jsonc
// $WILLOW_HOME/settings.global.json — the off switch
{ "consent": { "internet": false, "cloud_llm": true, "lan": false } }
```

```console
$ willow-mcp grant-net myapp --ttl 30m --reason "publish the release"
$ willow-mcp net-status          # what is live, and for how much longer
$ willow-mcp revoke-net myapp    # or just wait; the ceiling is 3h
```

Setting `consent.internet` to `false` stops network tasks **fleet-wide**,
immediately, without editing a single manifest. `task_net` is a capability
(rarely granted, deliberately excluded from `full_access`); `consent.internet` is
a switch; the lease is a **time-boxed grant** that an agent may ask for and never
issue. No MCP tool can mint one — `grant-net` is local CLI only, exactly like
`confirm-binding`. An agent may *request* egress and may never *grant it to
itself*.

Consent and leases are both read **fail-closed**: a missing file, an unparseable
file, a non-boolean value (`"true"`, `1`), a lease past its deadline, a deadline
with no timezone, or a lease record naming a *different* app than the file it sits
in — all read as denied. Absence is not consent, and a name is not an identity.
willow-mcp only reads the consent policy — it is authored by willow-2.0's
`global_settings.py`. That module also keeps a flat `consent.json` **mirror**,
rewritten on every save; willow-mcp reads it only when the canonical file is
absent. Because it is written constantly and read almost never, it can drift
silently, and **deleting it does not keep it gone** — the next save recreates it.
If the two disagree, `diagnostic_summary` reports an error naming both values
rather than quietly obeying one of them (B-30).

#### The residual, stated plainly

On a host where the agent and the MCP server run as the same uid, the agent can
write the very files that authorize its egress. Leases make a self-grant *expire*
and *leave a record*, and the PreToolUse hook blocks the obvious attempts — but
the operating system is not stopping it. `diagnostic_summary` names exactly which
keys the running process could forge, under `checks.net_lease.self_writable`.

The control is ownership. Put `mcp_apps/` and `mcp_apps/_net_leases/` under a uid
the agent does not run as, then:

```console
$ export WILLOW_MCP_STRICT_TRUST_ROOT=1   # refuse egress when the keys are self-writable
```

Strict mode is **off by default** because turning it on before that separation
exists would deny egress on every current install. This is tracked as B-32 in
`docs/BUGS.md`; requesting egress and confirming it are separate authorities, and
until the filesystem says so, only convention does.

### Running the task worker

`task_submit` only *queues* a task. A worker process executes it, sandboxed with
bubblewrap. Without one running, tasks stay `pending` forever:

```bash
willow-mcp worker --lane fast     # daemon; polls until stopped
willow-mcp worker --once          # drain what's queued, then exit
```

The engine is [`kartikeya`](https://pypi.org/project/kartikeya/), a hard
dependency — a base `pip install willow-mcp` ships a working drainer.

A running worker publishes a heartbeat under `$WILLOW_HOME/worker_heartbeat/`,
which `fleet_health` reads back:

```json
{"pending": 3, "running": 0, "completed": 12, "failed": 0, "total": 15,
 "workers": {"alive": 0, "workers": [{"pid": 4242, "state": "dead", ...}]},
 "stranded": true}
```

**`stranded: true` means there is pending work and no live worker** — the
distinction between "queued, it'll run" and "queued, nothing is listening."
`diagnostic_summary` raises the same condition as a named `worker` problem. A
worker is `alive` (ticking), `stale` (process up, loop wedged), or `dead` (pid
gone). Heartbeats are advisory telemetry: no permission decision reads them, and
reads verify the recorded pid is a live local process, so a forged file naming a
dead pid reads `dead`.

`knowledge_search`/`kb_at`/`kb_startup_continuity` and `fleet_status` adapt to
whatever your host database's real columns are named — see
[docs/design/schema-adaptation.md](docs/design/schema-adaptation.md).
`knowledge_ingest`/`kb_journal`/`kb_promote` refuse to write
(`unconfirmed_schema`) until you've reviewed and confirmed that mapping via
`schema_confirm_mapping` — the [`schema-confirm` skill](skills/schema-confirm.md)
walks through that.

Every tool requires an `app_id` param, checked against a manifest at
`$WILLOW_HOME/mcp_apps/<app_id>/manifest.json` — see [Authorization](#authorization).
The one exception is **`diagnostic_summary`**, which is intentionally ungated: it
is the tool you reach for when your manifest or database is misconfigured, so
gating it behind a permission would make the diagnostic itself undiagnosable. It
discloses only the caller's own configuration — never fleet rows or vault
secrets — and in serve mode still requires a confirmed identity and redacts
absolute filesystem paths.

## MCP config

Repo-local configs (`.cursor/mcp.json`, `.mcp.json`) wire **willow-mcp** plus
**codebase-memory-mcp** for graph-augmented code search while developing this
package. Install the CBM binary to `~/.local/bin/codebase-memory-mcp`, then
index this repo (`project: home-sean-campbell-github-willow-mcp`).

`willow-mcp`'s entry points at a repo-local venv rather than a bare `python3` —
your host interpreter may not have `pip` or the `mcp` package installed (a
missing import here crashes the stdio server before the handshake, which
shows up as a client-side reconnect failure). Set it up once per clone:

```bash
python3 -m venv .venv
.venv/bin/python3 -m pip install -e .
```

Minimal single-server config (path is relative to the repo root, so this
works unmodified on any clone once the venv above exists):

```json
{
  "mcpServers": {
    "willow-mcp": {
      "type": "stdio",
      "command": ".venv/bin/python3",
      "args": ["-m", "willow_mcp"]
    },
    "codebase-memory-mcp": {
      "type": "stdio",
      "command": "codebase-memory-mcp",
      "args": []
    }
  }
}
```

Point `WILLOW_PG_DB` / `WILLOW_STORE_ROOT` at your host fleet store when you
need Postgres knowledge or shared SOIL data.

You can also run the full [willow-2.0](https://github.com/rudi193-cmd/willow-2.0) server directly — the tool API is identical, apps work against both transparently.

## HTTP serve mode (OAuth)

> Serve mode is **2.0.0+**. Until the 2.0.0 release lands on PyPI, install from
> source (`pip install -e .` in a clone) to use it.

Beyond stdio, willow-mcp can run as an HTTP server that authenticates callers
with **OAuth 2.0 + PKCE** against Google or Apple as the upstream identity
provider. Signing in proves *who* a caller is; a separate, operator-controlled
**identity binding** step maps that identity to an `app_id` before any tool
permission applies. An authenticated-but-unbound caller is denied exactly like
an unmanifested `app_id` — fail closed, never fail open.

**1. Store provider credentials in the local vault** (secrets are prompted, so
they never land in shell history or a process listing):

```bash
willow-mcp setup --google-client-id "<client-id>"        # prompts for the secret
# or, for Apple:
willow-mcp setup --apple-team-id "<team>" --apple-client-id "<svc>" \
                 --apple-key-id "<kid>" --apple-p8-key-path ./AuthKey.p8
```

**2. Run the server:**

```bash
python3 -m willow_mcp --serve --port 8765 --host 127.0.0.1
```

`--port`/`--host` take precedence over `WILLOW_MCP_PORT`/`WILLOW_MCP_HOST`,
which take precedence over the defaults (`8765` / `127.0.0.1`). Point an HTTP
MCP client at `http://<host>:<port>/mcp`.

**3. First sign-in proposes a binding.** When a person completes the Google/Apple
approval flow, the server writes an **unconfirmed** binding to
`$WILLOW_HOME/mcp_apps/_identity_bindings/<issuer>__<subject>.json`:

```json
{ "issuer": "google", "subject_id": "…", "email": "you@example.com",
  "email_basis": "asserted", "app_id": null, "confirmed": false }
```

`email_basis` records how much downstream code should trust the email, because
IdPs differ: `asserted` (Google — present and IdP-asserted every sign-in),
`first_auth_only` (Apple — may appear only on the first authorization),
`relay` (Apple private-relay address that can stop forwarding), or
`unavailable`. If a bound identity's email later changes between sign-ins, the
binding is annotated with `email_drift` rather than silently updated.

**4. Confirm the binding (operator-only, local).** Confirmation is deliberately
*not* an MCP tool — a remote caller must never confirm its own binding. Run it
on the host that owns `$WILLOW_HOME`:

```bash
willow-mcp confirm-binding --issuer google --subject "<subject-id>" --app-id "<app_id>"
```

Only after this does the caller's session resolve to the manifest permissions
for `<app_id>` (see [Authorization](#authorization)).

### Turning serve mode on and off

Serve mode is a background process, not part of the stdio server — so it's
turned on and off on demand rather than by editing config each time.
`scripts/willow-serve` manages a systemd `--user` service for the `--serve`
process **and** toggles the matching http entry in `.mcp.json`, so an MCP
client connects to it only while it's on:

```bash
scripts/willow-serve install   # one-time: write + load the systemd user unit
scripts/willow-serve on         # start serve + add the .mcp.json entry
scripts/willow-serve off        # stop serve  + remove the .mcp.json entry
scripts/willow-serve status     # unit state + whether the entry is present
scripts/willow-serve logs        # follow the serve logs (journalctl)
```

After `on`/`off`, reconnect your MCP client (in Claude Code: `/mcp`) so it
picks up the changed `.mcp.json`. Port/host default to `8766`/`127.0.0.1`; set
`WILLOW_MCP_PORT` / `WILLOW_MCP_HOST` before `install` to change them. Claude
Code users get this as the [`willow-serve` skill](skills/willow-serve.md) —
just ask to turn serve mode on or off.

> If you already signed in once, `on` reuses your cached credential — no OAuth
> screen reappears unless it was cleared. That's expected, not a failure.

> **Serve mode does not inherit your shell environment.** The `systemd --user`
> unit is started by systemd, not by your interactive shell, so a `WILLOW_PG_DB`
> (or `WILLOW_STORE_ROOT`, `WILLOW_HOME`, …) you `export` in `.bashrc`/`.zshrc`
> **will not reach the serve process** — it falls back to the defaults in the
> [Configuration](#configuration) table. This bites env-based, non-default
> setups: the stdio server (launched from your shell) reads `willow_20`, say,
> while serve silently reads the default `willow`. Make the config reachable by
> the unit before `on`:
>
> ```bash
> # one-time: import current shell values into the systemd --user manager
> systemctl --user import-environment WILLOW_PG_DB WILLOW_STORE_ROOT WILLOW_HOME
> # …or, durably, drop them in a file systemd --user reads at login:
> #   ~/.config/environment.d/willow-mcp.conf  →  WILLOW_PG_DB=willow_20
> ```
>
> Then `scripts/willow-serve install` (regenerate) and `on`. Verify with a read
> tool over the serve endpoint: a `table_not_found` / `relation … does not
> exist` on data that stdio can see is the signature of this env gap.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `WILLOW_PG_DB` | `willow` | Postgres database name (serve mode won't see a shell `export` — see [serve env note](#turning-serve-mode-on-and-off)) |
| `WILLOW_PG_USER` | `$USER` | Postgres user (Unix socket auth) |
| `WILLOW_STORE_ROOT` | `~/.willow/store` | SQLite store directory — set to willow-2.0's store root to share data |
| `WILLOW_APP_ID` | `willow-mcp` | Default app_id if not passed per-call |
| `WILLOW_HOME` | `~/.willow` | Root for manifests, vault, and identity bindings |
| `WILLOW_MCP_HOST` | `127.0.0.1` | Serve-mode bind host (`--host` overrides) |
| `WILLOW_MCP_PORT` | `8765` | Serve-mode bind port (`--port` overrides) |
| `WILLOW_MCP_URL` | *(derived)* | Public base URL for OAuth issuer/callbacks in serve mode |
| `SAP_SAFE_ROOT` | `~/.sap/Applications` | SAFE folder root |
| `SAP_PGP_FINGERPRINT` | *(empty)* | Pinned GPG fingerprint |

## Authorization

Manifest-based ACL, no external service or ACL database. Each `app_id`
needs a manifest at `$WILLOW_HOME/mcp_apps/<app_id>/manifest.json`:

```json
{"permissions": ["store_read", "knowledge_write"]}
```

`permissions` is a list of group names and/or literal tool names —
see `PERMISSION_GROUPS` in `src/willow_mcp/gate.py` for the full set
(`store_read`, `store_write`, `knowledge_read`, `knowledge_write`,
`schema_admin`, `task_queue`, `agent_dispatch`, `fleet_read`, `context`,
`audit`, `full_access`). Fail-closed: no manifest, or an empty `permissions`
list, denies every call for that `app_id`.

There is also one **capability permission**, `task_net`, which is not a tool
name but a privilege flag: it lets an app *ask* for `task_submit(allow_net=True)`.
It is deliberately excluded from `task_queue` and `full_access` — network egress
from the sandbox must be granted explicitly, on its own line, and only host-side
(never authored from inside the sandbox). On its own it authorizes nothing: the
call also needs the operator's `consent.internet` and a live egress lease
(see [Egress needs three keys](#egress-needs-three-keys)).

### `store_scope` — confining an app to its own collections

By default, `store_*` tools are **unrestricted across collections** — the
SOIL store is deliberately shared with the wider Willow fleet (see
`WILLOW_STORE_ROOT` in [Configuration](#configuration) above), so an app with
`store_read`/`store_write`/`full_access` can see every collection any other
app or fleet process has written, the same way it always could. That's the
right default for a single-operator, single-trust-domain install, but it
means a `store_read` grant to one app is implicitly a grant to read every
other app's data too.

An operator who wants an app confined to its own data adds an optional
`store_scope` array to that app's manifest:

```json
{"permissions": ["full_access"], "store_scope": ["myapp_*"]}
```

Patterns match by exact name, or by prefix if they end in `*`. With
`store_scope` set, `store_put`/`get`/`list`/`update`/`search`/`delete` reject
any collection outside it (`collection_denied`), and `store_search_all`
only searches the matching collections instead of every collection in the
store. Omit the field entirely for today's unrestricted behavior — an empty
list (`"store_scope": []`) means "no collections," not "unrestricted."

**A scope the gate cannot read denies everything.** If `store_scope` is present
but malformed — most likely `"store_scope": "myapp_*"`, a string where a list
belongs — the app is confined to *no* collections rather than granted all of
them. The same holds for an unreadable manifest or an invalid `app_id`. This is
deliberate: an operator who mistypes the field believes the app is confined, and
a policy that cannot be parsed is not consent. The app fails loudly, an `ERROR`
is logged naming the field and the type it got, and nothing leaks while the typo
is being found. Omit the field (or set it to `null`) to declare no policy.

In [HTTP serve mode](#http-serve-mode-oauth), the `app_id` is not taken from
the call — it is resolved from the caller's confirmed OAuth identity binding,
then checked against that same manifest ACL.

## Hooks and skills (Claude Code)

`.claude-plugin/plugin.json` registers a `PreToolUse` hook and a skill for
Claude Code users — install this package as a plugin to get both alongside
the MCP server itself:

- **`hooks/pre_tool_use.py`** blocks `Bash` commands that reach for raw
  `psql`/`psycopg2`/`sqlite3` against a database or store willow-mcp owns,
  redirecting to the matching MCP tool instead. It also blocks any call that
  would write the keys authorizing the agent's *own* egress — minting a lease,
  running `grant-net`, or editing a manifest to add `task_net` — and warns on a
  `task_submit` that hand-embeds a `# allow_net` directive.
- **[`skills/schema-confirm.md`](skills/schema-confirm.md)** walks through
  reviewing and confirming a table's schema mapping before writing to it.
- **[`skills/willow-serve.md`](skills/willow-serve.md)** turns OAuth serve mode
  on/off on request (see [above](#turning-serve-mode-on-and-off)).
- **[`skills/kart-tasks.md`](skills/kart-tasks.md)** covers submitting and polling
  Kart tasks, the three-key egress model, and worker liveness.

See [docs/design/hooks-and-skills.md](docs/design/hooks-and-skills.md) for
the design and the reasoning behind shipping these alongside tools rather
than as a later add-on.

## License

MIT — Sean Campbell 2026
