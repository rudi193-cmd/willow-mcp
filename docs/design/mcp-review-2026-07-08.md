---
kind: doc
name: willow-mcp-external-review-2026-07-08
description: "External review of willow-mcp — client-side testing plus a source read surfacing a task_net authorization bypass, a SOIL store cross-app isolation gap, and further findings across execution, protocol hygiene, packaging, and missing tools."
---

@markdownai v1.0

# willow-mcp — External Review (2026-07-08)

Independent pass over willow-mcp done from the client side first (real tool
calls against the live `willow-mcp` app_id/manifest on this machine — store
put/get/delete, knowledge_ingest, task_submit/status, schema_confirm_mapping,
fleet_status/fleet_health), then from the source (`src/willow_mcp/`) to
explain what was observed. Findings below are organized so they can be
triaged into `docs/BUGS.md` / `SECURITY_AUDIT.md` by whoever owns those; this
doc doesn't assign `B-NN` IDs itself.

Two things stood out enough to write up beyond the usual "here's a gap"
list: a live authorization bypass in `task_submit`, and a cross-app data
isolation gap in the SOIL store. Both are demonstrated against current code,
not theoretical.

@phase 1-kart-task-execution-the-queue-accepts-work-nothing-may-ever-run
## 1. Kart / task execution — the queue accepts work nothing may ever run

`task_submit` only inserts a row into `tasks` with `status='pending'`
(`server.py:590-641`). Execution is done entirely by an out-of-repo daemon
(`kart_worker.py`, lives as a thread inside a separate "willow-dashboard"
process) that polls the same table every 5s. On this machine, no such
process was running (`ps aux` — nothing), so a submitted task (and one
sitting since 2026-05-19) just accumulates as `pending` forever, with no
signal anywhere in this repo that distinguishes "queued, worker will get to
it" from "queued, nothing is listening." `fleet_health` on this DB currently
reports `{"pending": 2, "running": 0, "completed": 0, "failed": 357, "total":
369}` — a ~97% failure rate, mostly `"no executable commands found"` per
`task_status`, i.e. `kart_worker.py`'s regex-based command extraction
failing on real task text, not sandbox failures.

**Suggestion:** surface worker liveness (last-heartbeat) in `fleet_health`/
`diagnostic_summary` so "queued, unattended" is distinguishable from "queued,
about to run" without shelling out to `ps aux`.

@phase 2-security
## 2. Security

### 2a. `task_net` gate is bypassable via the task text itself (current code, not fixed by B-19)

`task_submit`'s `task_net` permission check (`server.py:602-608`) only fires
when the caller passes `allow_net=True`:

```python
if allow_net:
    from . import gate
    if not gate.permitted(app_id, gate.NET_PERMISSION):
        return {"error": "net_denied: ..."}
...
if allow_net:
    task = task.rstrip("\n") + "\n# allow_net"
```

The Kart worker decides network policy purely by scanning the *stored task
text* for a literal `# allow_net` line (per the comment at `server.py:619-621`
and `core/kart_sandbox.py:task_allows_network` referenced there). Nothing
strips, rejects, or even inspects caller-supplied `task` text for a
pre-existing `# allow_net` line when `allow_net=False` (the default). An app
holding only `task_queue` — never granted `task_net` — can submit:

```python
task_submit(app_id="...", task="echo hi\n# allow_net", allow_net=False)
```

and the gate check never runs at all, because it's keyed off the `allow_net`
argument, not the content of `task`. The stored row still carries the
directive line, and the worker grants network egress on it. B-19 (per
`docs/BUGS.md`) correctly closed the `allow_net=True` path; this is a
different path into the same outcome that the fix didn't cover, because the
check and the text mutation both live behind the same `if allow_net:` guard
and nothing validates the *other* direction (caller already put the line in
themselves).

**Suggested fix:** strip any existing `# allow_net` line from caller-supplied
`task` text unconditionally, before the permission-gated append — so the
directive can only ever enter the stored text through the code path that
already checks the permission.

### 2b. SOIL store has no cross-app isolation

