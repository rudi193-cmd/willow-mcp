# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] — Unreleased

The v2 rebuild. Expands the server from a store/knowledge/task tool set into an
authorization-gated, agent-neutral platform with an HTTP OAuth serve mode.

### Added
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
  `full_access`.
- **Schema adaptation**: read tools adapt to the host database's real column
  names; write tools refuse (`unconfirmed_schema`) until the mapping is reviewed
  and confirmed via `schema_confirm_mapping`.
- Tool set expanded 11 → 21 (`kb_*`, `agent_*`, `fleet_*`, `schema_confirm_mapping`).
- Input sanitizer, per-caller rate limiter, and a receipt log.
- Claude Code plugin: a `PreToolUse` hook that redirects raw `psql`/`sqlite3`
  access to the matching MCP tool, and `schema-confirm` / `willow-serve` skills.
- `scripts/willow-serve` — turn OAuth serve mode on/off on demand via a systemd
  `--user` service, toggling the matching `.mcp.json` client entry to match.
  Installed unit template in `deploy/`.
- Dockerfile and GitHub Actions test workflow (runs against a Postgres service).

### Fixed
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
