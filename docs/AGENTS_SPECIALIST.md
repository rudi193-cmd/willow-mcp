# AGENTS_SPECIALIST — Specialist entry guide

Cold-start map for **specialist** MCP seats (hanuman, loki, jeles, ada, …).

## Entry modes

| Mode | How | Closeout |
|------|-----|----------|
| **Dispatch** | `session_enter` with `dispatch_id` (or pending packet auto-bound) | `handoff_write_v4` |
| **Human** | `session_enter` without `dispatch_id` | `session_handoff_write` |

## First moves (dispatch)

1. `session_enter(app_id=<specialist>, session_id=…, dispatch_id=…)`
2. `dispatch_read` — read `assignment.md`
3. Do scoped work within manifest permissions
4. `handoff_write_v4` — structured closeout + narrative

## Namespace

Write only in your lane: `store_scope` from `mcp_apps/<app_id>/manifest.json`.

## Persona

Bundled voice files live at `$WILLOW_HOME/personas/<agent>.md` after `willow-mcp-init`.
Persona is overlay only — it does not change `app_id` or permissions.

## Hard rules

- No `WILLOW_HUMAN_ORCHESTRATOR` on specialist MCP configs.
- `task_submit` needs manifest `task_queue` + operator consent + egress lease.
- KB writes need `schema_confirm_mapping` before `knowledge_ingest`.

## Related docs

- `docs/design/specialist-registry.md`
- `docs/design/session-lifecycle.md`
- `config/specialists.json` (after init: `$WILLOW_HOME/config/specialists.json`)
