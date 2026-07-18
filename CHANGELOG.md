# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] — Unreleased

The v2 rebuild. Expands the server from a store/knowledge/task tool set into an
authorization-gated, agent-neutral platform with an HTTP OAuth serve mode.

### Added
- **Store/gap introspection & cleanup tools** — `whoami` (your own manifest and
  effective permissions; ungated like `diagnostic_summary`), `store_collections`
  and `store_stats` (list / count the SOIL collections in your `store_scope`
  without a search), and `store_purge_collection` / `gap_delete` /
  `gap_purge_topic` (reversible soft-delete cleanup — a whole collection, one
  gap, or every gap under a topic; each confirm-guarded and archive-don't-delete,
  with `gap_purge_topic` skipping promoted gaps). Shaped by dogfooding the server
  from inside — each tool surfaced the need for the next.
- **One-command local sandbox + native session load.**
  `scripts/sandbox-bootstrap.sh` and fresh-install Postgres DDL
  (`docs/schema/{knowledge,agents,routing_decisions}.postgres.sql`) take a clone
  to a working stdio server; a synchronous `SessionStart` hook
  (`.claude/hooks/session-start.sh`) plus `.claude/settings.json` provision the
  box (venv, `$WILLOW_HOME`, Postgres, bubblewrap) and load willow-mcp natively
  at session start on Claude Code on the web, and activate the `PreToolUse`
  sudo-invariant guard.
- **Egress secret redaction** (`secret_scan.py`, wired at the `_guarded`
  funnel) — defense-in-depth for the standing guarantee "no tool ever returns a
  credential." The credential *accessor* already withheld values
  (`credential_source()` returns a source, never the secret); the *data* path
  did not — a stored record, a KB atom, task output, or an integration response
  body carrying an `sk-…`, an `AKIA…`, or a private-key block was returned
  verbatim. Now the one funnel every tool response passes through redacts
  high-confidence credential formats (AWS access key id, provider `sk-` keys,
  GitHub/Slack/Google/Stripe tokens, JWTs, PEM private-key blocks) to
  `[REDACTED:<kind>]` before egress. Redacts rather than blocks, so legitimate
  retrieval survives minus the credential; precision-first patterns so ordinary
  ids/hashes are not false-positived; fail-closed if the scanner itself errors
  (the payload is denied, never returned unscanned); and payload-free receipts
  (a `redacted` row records only WHICH kinds, never the value). Unit contract in
  `test_secret_scan.py`, end-to-end store round-trip in `test_server.py`.
  - **Per-manifest exemption** (`gate.egress_secret_exempt`): a tool that
    legitimately must return a raw token — the canonical case is an
    `integration_call` performing an OAuth token exchange — can be named in its
    app's manifest `egress_secret_exempt` list. The scan still runs (the audit
    trail stays complete); an exempted return is kept raw but receipted as
    `credential_returned` with the kinds, so the exception is loud, never
    silent. Fail-closed toward redaction: a bad app_id, a missing/unreadable
    manifest, or a malformed field exempts nothing, and — since manifests are
    operator-side (the PreToolUse hook blocks an app from writing its own) — an
    app can never exempt itself. Per-tool, not a blanket unlock.
- **The Grove** (`the_grove.py`) — a rings store for *lessons*, sibling to
  `schema_profile`'s vocabulary rings but unbounded on purpose: vocabulary may
  be pruned cheaply, lessons are kept precisely so the deployment cannot become
  something that forgets them. One ring per lesson (`add_ring`/`rings`/`depth`),
  `canopy()` (the visible architecture), `deep_roots()` (the recorded lessons),
  and a pipe-friendly status: `python -m willow_mcp.the_grove --status` reports
  stability, ring depth, and soil health; run with no arguments for the resting
  display. A diseased rings file reads as empty but reports the grove
  `unsettled` rather than silently claiming depth 0.
- **`core.record_lessons()`** — distill any SQLite journal (any schema — the
  table holding the writing is introspected, never assumed) into entry count,
  date range, and theme tallies, then grow exactly one grove ring carrying the
  lesson worth keeping. The source is opened `mode=ro` — a journal handed to
  this function is being remembered, not edited — and every failure is
  fail-soft (`{"error": ...}`, no ring), because a ring must never record a
  lesson that wasn't actually learned.
