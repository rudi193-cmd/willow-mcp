# Contributing

Thanks for your interest in willow-mcp. This is a small, focused MCP server;
contributions that keep it agent-neutral and fail-closed are welcome.

## Development setup

```bash
git clone https://github.com/rudi193-cmd/willow-mcp
cd willow-mcp
python3 -m venv .venv
.venv/bin/python3 -m pip install -e . pytest
```

Requires Python 3.11+. The repo-local venv matters for MCP clients: the stdio
server is launched as `.venv/bin/python3 -m willow_mcp`, and a missing import in
a bare host interpreter crashes the server before the MCP handshake.

## Running tests

```bash
.venv/bin/python3 -m pytest tests/ -q
```

Some tests exercise the Postgres knowledge base and expect a reachable server.
CI runs them against a `postgres:15` service with these env vars — set the same
locally if your Postgres needs them:

```bash
PGHOST=localhost PGPORT=5432 PGUSER=postgres PGPASSWORD=postgres \
  .venv/bin/python3 -m pytest tests/ -q
```

The full suite must be green before a change can merge (see below).

## Branching and pull requests

`master` is protected by a **no-bypass ruleset**: all changes land through a
pull request with a green `test` check. Direct pushes to `master` are rejected.

1. Branch off the latest `master` (`git checkout -b my-change origin/master`).
2. Make the change **and its tests in the same PR** — new behavior ships with
   coverage; "no prior test" is not a reason to skip one.
3. Open a PR against `master`; wait for the `test` check to pass.
4. Merges use `--merge` (merge commit), not squash — the history is kept linear
   by first-parent, and each PR stays a reviewable unit.

## Code layout

| Path | What it is |
|------|------------|
| `src/willow_mcp/server.py` | Tool definitions, the guard pipeline, and `main()` |
| `src/willow_mcp/gate.py` | Manifest-based ACL — permission groups, fail-closed checks |
| `src/willow_mcp/oauth.py` | Serve-mode OAuth 2.0 + PKCE provider (Google/Apple) |
| `src/willow_mcp/identity_binding.py` | `(issuer, subject) → app_id` bindings, `email_basis`, drift |
| `src/willow_mcp/vault.py` | Local encrypted credential vault |
| `src/willow_mcp/schema_profile.py` | Host-DB schema adaptation and confirm gate |
| `src/willow_mcp/db.py` | Postgres access |
| `hooks/`, `skills/` | Claude Code plugin surface (see `.claude-plugin/plugin.json`) |
| `docs/design/` | Design docs — schema adaptation, hooks-and-skills |

## Conventions

- **Fail closed.** A missing manifest, an unconfirmed binding, or an unconfirmed
  schema mapping denies the operation. Preserve that posture.
- Keep the tool surface agent-neutral — no personal, fleet-, or host-specific
  references in the public code or docs.
- New tools that carry a footgun should ship their hook and/or skill in the same
  change, not as a later add-on.
- Update `CHANGELOG.md` under `[Unreleased]` / the pending version for anything
  user-visible.
