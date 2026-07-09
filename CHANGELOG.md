# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] — Unreleased

The v2 rebuild. Expands the server from a store/knowledge/task tool set into an
authorization-gated, agent-neutral platform with an HTTP OAuth serve mode.

### Added
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
