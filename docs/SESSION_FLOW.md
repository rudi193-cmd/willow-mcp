# SESSION_FLOW.md — Session lifecycle (willow-mcp)

*Entry mode decides human vs dispatch path.*

## Entry modes

| Entry | Signal | Path | Closeout |
|-------|--------|------|----------|
| **Human orchestrator** | `app_id=willow` only | `human_orchestrator` | `session_handoff_write` |
| **Human specialist** | Normal prompt; no `dispatch_id` | `human` | `session_handoff_write` / `context_save` |
| **Dispatch specialist** | `dispatch_id` / session / pending | `dispatch` | `handoff_write_v4` |

Call **`session_enter(app_id, session_id, dispatch_id="")`** at session start.

## States (dispatch path only)

```
pending → working → complete → verified → cleared
```

| State | Meaning |
|-------|---------|
| **pending** | Packet written; specialist has not accepted |
| **working** | Specialist accepted; executing `assignment.md` |
| **complete** | `handoff_write_v4` written |
| **verified** | Orchestrator ran `verify_handoff` |
| **cleared** | Orchestrator ran `agent_clear` |

## Packet directory

```
$WILLOW_HOME/dispatch/{dispatch_id}/
├── meta.json
├── assignment.md
├── status.json
├── handoff.json      # on complete
└── closeout.md       # on complete
```

## MCP tools

| Tool | Who | Action |
|------|-----|--------|
| `dispatch_send` | Orchestrator | Create packet |
| `dispatch_list` | Either | List packets |
| `dispatch_read` | Either | Read assignment |
| `dispatch_accept` | Specialist | pending → working |
| `session_enter` | Either | Resolve human vs dispatch entry |
| `session_handoff_write` | Specialist (human entry) | Markdown closeout, no dispatch_id |
| `handoff_write_v4` | Specialist (dispatch entry) | complete |
| `verify_handoff` | Orchestrator | verified |
| `agent_clear` | Orchestrator | cleared |

See `docs/design/session-lifecycle.md` for full design.
