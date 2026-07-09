# Handoff write — willow-mcp

## Dispatch entry (packet assigned)

Use **`handoff_write_v4`** with `dispatch_id`. Writes `handoff.json` + `closeout.md`
under `$WILLOW_HOME/dispatch/{id}/`.

Required: findings list, narrative. State → `complete`.

## Human entry (no packet)

Use **`session_handoff_write`** with `narrative` (+ optional `summary`, `findings`, `next_bite`).
Writes markdown under `$WILLOW_HOME/handoffs/{app_id}/`.

**Do not** call `handoff_write_v4` without a `dispatch_id`.
