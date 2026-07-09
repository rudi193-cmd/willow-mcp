# Session start — willow-mcp

Call **`session_enter(app_id, session_id, dispatch_id="")`** at session open.

## Willow (orchestrator) — human only

**`app_id=willow` is the human orchestrator seat. Agents must not use it.**

```
session_enter("willow", session_id)  →  entry_mode: human_orchestrator
```

- **Never** pass `dispatch_id` for willow — rejected.
- Desk: `dispatch_list` · assign: `dispatch_send` (human host only).
- Close: `session_handoff_write`.

Orchestrator MCP config must set `WILLOW_HUMAN_ORCHESTRATOR=1`. Specialist configs must not.

See `docs/design/human-orchestrator.md`.

## Specialists

| Signal | Mode | Closeout |
|--------|------|----------|
| Normal prompt, no id | **human** | `session_handoff_write` or `context_save` |
| `dispatch_id` / pending packet | **dispatch** | `handoff_write_v4` |

## Dispatch path (specialists)

1. `session_enter` → read `assignment.md`
2. Work
3. `handoff_write_v4`

## Human path (specialists)

1. `session_enter` → `entry_mode: human`
2. Work
3. `session_handoff_write`
