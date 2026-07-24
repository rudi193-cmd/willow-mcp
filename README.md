# willow-mcp

[![PyPI](https://img.shields.io/pypi/v/willow-mcp)](https://pypi.org/project/willow-mcp/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-1.0-blue)](https://modelcontextprotocol.io)

Agent-neutral MCP server with persistent memory and task execution. Works with any MCP client: Claude Code, Claude Desktop, Cursor, or any custom agent that speaks stdio MCP.

> **Corpus memory:** the whole Willow constellation — the code, human, and collaboration corpora assembled and queryable — lives in the sovereign [`willow-compose`](https://github.com/rudi193-cmd/willow-compose) repo. The hub *calls* it; it doesn't live here (keeping the hub lean).

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
willow-mcp-compile --force   # compile manifests (use product venv — see below)
willow-mcp-sign-seed hanuman # ratify home seed + detach-sign (operator terminal only)
willow-mcp-compile-persona hanuman # seed → personas/hanuman.md (AS-7)
```

### Local sandbox (one command)

To take a fresh clone to a working stdio server — venv, editable install,
scaffolded `$WILLOW_HOME`, compiled manifests, and (best-effort) a local
Postgres with every table created — run:

```bash
bash scripts/sandbox-bootstrap.sh   # idempotent; ends with a live diagnostic_summary
```

On a bootstrapped sandbox the schema mappings for the tables the script itself
just created are **auto-confirmed** (so `task_*` and knowledge writes work
immediately), behind three guards: existing mapping artifacts are never
touched, every field must resolve exact, and the live columns must equal the
repo's own DDL — an adopted/foreign database always falls through to the
human `schema_confirm_mapping` path (see `src/willow_mcp/sandbox_confirm.py`).

It scaffolds a repo-local, gitignored `.willow/` so the sandbox never touches
your real fleet state. Postgres is optional and handled best-effort (the SOIL
store stands alone); pass `WILLOW_SKIP_PG=1` for a SOIL-only stand-up, or
`WILLOW_PG_BOOTSTRAP_ROLE=1` on a bare cluster where your OS user has no
Postgres role yet.

A fresh Postgres database needs willow-mcp's tables. On a shared fleet DB they
already exist; on a standalone install, apply the DDL in
[`docs/schema/`](docs/schema/) (`knowledge`, `agents`, `routing_decisions`,
`tasks` — the four `diagnostic_summary` checks for). The bootstrap script
applies all four for you. Each `knowledge`/`tasks` write path stays locked
behind `schema_confirm_mapping` until you confirm the mapping once.

> **PATH note:** `~/.local/bin/willow-mcp` is often the **fleet** shim (`sap_mcp.py`), not this
> product. Use the product venv binary:
> `~/github/.willow/venvs/willow-mcp/bin/willow-mcp-compile --force`
> or `.../bin/willow-mcp compile-agents --force` after `pip install -e .` in that venv.

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
| `store_collections` | List the SOIL collections you can see (narrowed to your `store_scope`) — learn the collection names without running a search |
| `store_purge_collection` | Bulk soft-delete every record in a collection (e.g. leftover test/scratch data). Reversible (archive-don't-delete — the store.db is kept); requires `confirm=<collection name>` and stays within your `store_scope` |
| `store_stats` | Per-collection live-record counts (within your `store_scope`), largest first, plus store-wide totals — the numeric companion to `store_collections` for spotting a bloated or polluted collection |
| `knowledge_ingest` | Add a knowledge atom (requires a confirmed schema mapping — see `schema_confirm_mapping`) |
| `knowledge_search` | Multi-keyword search in the Postgres knowledge base |
| `kb_at` | Fetch a single knowledge atom by ID |
| `kb_promote` | Change an atom's domain (requires a confirmed schema mapping) |
| `kb_journal` | Add a journal-domain knowledge atom (requires a confirmed schema mapping) |
| `kb_startup_continuity` | Fetch atoms tagged/domained for startup continuity |
| `schema_confirm_mapping` | Confirm (optionally correct) a table's column mapping, unlocking its write tools. `preview=True` dry-runs it and renders a **sample row** so you can see what each field actually resolves to before trusting a name match — see [docs/design/schema-adaptation.md](docs/design/schema-adaptation.md) |
| `gap_log` | Log or bump a "we don't know this yet" entry (fleet-wide backlog, SOIL-only, no Postgres needed) — see [docs/design/gap-backlog.md](docs/design/gap-backlog.md) |
| `gap_list` | List gaps, most-asked first — filter by `topic` and/or `status` (`open`/`resolved`/`promoted`) |
| `gap_resolve` | Mark a gap as being worked or answered — bookkeeping only, does not write to the knowledge base |
| `gap_delete` | Soft-delete a single gap by id — clear junk/test entries without disturbing real gaps. Reversible (archive-don't-delete) |
| `gap_purge_topic` | Soft-delete every gap under an exact topic in one call — bulk cleanup without the per-call rate limit. Promoted gaps (they point at a landed atom) are left intact; requires `confirm=<topic>` |
| `gap_promote` | Turn a resolved gap into a knowledge atom. Requires `answer`, at least one `source`, and `confirmed_by`; writes through the same schema-confirmation gate as `knowledge_ingest` and closes the gap out |
| `nest_scan` | Walk a drop folder, extract + classify its files by meaning, and write a canonical SQLite Nest DB. Returns counts only; `dry_run=True` (default) reports without writing — see [docs/NEST.md](docs/NEST.md) |
| `nest_status` | Counts for a seeded Nest DB — sources by status, fragments by type, topical categories by size. Structure only; filename-labels are walled and counted as `uncategorised` |
| `nest_digest` | A one-page Markdown map of a Nest DB — the **walled** view (person names, the date timeline, and filenames suppressed). The full digest is a local-CLI affordance only, never returned over MCP |
| `nest_promote` | Promote a Nest's **structure** — counts, curated category names, redacted secret kinds, never content — into the knowledge base via the same core write as `knowledge_ingest`. `dry_run=True` returns the atoms that would be promoted |
| `nest_intake_scan` | Live drop-folder router: classify new files in a drop zone by filename into a track and **stage** a review queue. Non-destructive — nothing moves until `nest_intake_file` |
| `nest_intake_queue` | List the pending review queue with the track the classifier predicted for each file |
| `nest_intake_file` | File a staged item: **move** the file to its predicted track's destination, or `override_dest` to correct it. An override feeds the correction counter |
| `nest_intake_skip` | Skip a staged item — leave the file, record the decision |
| `nest_intake_flags` | List open rule-delta flags — patterns overridden often enough that the classifier proposes a rules change (a human ratifies) |
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
| `fleet_status` | Return the canonical charter `fleet.json` roster plus Postgres drift diagnostics |
| `fleet_health` | Task queue counts by status, live worker heartbeats, and whether the queue is `stranded` |
| `frank_read` / `frank_verify` | Read and verify the existing Postgres FRANK hash chain |
| `frank_append` | Append an established-shape FRANK event (separately gated) |
| `envelope_apply` | Match an active constitutional grant and write its FRANK citation before returning authority |
| `context_save` | Save ephemeral per-identity working state under a key, with an optional TTL (SOIL-backed, no Postgres) |
| `context_get` | Read a saved context; `expired` (and purged) once its TTL passes |
| `context_list` | List your saved context keys and expiry times (expired ones skipped) |
| `context_expire` | Delete a saved context before its TTL |
| `integration_list` | The integration ledger: every outbound adapter, live or **declared stub**, with credential *source* (never the value) |
| `integration_status` | Offline readiness readout for one adapter — live/stub, credential presence, and whether the egress gate would pass. No network call |
| `integration_call` | Call an external API through a registered adapter — behind the three-key egress gate, keyed on `integration_net` (own line, never implied by `task_net` or `full_access`) |
| `receipts_tail` | Read your own most-recent tool-call receipts — a self-audit trail scoped to your `app_id` |
| `whoami` | Report your own identity and effective permissions — app_id, role, permission groups, the resolved set of tools you can call (minus `deny_tools`), and your `store_scope`. Ungated, like `diagnostic_summary` |
| `diagnostic_summary` | Self-check: store/Postgres/schema/manifest/bindings/worker/consent/egress-lease/env health, with a verdict and named fixes. Ungated — see below |

### Egress needs three keys

**First run:** `willow-mcp-init` then `willow-mcp onboard --project-root <repo> --enable-internet`.
See [docs/OPERATOR-ONBOARD.md](docs/OPERATOR-ONBOARD.md). Use `wmc` or the product venv
binary — not bare `willow-mcp` on PATH when the legacy `sap_mcp.py` server is installed.

A task that reaches the network requires **all three standing keys** plus a
one-use signed task envelope. Any missing element denies before shell launch:

| Key | Question | Where | Turned by |
|---|---|---|---|
| `task_net` | May this app *ever* request egress? | `mcp_apps/<app_id>/manifest.json` | operator, granted once |
| `consent.internet` | Is egress permitted *right now*? | `$WILLOW_HOME/settings.global.json` | operator, flipped freely |
| egress lease | For *this app*, until *when*? | `mcp_apps/_net_leases/<app_id>.json` | operator, `willow-mcp grant-net`, expires on its own |
| signed task envelope | This submitter, exact task, scope, expiry, and nonce? | `tasks.network_authorization` | operator, `willow-mcp sign-net-task`, one use |

```jsonc
// $WILLOW_HOME/settings.global.json — the off switch
{ "consent": { "internet": false, "cloud_llm": true, "lan": false } }
```

```console
$ willow-mcp onboard --project-root ~/github/willow --enable-internet
$ willow-mcp run-net myapp --task-file task.sh --ttl 30m   # grant + sign + queue
$ willow-mcp worker --lane fast --once                   # drain the queue
$ willow-mcp doctor --app-id myapp                         # copy/paste fixes
$ willow-mcp grant-net myapp --ttl 30m --reason "publish the release"
$ willow-mcp sign-net-task myapp --task-file task.sh       # keys: setup-egress / ~/.config/willow-mcp/egress/
$ willow-mcp net-status
$ willow-mcp revoke-net myapp
```

Setting `consent.internet` to `false` stops network tasks submitted through
`task_submit`, immediately, without editing a single manifest. `task_net` is a
capability (rarely granted, deliberately excluded from `full_access`);
`consent.internet` is a switch; the lease is a **time-boxed grant** that an agent
may ask for and never issue. No MCP tool can mint one — `grant-net` is local CLI
only, exactly like `confirm-binding`. An agent may *request* egress and may never
*grant it to itself*. `sign-net-task` requires an interactive host terminal and
an Ed25519 private key outside `WILLOW_HOME`/`WILLOW_STORE_ROOT`; no MCP tool or
worker receives that key.

At execution, Kartikeya treats `# allow_net` only as a request and calls the
willow-mcp host authorizer. The authorizer rechecks capability, consent, lease,
strict trust-root state, signature, exact normalized task hash, expiry, and the
one-use nonce. Direct task-table inserts and legacy rows have no envelope, so
they remain runnable only as network-isolated work (B-37).

Deployment is deliberately explicit: apply
`docs/schema/tasks-add-network-authorization.sql`, reconfirm the `tasks` mapping,
set `WILLOW_MCP_EGRESS_PUBLIC_KEY` to an operator-owned Ed25519 public PEM that
the worker cannot write, set a worker-writable `WILLOW_MCP_EGRESS_REPLAY_ROOT`,
and enable `WILLOW_MCP_STRICT_TRUST_ROOT=1`. The matching private key must remain
outside `WILLOW_HOME` and `WILLOW_STORE_ROOT`; only the interactive
`sign-net-task` command reads it. Until those conditions hold, network tasks deny
closed while ordinary isolated tasks remain unchanged.

Consent and leases are both read **fail-closed**: a missing file, an unparseable
file, a non-boolean value (`"true"`, `1`), a lease past its deadline, a deadline
with no timezone, or a lease record naming a *different* app than the file it sits
in — all read as denied. Absence is not consent, and a name is not an identity.
Runtime tools only read consent. An operator can mutate it through the local,
interactive-only `willow-mcp consent set <key> <true|false>` command; the command
atomically writes canonical policy and mirror and appends a metadata-only audit
record. `willow-mcp consent reconcile` keeps the canonical value and repairs its
mirror. If the two disagree, `diagnostic_summary` reports both rather than
guessing intent (B-30).

### Governance continuity

`willow-mcp roster status` compares the constitution repo's canonical
`fleet.json` with Postgres. `willow-mcp roster sync` is interactive-only and
idempotently inserts or updates charter rows; unknown database rows are reported
as contested and preserved, never silently deleted.

Constitutional envelopes are loaded read-only from
`envelopes/pre-approved.json` and checked against `syscall-table.json`.
`envelope_apply` validates issuer, grantee, verb, exact bounds shape, revocation,
expiry, and FRANK-derived quota. Both grants and faults append an
`envelope_citation` to the existing `frank_ledger` before authority is returned.

#### `gates` — every gate, on/off, egress-lease shaped

Diagnosing a denial today means knowing which of a dozen-plus gates to check
and which file or CLI command controls it. `willow-mcp gates` shows all of
them at once, each rendered the way the egress lease already renders
itself — on/off, plus how long the "on" is good for. Run it in a real
terminal and it's interactive — arrow keys / j-k to move, enter/space to
actually flip the highlighted gate, no second command to copy anywhere:

```console
$ willow-mcp gates                    # interactive TUI (every app under mcp_apps/)
$ willow-mcp gates myapp              # interactive TUI, scoped to one app
$ willow-mcp gates --serve            # live local HTML dashboard, working buttons
$ willow-mcp gates --serve --port 9000 --host 127.0.0.1
$ willow-mcp gates --static           # one-shot text printout instead of the TUI
$ willow-mcp gates --html             # writes ./willow-gates.html, a read-only snapshot
$ willow-mcp gates --json             # raw rows, for scripting
```

`--static`/`--json`/`--html` are unchanged from before and still the right
choice for scripting, CI, or a file you want to keep — `--static` is also
what runs automatically whenever stdout isn't a real terminal (piped,
redirected), so nothing here breaks existing scripts.

The interactive TUI and `--serve`'s live dashboard share one action layer
(`gates_actions.py`) with the CLI subcommands below — pressing a row (or
clicking its button) calls the exact same functions `allow-permission`/
`grant-net`/`confirm-binding` do, nothing new. `--serve` binds
`127.0.0.1`-only by default; it's a mutation-capable local admin surface
with no authentication of its own, so widening `--host` prints a warning
rather than doing it quietly. The one exception is the `worker` row's
action: it drains the queue **once** (like `worker --once`), never launches
the persistent daemon — that would block the TUI/dashboard forever.

Manifest permission groups — which had no CLI before, only hand-editing
`manifest.json` or regenerating it via `compile-agents` — get their own
pair, usable standalone or as what the TUI/dashboard call underneath:

```console
$ willow-mcp allow-permission myapp store_read
$ willow-mcp deny-permission myapp store_read
```

Both are local-CLI-only, never MCP tools, for the same reason `grant-net`
isn't: an agent must never be able to grant itself a permission it was just
denied — and that boundary holds for the TUI and `--serve` too, since
neither is reachable except by an operator running them on the host that
owns `$WILLOW_HOME`. `consent.*` rows never show a command or a working
button — willow-mcp only reads that policy (see above) — and
`strict_trust_root` / severance / human-orchestrator attestation are
environment variables read once at process start, so their rows name the
env var to set and restart with, rather than pretending a live toggle
exists.

`task_net` and `integration_net` both show up as their own capability rows
(neither is folded into `full_access`), and both are authorized by the same
per-app egress lease below them — one `grant-net`/`revoke-net` covers Kart
sandbox egress and server-process integration calls together, since a lease
is scoped to the app, not to which capability is asking.

Every row also carries a `state_label` in context instead of a bare ON/OFF —
GRANTED, ALLOWED, ACTIVE, CONFIRMED, RUNNING, ENABLED (and their opposites) —
and a `category` (egress & network / system / identity / permissions) that
the TUI and both HTML pages group by. The HTML pages open on the egress
tab — the smallest group, and the one with a clock — with a summary strip
above the tabs for at-a-glance state, and render the ~20-row permissions
group (routine, rarely touched) as a compact list rather than large cards,
instead of one flat scroll of everything at once.

#### `tree` — the integration seam for a real dashboard

`docs/design/*.html` sketches a client UI as a tree — trunk (overall
health), sap (task queue), canopy (agent fleet), roots (SOIL store), rings
(schema-mapping confirmation), leaves (knowledge atoms), litter (activity
log), and stomata (the gates above). `willow-mcp tree` is what makes that
real: one call that returns every part in that same shape, instead of a
dashboard assembling `fleet_status`/`fleet_health`/`kb_startup_continuity`/
`receipts_tail`/`gates` itself.

```console
$ willow-mcp tree myapp              # short text summary
$ willow-mcp tree myapp --json       # full data, for a real dashboard to consume
```

It's a thin CLI wrapper over `willow_mcp.tree_view.build_tree(app_id)`,
which a Python dashboard can also import and call directly. `sap`, `canopy`,
and `leaves` go through the same `@_guarded` MCP tool functions a client
would reach over the protocol — gating, rate limiting, and receipt logging
all still apply — and degrade to `{"error": "postgres_unavailable"}` with no
database configured, same as those tools already do. `roots`, `rings`,
`litter`, and `stomata` read local SQLite/filesystem state directly, so they
work with no Postgres at all.

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

### Integrations (outbound adapters)

`integration_call` lets the **server process** call external HTTP APIs through
registered adapters — a second egress lane, beside the Kart sandbox's. It uses
the same three-key gate, but keyed on its **own** capability, `integration_net`:
the server egresses as its own uid with its own filesystem view, a strictly more
privileged lane than the network-namespaced sandbox, so `task_net` never implies
it (and vice versa). `integration_call` itself is also excluded from
`full_access` — even the attempt surface is opt-in.

Adapters are **earned, not scaffolded**. Four are live (`github`,
`huggingface`, `jeles`, `utety`); six are *declared stubs* (`gmail`, `slack`,
`notion`, `google-drive`, `datadog`, `jira`) that refuse fail-closed, each
naming what it needs and what earns its implementation. `integration_list` is
the ledger (it reports each adapter's live/stub status) — see
[`docs/design/integrations.md`](docs/design/integrations.md) for the earn rule.

Credentials resolve environment-variable-first (e.g. `WILLOW_GITHUB_TOKEN`,
then `GITHUB_TOKEN`), then the vault under `integration/<name>/token`. No tool
ever returns a credential — only its *source*.

```console
$ willow-mcp-integrations list                # the ledger, live + stubs
$ willow-mcp-integrations check github --app-id myapp   # offline: creds? keys? no network call
$ willow-mcp-integrations set-token github   # prompted + hidden, stored in the vault
```

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
`knowledge_ingest`/`kb_ingest`/`kb_journal`/`kb_promote` refuse to write
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

**Version line.** willow-mcp is the **current substrate** the fleet consumes. It
sits at the head of a lineage of *distinct machines* — each its own spec, not
rebadges of one another:

- **`willow-1.7` → `willow-1.9`** — earlier production lines; `willow-1.9` is
  **archived** (April–May 2026 era).
- **`willow-2.0`** — a distinct, larger-surface fleet server; now **legacy /
  migration source**, not the current stack.
- **`willow-mcp`** — the **current substrate**: a re-scoped re-implementation of
  willow-2.0's SOIL / knowledge / dispatch core.

willow-mcp re-implements that core as a standalone product with a redesigned,
smaller surface — **not** a drop-in copy of
[willow-2.0](https://github.com/rudi193-cmd/willow-2.0)'s tool API. Many tools
were renamed in the redesign (`soil_*` → `store_*`, `ledger_*` → `frank_*`,
`agent_task_*` → `task_*`), so an app is not portable between the two unchanged.
See [`docs/migrations/willow-2.0-gap-inventory.md`](docs/migrations/willow-2.0-gap-inventory.md)
for the verified tool-by-tool diff, and query `lineage_why` on the recorded atoms
(`version-willow-mcp`, `version-willow-2.0`, `version-willow-1.9`,
`version-willow-1.7`) for the provenance.

> **Not the same "2.0".** The willow-**2.0** *fleet server* above is the
> predecessor line. willow-mcp's own package version (e.g. "serve mode is
> **2.0.0+**" below) is this product's semver — unrelated.

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

### Installing standalone workers

`willow-mcp worker-service` manages separate fast and batch systemd user units.
It writes every required environment value into the units, so workers do not
inherit hidden willow-2.0 paths or depend on shell exports:

```bash
willow-mcp worker-service install
willow-mcp worker-service status
willow-mcp worker-service uninstall
```

Install and uninstall never start or stop services. Uninstall refuses while a
worker is active; live state changes remain an explicit operator action. Before
starting either unit, apply `docs/schema/tasks-worker-production.sql` and
reconfirm the `tasks` mapping. The queue then isolates `fast`/`batch` claims,
records claim owner/time, recovers stale claims, applies bounded retries, and
timestamps terminal rows.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `WILLOW_PG_DB` | `willow` | Postgres database name (serve mode won't see a shell `export` — see [serve env note](#turning-serve-mode-on-and-off)) |
| `WILLOW_PG_USER` | `$USER` | Postgres user (Unix socket auth) |
| `WILLOW_STORE_ROOT` | `~/.willow/store` | SQLite store directory — set to willow-2.0's store root to share data |
| `WILLOW_MCP_FLEET_HOME` | *(unset)* | The fleet home this install claims to be **severed** from. Unset = no claim. See [Severance](#severance) |
| `WILLOW_MCP_FLEET_PG_DB` | *(unset)* | The fleet database this install claims to be severed from |
| `WILLOW_MCP_DISPATCH_MIRROR` | *(unset)* | Truthy on a **fleet host** to best-effort mirror dispatch packets into shared Postgres `dispatch_tasks` (so the fleet sees dispatches, like it already sees store/knowledge/tasks/agents). Off = filesystem-only; the filesystem packet is always canonical. See `docs/schema/dispatch_tasks.postgres.sql` |
| `WILLOW_APP_ID` | `willow-mcp` | Default app_id if not passed per-call |
| `WILLOW_HOME` | `~/.willow` | Root for manifests, vault, and identity bindings |
| `WILLOW_WORKER_LANE` | set by worker unit | Worker lane (`fast` or `batch`) |
| `WILLOW_WORKER_HEARTBEAT_ROOT` | `$WILLOW_HOME/worker_heartbeat` | Explicit worker heartbeat directory |
| `WILLOW_WORKER_STALE_SECONDS` | `1800` | Age after which an uncompleted claim is recovered |
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
see `PERMISSION_GROUPS` in `src/willow_mcp/gate.py` for the authoritative set
(42 groups). Common ones: `store_read`, `store_write`, `knowledge_read`,
`knowledge_write`, `schema_admin`, `task_queue`, `agent_dispatch`,
`dispatch_read`, `dispatch_write`, `fleet_read`, `context`, `audit`,
`gap_read`, `gap_write`, `gap_promote`, `fork_read`, `fork_write`, `nest_read`,
`nest_write`, `integration_read`, `web_read`, `code_graph_read`,
`code_graph_write`, `full_access` — plus per-subsystem read/write groups for
lineage, friction, commitments, the human-loop, and MarkdownAI. Fail-closed:
no manifest, or an empty `permissions` list, denies every call for that
`app_id`. `gap_promote` is kept separate from `gap_write` — landing
something as trusted knowledge is a more consequential act than logging or
resolving a gap, the same reasoning `schema_admin` gets its own group
instead of folding into `knowledge_write`.

The MarkdownAI (mai) tools (registered only when `WILLOW_MCP_MARKDOWNAI=1`)
are additionally per-app gated (#153/#161): `markdownai_read` and
`markdownai_write` cover the file/render tools, and `markdownai_directives` —
deliberately outside `full_access` — unlocks the side-effectful
`@db`/`@http`/`@env` directives inside `render()`. Even with that grant:
`@db` connections must be allowlisted in the manifest's `"mai_connections"`
list and never default to the willow database; `@http` honors the operator's
`consent.internet` plus an SSRF host blocklist; and `@env` resolves only keys
named in the operator's `WILLOW_MAI_ENV_ALLOW` (comma-separated, default
deny), with credential-shaped keys never resolving at all.

There is also one **capability permission**, `task_net`, which is not a tool
name but a privilege flag: it lets an app *ask* for `task_submit(allow_net=True)`.
It is deliberately excluded from `task_queue` and `full_access` — network egress
from the sandbox must be granted explicitly, on its own line, and only host-side
(never authored from inside the sandbox). On its own it authorizes nothing: the
call also needs the operator's `consent.internet` and a live egress lease
(see [Egress needs three keys](#egress-needs-three-keys)).

### `store_scope` — confining an app to its own collections

By default, `store_*` tools are **unrestricted across collections** — and by
default the SOIL store is the wider Willow fleet's store (see
`WILLOW_STORE_ROOT` in [Configuration](#configuration) above), so an app with
`store_read`/`store_write`/`full_access` can see every collection any other
app or fleet process has written, the same way it always could. That's the
right default for a single-operator, single-trust-domain install, but it
means a `store_read` grant to one app is implicitly a grant to read every
other app's data too.

Sharing is a default, not a design commitment. An install that should be cut
off from the fleet can point `WILLOW_STORE_ROOT` at its own store and name the
fleet it is severed from — see [Severance](#severance) below, which turns the
cut into something `diagnostic_summary` checks rather than something the docs
assert.

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

### `egress_secret_exempt` — letting a tool return a raw credential

Tool responses are scanned at a single funnel and any credential-shaped value
(a provider `sk-` key, an `AKIA…` id, a PEM private-key block, a GitHub/Slack/
Google/Stripe token, a JWT) is redacted to `[REDACTED:<kind>]` before it
leaves — the data-path half of "no tool ever returns a credential." A few tools
legitimately must return a raw token, the canonical case being an
`integration_call` that performs an OAuth token exchange. Name those tools in
the app's manifest:

```json
{"permissions": ["full_access"], "egress_secret_exempt": ["integration_call"]}
```

The scan still runs, so the audit trail stays complete: an exempted return is
kept raw but receipted as `credential_returned` (naming the kinds, never the
value), so the exception is loud rather than silent. Like `store_scope`, the
field **fails closed toward redaction** — a bad `app_id`, a missing/unreadable
manifest, or a malformed field (a string where a list belongs) exempts *nothing*
and an `ERROR` is logged. Because manifests are operator-side (the PreToolUse
hook blocks an app from writing its own), an app can never exempt itself. The
exemption is per named tool, never a blanket unlock.

## Severance

A willow-mcp install can share a Willow fleet's store, database, and trust root,
or it can be cut off from them. Both are legitimate. What is not legitimate is
*claiming* the cut and not having it — a server that reports `ok` while wired to
the fleet is worse than one with no check at all.

Severance is **asserted, never assumed.** Name the fleet you are severed from:

```bash
export WILLOW_MCP_FLEET_HOME=/home/you/github/.willow
export WILLOW_MCP_FLEET_PG_DB=willow_20
```

`diagnostic_summary` then reports a `severance` check over four surfaces:

| Surface | Kind | Violation |
|---|---|---|
| `store` | data | `WILLOW_STORE_ROOT` resolves inside the fleet home → `degraded` |
| `postgres` | data | `WILLOW_PG_DB` is the fleet database → `degraded` |
| `trust_root` | **authority** | `mcp_apps/` is inside the fleet home, or is writable by this process → `broken` |
| `egress` | **authority** | this process can forge the three-key network gate (strict trust root off, or the consent switch / lease root / egress verification key is self-writable) → `unknown` degrades, a forgeable key `breaks` |

The distinction is the whole design. Store and database hold **data**: someone
who writes them corrupts records. The `trust_root` and `egress` surfaces hold
**authority** — the manifest that grants `task_net`, the lease root, the consent
file, the egress verification key. Someone who writes *those* grants themselves
the egress the cut was supposed to deny. Only an authority surface can turn a
severed install into a compromised one, so only those two break the verdict; the
data surfaces merely degrade it.

Consequently the trust root must live somewhere neither this process nor the Kart
sandbox can write. A repo directory is the wrong place for it, however convenient:
repos are bound read-write into task sandboxes. Put data in the repo; put the gate
outside it, owned by a uid the agent does not run as.

Symlinks are resolved before comparison. `~/.willow` is frequently a symlink into
a fleet tree, and two names for one directory are not two directories.

Leave both variables unset and the check reports `not_asserted` and changes
nothing — a single-trust-domain install is complete without severance, and one
that never claimed to be cut off cannot be caught lying about it. Set one and not
the other and the unnamed surface reports `unknown`, which degrades: an
unverifiable claim is not a passing one.

## The companion layer

Not everything in the package is a gate. A few subsystems exist to carry the
*story* of an install — lessons, work-units, the shape of the collaboration —
and a `tools/` directory turns jobs a model was doing by hand into
deterministic scripts.

### The Grove — rings for lessons

`the_grove.py` is a rings store for lessons learned, sibling to
`schema_profile`'s vocabulary rings but unbounded on purpose: vocabulary may be
pruned cheaply; lessons are kept precisely so the deployment cannot become
something that forgets them.

```console
$ python -m willow_mcp.the_grove            # the resting display
The Grove is stable.
Current depth: 0 rings.
Soil health: Worth tending.

Next gardener: unknown.
Chapters remaining: as many as the rain requires.
$ python -m willow_mcp.the_grove --status   # pipe-friendly: stability, depth, soil health
```

`core.record_lessons()` distills any SQLite journal (the table holding the
writing is introspected, never assumed; the source is opened read-only) into
exactly one ring carrying the lesson worth keeping. A diseased rings file reads
as empty but reports the grove `unsettled` rather than silently claiming
depth 0.

### Forks — bounded work-unit tracking

The seven `fork_*` tools (`fork_create` / `fork_status` / `fork_log` /
`fork_list` / `fork_join` / `fork_merge` / `fork_delete`, under the
`fork_read`/`fork_write` permission groups) track branch + PR work-units as
durable SOIL records with an append-only change log — the same shape as gaps,
lineage, and the human-loop queue, deliberately *not* a fleet-Postgres table
(B-28's lesson: don't drag a schema migration into the shared database for a
bookkeeping record). `fork_merge`/`fork_delete` count atom/KB change-log refs
as promoted/archived bookkeeping.

### Friction floor — the mirror detector

`friction_scan` watches one thing: whether the agent has stopped being *other*
and is mirroring the user back, smoothed, **while the user is escalating**.
When a window of agent turns sits below the friction floor during escalation,
it raises a loud, human-facing flag — persisted and deduped;
`friction_flags_list` reads them back. It never blocks and never egresses: a
signal, not a verdict. It must be driven from outside the watched model — a
mirror cannot audit itself.

### `tools/` — take the job off the model

Deterministic harnesses for jobs a model was doing by hand — each turns
conversational labor into a script, so the next session runs the tool instead
of re-deriving the work. See [`tools/README.md`](tools/README.md) for the full
wiring; the cast:

| Script | Job it takes off the model |
|---|---|
| `wtool.py` | the substrate — call any of the server's tools from a shell (`--list`, JSON args), so *any* script can do what a model does through an MCP client |
| `mai_lint.py` | deterministic @markdownai format validation (also a CI step) |
| `mai_metrics.py` | record one metric per bite into SOIL; report the new-gaps-by-learnings convergence curve |
| `mai_prose_split.py` | the prose/structure pass for converting narrative docs to @markdownai — separates protected prose from directive candidates, and a `prose_ratio` verdict flags story-shaped docs "do not force" instead of mangling them |
| `provision_gate.py` | union permission groups into a gate manifest, validating every name against `gate.PERMISSION_GROUPS` — loud-fail on a typo instead of granting nothing |

## Hooks and skills (Claude Code)

`.claude-plugin/plugin.json` registers a `PreToolUse` hook and thirteen skills
for Claude Code users — install this package as a plugin to get them alongside
the MCP server itself. The hook is wired for four matchers (`Bash`,
`task_submit`, `Write|Edit|MultiEdit|NotebookEdit`, and `WebSearch|WebFetch`),
all routed through the same guard:

- **`hooks/pre_tool_use.py`** blocks `Bash` commands that reach for raw
  `psql`/`psycopg2`/`sqlite3` against a database or store willow-mcp owns,
  redirecting to the matching MCP tool instead. It also blocks any call that
  would write the keys authorizing the agent's *own* egress — minting a lease,
  running `grant-net`, or editing a manifest to add `task_net` — and warns on a
  `task_submit` that hand-embeds a `# allow_net` directive.
- The full skill set (13): `session-start`, `consent`, `worktree`,
  `handoff-write`, `external-guard`, `schema-confirm`, `willow-serve`,
  `kart-tasks`, `debugging`, `review`, `tdd`, `brainstorming`,
  `persona-overlays`. A few load-bearing ones:
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

Apache-2.0 — Sean Campbell 2026