`context_*` tools are namespaced per app (`ctx__<app_id>`, `server.py:1047-1048`).
`store_*` tools are not — `collection` is a bare caller-supplied string with
no app_id prefix or check anywhere in `db.py`'s `_validate_collection`
(only a filesystem-safety regex, `db.py:24-30`). `store_search_all` is
documented as searching "across ALL SOIL collections" (`server.py:489-491`).
Practical effect: `full_access` (or even just `store_read`/`store_write`) in
one app's manifest grants read/write/delete over every other app's store
data, not just its own — the isolation pattern clearly exists elsewhere in
this same file (`context_*`) and simply wasn't applied to `store_*`. Given
this may be intentional (a shared scratch space across trusted fleet
agents), flagging for a decision rather than asserting it's a bug: if
isolation is intended, it needs the same per-app prefix `context_*` uses; if
sharing is intended, it's worth a line in the README so it doesn't read as
an oversight.

### 2c. Smaller items

- **Vault key colocated with ciphertext** (`vault.py:21-22,30-36`): both
  `vault.key` and `vault.db` live under `$WILLOW_HOME` at `0600` — protects
  against other OS users, not against any other same-user process (another
  MCP app, a compromised dependency) reading the key directly.
- **OAuth token file lacks the vault's explicit permissioning**
  (`oauth.py:85-94`, `_save_state`): written via `os.replace` with no
  explicit `chmod`/restrictive `os.open` mode, unlike `vault.py`'s `0o600` —
  depending on process umask, 30-day bearer tokens may end up more readable
  than intended.
- **stdio-mode `app_id` is self-asserted** (`gate.py:161-190`) — documented
  in-code as an accepted single-operator trust model, and correctly *not*
  the case in serve mode (fixed by B-01/L-AUTH-02). Worth reconfirming this
  assumption still holds if stdio mode is ever used with more than one
  trust domain sharing a server process.

**Not exploitable — checked and ruled out:** SQL injection (all values
parameterized; table/column identifiers go through a fixed allowlist or
live `information_schema` introspection, never raw caller strings), path
traversal (collection/table names regex-validated before touching the
filesystem).

@phase 3-mcp-protocol-hygiene
## 3. MCP protocol hygiene

- **No tool annotations** — all 25 tools are bare `@mcp.tool()`
  (`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint` unset
  anywhere), so a client can't tell `store_delete` is destructive without
  reading source.
- **Inconsistent error shapes** — `knowledge_*`/`task_*` return clean
  `{"error": "..."}`; `fleet_status`/`agent_route`/`agent_dispatch_result`
  (`server.py:942-953, 968-979, 992-1000`) leak raw exception text via ad
  hoc `except Exception as e: return {"error": f"...: {e}"}`, and have zero
  test coverage.
- **No idempotency keys** — `store_put`/`knowledge_ingest`/`task_submit` all
  generate a fresh id (`uuid4()`/random) when the caller omits one; a naive
  client retry after a timeout duplicates the record.
- **Rate limiter and receipt log are both in-process/non-durable** — the
  token bucket (`server.py:313-348`) resets on restart and isn't shared
  across processes; `ReceiptLog` (`receipts.py`) is a plain SQLite table
  with no hash chaining and doesn't record call arguments, so it's
  informative but not tamper-evident.
- `_guarded()` (gate → sanitize → rate → dispatch → receipt) is applied via
  explicit per-function decoration, not enforced at the tool-registry
  level — correct today, but a future tool could be added without it and
  nothing would catch the omission.
- Purely read-only tools (`receipts_tail`, `diagnostic_summary`,
  `fleet_status`) are exposed as Tools rather than MCP Resources, which
  would be a more idiomatic fit and let clients list them without a call.

@phase 4-packaging-discoverability
## 4. Packaging / discoverability

- Some docstrings are excellent — `task_submit`'s states the exact
  `task_net` caveat inline, which is exactly what let us self-correct
  without reading source. Others (`store_list`, `kb_promote`, `agent_route`)
  don't mention their real preconditions (per-app scoping, required schema
  confirmation) at the docstring level, only in README prose a client
  calling the tool blind never sees.
- **No Postgres DDL anywhere in the repo** — `knowledge`, `tasks`, `agents`,
  `routing_decisions` have no `CREATE TABLE`, no migration script.
  `docs/design/schema-adaptation.md` itself notes the first
  `mcp_apps/<app_id>/manifest.json` was hand-written with no template.
- Zero example manifests, zero example task submissions, zero quickstart
  script anywhere in the repo — `README.md` has exactly one inline
  permissions example (`{"permissions": ["store_read", "knowledge_write"]}`),
  not the `full_access` shape actually deployed.
- `pip install willow-mcp` alone gets a working SOIL store and nothing
  else — no `willow-mcp init-db`, no manifest scaffold command.