- **Integration adapters** (`integrations.py`) — outbound HTTP adapters with a
  shared base (env→vault credential resolution, bounded stdlib transport with
  Retry-After-honoring retries, credential-scrubbed errors). Two live adapters
  (`github`, `huggingface`) and six **declared stubs** (`gmail`, `slack`,
  `notion`, `google-drive`, `datadog`, `jira`) that refuse fail-closed and name
  what earns their implementation. New tools `integration_list`,
  `integration_status`, `integration_call`; new operator CLI
  `willow-mcp-integrations` (`list` / `check` / `set-token`). Live calls are the
  fourth consumer of the three-key egress gate, keyed on a new
  `integration_net` capability — its own line, never implied by `task_net` or
  `full_access`, because the server-process lane is strictly more privileged
  than the sandbox lane. `integration_call` is likewise excluded from
  `full_access`. See `docs/design/integrations.md` for the earn rule.
- **`willow-mcp tree` / `tree_view.build_tree()` — the integration seam for a real
  dashboard.** `docs/design/*.html` sketches a client UI as a tree (trunk/sap/
  canopy/roots/rings/leaves/litter/stomata) with fabricated numbers; `tree`
  makes it real, one call returning every part in that shape instead of a
  dashboard assembling `fleet_status`/`fleet_health`/`kb_startup_continuity`/
  `receipts_tail`/`gates` itself. `sap`/`canopy`/`leaves` call straight into the
  same `@_guarded` tool functions an MCP client would reach (gating, rate
  limiting, and receipt logging all still apply) and degrade to
  `{"error": "postgres_unavailable"}` with no database configured, matching
  those tools' existing shape. `roots`/`rings`/`litter`/`stomata` read local
  SQLite/filesystem state directly and work with no Postgres at all. Adds
  `Store.list_collections()` (factored out of `search_all`'s own enumeration)
  as the `roots` data source.
- **`willow-mcp gates` — every authorization gate as one on/off panel, egress-lease
  shaped.** Diagnosing a denial meant knowing which of a dozen-plus gates to check
  (manifest permissions, `task_net`, `integration_net`, `consent.*`, egress lease,
  identity bindings, strict trust root, severance, human-orchestrator attestation,
  worker liveness) and which file or CLI command controlled it. `gates` shows all
  of them at once, each rendered the way the egress lease already renders itself:
  on/off, plus how long the "on" is good for — `standing` for gates with no expiry,
  `process-lifetime` for env-var gates that only change at restart, or a live
  countdown for the lease. `--html` writes a self-contained static snapshot with a
  client-side ticking countdown and copy-to-clipboard action buttons; `--json`
  dumps raw rows for scripting. New `allow-permission` / `deny-permission`
  subcommands give manifest permission groups the operator-only local-CLI
  affordance they lacked before (only hand-editing `manifest.json` or a full
  `compile-agents` regenerate existed prior) — local-CLI-only and never MCP tools,
  the same sudo-invariant boundary as `grant-net`/`confirm-binding`, so an agent can
  never grant itself a permission it was just denied. `consent.*` rows are
  read-only by design (willow-mcp never writes that policy) and never show a
  command.
- **`gates` is now interactive — a real TUI and a live local HTML dashboard, not
  just a snapshot.** Bare `willow-mcp gates` in a real terminal opens a curses
  screen: arrow keys / j-k to move, enter/space to actually flip the highlighted
  gate — grant/revoke a lease (prompts for TTL + reason), allow/deny a permission,
  confirm an identity binding, drain the task queue once. `willow-mcp gates
  --serve` does the same over a `127.0.0.1`-only local HTTP server with real
  clickable buttons, for anyone who'd rather use a browser. Both share one action
  layer (`gates_actions.py`) with the `allow-permission`/`grant-net`/
  `confirm-binding` CLI subcommands — pressing a row calls the exact same
  functions, no new authority. `--json`/`--html`/`--static` are unchanged and
  still what runs automatically when stdout isn't a real terminal (piped, CI),
  so nothing scripted against the old output breaks.
- **Gates dashboard: readable state labels and a real layout, not one long
  scroll of identical cards.** Feedback on the live HTML dashboard: bare
  ON/OFF buttons don't say what "on" means (granted? allowed? running?), and
  ~30 same-sized cards in one flat grid reads as noise, not a dashboard. Every
  row now carries a `state_label` in context — GRANTED/NOT GRANTED,
  ALLOWED/BLOCKED, ACTIVE/NONE, CONFIRMED/PENDING, RUNNING/STALLED/STOPPED,
  ENABLED/DISABLED — and a `category` (egress & network / system / identity /
  permissions) that both the TUI and the two HTML pages now group by instead
  of showing everything at once. The HTML pages default to the egress tab
  (smallest group, the one with a clock and real consequence) with a summary
  strip above the tabs for at-a-glance state, and render the ~20-row,
  rarely-touched permissions group as a compact single-column list instead of
  large cards. New shared module `gates_html.py` holds the CSS/JS both the
  static snapshot (`gates_panel.render_html`) and the live dashboard
  (`gates_serve.py`) now render through, so the two pages can't drift apart
  the way two independent ~200-line templates eventually would.
- **Time-boxed egress leases** (B-32 / L-NET-02). `task_submit(allow_net=True)` now
  needs a **third** key: an unexpired lease issued by the operator with
  `willow-mcp grant-net <app_id> --ttl 30m --reason ...` (ceiling 3h, per FRANK
  `cc553729`). `task_net` is demoted to a capability — *this app may ever ask* —
  while the lease is the grant itself, carrying an issuer, a reason, and a deadline.
  **No MCP tool can mint a lease**: issuance is local-CLI-only, exactly as
  `confirm-binding` is. New `revoke-net` and `net-status` subcommands. Leases are
  read fail-closed — absent, unparseable, expired, over-ceiling, a deadline with no
  timezone, or a record naming a different `app_id` than the file it sits in all
  deny. Because leases live under `mcp_apps/`, they inherit B-14's `bound_ro`
  sandbox mount: a sandboxed task cannot mint one (verified — `OSError(EROFS)`).
  `diagnostic_summary` gains a `net_lease` check whose `self_writable` field names
  every authorizing key the running process could forge, and the PreToolUse hook
  blocks an agent from writing any of them. **The residual is real and deliberate:**
  on a single-uid host the agent can still write the lease, so this narrows and
  audits the self-grant rather than preventing it. Set
  `WILLOW_MCP_STRICT_TRUST_ROOT=1` after `chown`ing the trust root to a uid the
  agent does not run as, and egress is refused whenever the keys are self-writable.
  Off by default, because enabling it before that separation exists would deny
  egress on every current install.
- **Two-key egress gate** (B-29). `task_submit(allow_net=True)` now requires the
  operator's standing `consent.internet` from `$WILLOW_HOME/settings.global.json`
  **in addition to** the app's `task_net` capability. Either one missing denies
  (`net_denied` / `consent_denied`) before any write. Flipping `consent.internet`
  to `false` stops egress fleet-wide without editing a single manifest. The new
  `consent.py` reads that policy **fail-closed** — an absent file, an unparseable
  file, or a non-boolean value all read as denied — and only ever reads it; the
  policy is authored by willow-2.0. `diagnostic_summary` gains a `consent` check
  that raises an error when the legacy `consent.json` and canonical
  `settings.global.json` disagree, rather than silently obeying one.
- **Worker liveness** (Kart lift stage 4, B-26). `willow-mcp worker` publishes a
  heartbeat through kartikeya's `on_heartbeat` seam. `fleet_health` now reports
  `workers` (each `alive` / `stale` / `dead`) and a `stranded` boolean — true when
  there is pending work and no live worker — and `diagnostic_summary` gains a
  `worker` check that names the condition and its fix. Previously a submitted task
  looked identical whether a worker was about to claim it or none existed.
  Heartbeats are advisory telemetry, never authorization: no gate reads them, and
  reads verify the recorded pid is a live local process.
- **HTTP serve mode** (`--serve`) with OAuth 2.0 + PKCE against Google/Apple as
  the upstream IdP, plus a local credential vault (`willow-mcp setup`).
- **Identity binding**: serve-mode sign-ins propose an unconfirmed
  `(issuer, subject_id) → app_id` binding; an operator-only, stdio-local
  `willow-mcp confirm-binding` confirms it before any tool permission applies.
  Fail-closed for authenticated-but-unbound callers.
- **`email_basis`** on bindings (`asserted` / `first_auth_only` / `relay` /
  `unavailable`) so downstream code knows how much to trust an IdP email, plus
  `email_drift` annotation when a bound identity's email changes.
- **Manifest-based ACL gate** (`gate.py`): every tool call is authorized against
  `$WILLOW_HOME/mcp_apps/<app_id>/manifest.json` — no ACL database, no external
  auth service. Permission groups: `store_read`, `store_write`, `knowledge_read`,
  `knowledge_write`, `schema_admin`, `task_queue`, `agent_dispatch`, `fleet_read`,
  `context`, `audit`, `full_access`.
- **`diagnostic_summary`** — a self-check that answers "is this install wired
  correctly?": SOIL store (path/writable/collections), Postgres (reachable +
  which database + whether willow-mcp's tables are present), schema-confirmation
  state, your `app_id`'s manifest + resolved permissions, identity bindings, and
  the config environment — then a verdict (ok/degraded/broken) with named
  problems and fixes. Deliberately ungated (it must answer even when the manifest
  or database is misconfigured); reveals only the caller's own config, never
  fleet rows or vault secrets; serve mode requires a confirmed identity and
  redacts absolute paths. Its headline case is the empty-DB / wrong-`WILLOW_PG_DB`
  footgun (Postgres connects but points at a database without the tables).
- **Session context** (`context_save` / `context_get` / `context_list` /
  `context_expire`) — ephemeral, per-identity working state that survives across
  sessions, with an optional TTL. SOIL-backed (no Postgres needed); reads
  transparently skip and purge expired entries; scoped to your `app_id`.
- **`receipts_tail`** — read your own most-recent tool-call receipts (a
  self-audit trail); scoped to your `app_id`, never another identity's calls.
- **Schema adaptation**: read tools adapt to the host database's real column
  names; write tools refuse (`unconfirmed_schema`) until the mapping is reviewed
  and confirmed via `schema_confirm_mapping`.
- Tool set expanded 11 → 27 (`kb_*`, `agent_*`, `fleet_*`, `schema_confirm_mapping`,
  `diagnostic_summary`, `context_*`, `receipts_tail`).
- Input sanitizer, per-caller rate limiter, and a receipt log.
- Claude Code plugin: a `PreToolUse` hook that redirects raw `psql`/`sqlite3`
  access to the matching MCP tool, and `schema-confirm` / `willow-serve` skills.
- `scripts/willow-serve` — turn OAuth serve mode on/off on demand via a systemd
  `--user` service, toggling the matching `.mcp.json` client entry to match.
  Installed unit template in `deploy/`.
- Dockerfile and GitHub Actions test workflow (runs against a Postgres service).

### Fixed
- **`kb_startup_continuity` crashed on a jsonb `tags` column**
  (`operator does not exist: jsonb ~~`) and silently returned empty on a native
  `text[]` column. Now branches on the column type: `::text LIKE` for text /
  jsonb, `= ANY(col)` element match for arrays.
- **Receipts escaped the sovereign box.** The tool-call audit trail defaulted to
  `~/.willow/mcp_receipt.db` — outside any box `$WILLOW_HOME` points at. Now
  defaults under `$WILLOW_HOME` (explicit `db_path` / `WILLOW_MCP_RECEIPT_DB`
  still win), keeping the audit trail inside the data-vault boundary.
- **Test isolation could be defeated by the ambient environment.** conftest used
  `os.environ.setdefault`, so an exported `WILLOW_HOME`/`WILLOW_STORE_ROOT` (e.g.
  from the new SessionStart hook) ran the suite against a real store, polluting
  it. It now force-sets the isolation vars.
- **Purge confirm-guard degeneration.** An explicit empty `collection`/`topic`
  made the `confirm != target` check pass (`"" == ""`); the purge tools now
  reject an empty target before the confirm check.
- **PreToolUse guard coverage.** The owned-store tripwire now catches
  psycopg3/asyncpg/pg8000 and `vault.db`/`kart.db`/`store.db` (a SOIL collection
  reached by absolute path); its known limits (a `python -c` one-liner, unlisted
  clients) are documented rather than overclaimed.
- **`willow-mcp gates`/`net-status`/`tree` crashed with an unhandled
  `BrokenPipeError` traceback when piped into something that closes early**
  (`willow-mcp gates | head`, `willow-mcp net-status app | grep -q active`) —
  found by wiring the CLI into a CI smoke test. These subcommands print
  multiple lines and are exactly the shape someone pipes into `head`/
  `grep -q`; a downstream reader closing before the writer finishes raises
  `BrokenPipeError` on the next write, which Python does not handle for you.
  `main()` now wraps its dispatch and exits clean (code 1) instead.
- **`pip install willow-mcp[worker]` was advertised but never existed (B-27).**
  The worker's "kartikeya is missing" errors, its `--help` text, and
  `task_queue.py`'s docstring all pointed at a `[worker]` extra; `pyproject.toml`
  declares no extras at all, and `kartikeya` has been a hard dependency since the
  B-22 close-out. The one message shown when a worker can't start told operators
  to run a command that errors. All four sites now say `pip install willow-mcp`.
- **Schema confirmation could accept a name match as truth (#20).**
  `schema_confirm_mapping` mapped canonical fields to real columns by name and
  confirmed without ever showing the data — so a `content` column that actually
  holds a provenance blob (with the real text in `title`/`summary`) would be
  confirmed as canonical `content`, and reads returned metadata instead of
  knowledge. `schema_confirm_mapping` now takes `preview=True` (dry-run:
  proposed mapping **plus** a rendered `sample` row, nothing written) and, on a
  real confirm, includes the same `sample` — confirmation is never blind. The
  `schema-confirm` skill requires reviewing the sample before confirming, and
  `diagnostic_summary` reports each table's field→column map so a
  confirmed-but-wrong mapping is visible in the self-check.
- `--port` / `--host` CLI flags were silently ignored in serve mode — the
  FastMCP object, base URL, and OAuth issuer are built at import time and never
  saw the argparse values. Resolved at import with precedence CLI > env > default.
- `task_*` / `fleet_health` referenced a nonexistent `kart_task_queue` table;
  pointed at the real `tasks` table.
- Security-audit hardening (Level 2 WLWR1) across the tool surface.

### Changed
- **`full_access` completeness.** Now includes `specialist_list` /
  `specialist_get` and the new store/gap read tools, matching the documented
  contract ("all gated tools except the egress lines `task_net` and
  `integration_call`"); `permissions-matrix.md` corrected to match. Bulk
  `gap_purge_topic` is its own opt-in `gap_purge` group (it soft-deletes across
  the fleet-shared gaps backlog), not folded into everyday `gap_write`.
- Repository is agent-neutral: removed personal/fleet-specific references from
  the public surface.

## [1.2.0] — 2026

### Added
- Full parameter descriptions and behavior annotations for all tools.

## [1.1.0] — 2026

### Added
- Multi-keyword AND search in `knowledge_search`.
- Record API and `WILLOW_STORE_ROOT` for pointing at an existing store root.

### Changed
- **Breaking**: aligned the SQLite store schema with willow-1.7's `WillowStore`.

## [1.0.0] — 2026

### Added
- Initial release: agent-neutral MCP server with a SQLite store (SOIL),
  Postgres knowledge base, and Kart task queue (11 tools).

[2.0.0]: https://github.com/rudi193-cmd/willow-mcp/releases
[1.2.0]: https://pypi.org/project/willow-mcp/1.2.0/
[1.1.0]: https://pypi.org/project/willow-mcp/1.1.0/
[1.0.0]: https://pypi.org/project/willow-mcp/1.0.0/