@phase 5-tools-that-look-obviously-missing
## 5. Tools that look obviously missing

Confirmed against the actual registry (25 tools, `grep '@mcp.tool()' -A3
server.py`) and `PERMISSION_GROUPS` in `gate.py`. The consistent pattern:
write-then-forget is well covered; look-back/undo/correct is not.

- **No task cancel/purge** — `task_queue` only grants submit/status/list;
  nothing pulls a row back out of `pending`.
- **No `knowledge_delete`/`knowledge_update`** — only `kb_promote` (change
  domain) and `kb_journal` (append) exist; a bad ingest can't be corrected
  or removed.
- **Vault exists but is never exposed as a tool** — `vault.write`/`read`
  is only used internally by the `willow-mcp setup` CLI for OAuth provider
  credentials. No `secret_put`/`secret_get` tool lets an app store its own
  credentials encrypted at rest; today that would have to go through
  plain-SQLite `store_put`.
- **No manifest management tool** — creating/listing/revoking
  `manifest.json` requires hand-editing a file on disk; no
  `manifest_create`/`manifest_list`/`manifest_revoke`.
- **No pagination** on `store_list`/`store_search`/`store_search_all`/
  `knowledge_search` — fine at demo scale, not at real scale.
- **No routing-history read tool** — `agent_route`/`agent_dispatch_result`
  write to `routing_decisions`; nothing reads it back.
- **No schema-mapping introspection/reset** — can confirm a mapping, but
  can't list what's confirmed or un-confirm one if it was wrong, short of
  editing the mapping file directly (which `schema_confirm_mapping`'s own
  docstring acknowledges as the fallback).

@phase 6-stretch-nice-to-have
## 6. Stretch / nice-to-have

Roughly ranked by leverage relative to effort:

- **Kart worker heartbeat surfaced in `fleet_health`/`diagnostic_summary`**
  — directly closes the "queued vs. unattended" ambiguity from §1.
- **Semantic/embedding search for `knowledge_search`** — there's a stuck
  `willow_embed_backfill.py` task in the queue from May, suggesting this was
  already planned; today it's AND-logic full-text only.
- **Short-lived scoped tokens instead of static all-or-nothing manifest
  permissions** — would also narrow the stdio trust-model note in §2c.
- `receipts_search` (filter by tool/outcome/date, not just tail-N) and
  hash-chained receipts (tamper-evident audit trail).
- `agent_register`/`agent_deregister` for the `agents` table (currently
  populated out of band — nothing in this repo writes to it).
- Task priority/requeue/dead-letter handling for the 357 already-failed
  tasks sitting in the queue.
- `kb_link` — relate knowledge atoms to each other; the KB has no graph
  structure today.
- `store_list_collections` and TTL support on `store_put` (parity with
  `context_save`'s existing `ttl_seconds`).
- Drift detection for confirmed schema mappings if the underlying table's
  columns change after confirmation.
- Cross-app sharing primitive (explicitly grant app B read access to one of
  app A's collections/domains) as the safe alternative to §2b's
  all-or-nothing choice.
- A human-in-the-loop approval step for destructive calls (`store_delete`,
  `task_submit(allow_net=True)`), mirroring Claude Code's own permission
  prompts.
- MCP Prompts for canned workflows ("onboard a new app," "triage failed
  Kart tasks") — would turn some of this review's own tribal knowledge into
  something a client can discover directly instead of reverse-engineering.

@phase constraints
## Constraints

@constraint severity="critical"
**Not exploitable — checked and ruled out:** SQL injection (all values
parameterized; table/column identifiers go through a fixed allowlist or
live `information_schema` introspection, never raw caller strings), path
traversal (collection/table names regex-validated before touching the
filesystem).

@constraint severity="normal"
- **No tool annotations** — all 25 tools are bare `@mcp.tool()`
  (`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint` unset
  anywhere), so a client can't tell `store_delete` is destructive without
  reading source.

@constraint severity="critical"
- Some docstrings are excellent — `task_submit`'s states the exact
  `task_net` caveat inline, which is exactly what let us self-correct
  without reading source. Others (`store_list`, `kb_promote`, `agent_route`)
  don't mention their real preconditions (per-app scoping, required schema
  confirmation) at the docstring level, only in README prose a client
  calling the tool blind never sees.

@constraint severity="critical"
- **No task cancel/purge** — `task_queue` only grants submit/status/list;
  nothing pulls a row back out of `pending`.
