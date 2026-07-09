# ORIENT_ORCHESTRATOR — Willow orchestrator seat

Human-only entry for the **willow** orchestrator. Agents cannot run this seat.

## First moves

1. `session_enter(app_id="willow", session_id=…)` — returns `human_orchestrator` mode; no `dispatch_id`.
2. `dispatch_list` — desk view of packets.
3. `dispatch_send` — assign work to specialists (requires `WILLOW_HUMAN_ORCHESTRATOR=1` on MCP host).
4. `verify_handoff` — close the loop when a specialist completes.

## Tri-modal lens

| Mode | Question |
|------|----------|
| Governance | May we? Who witnessed it? |
| PM | What's in flight, by when? |
| PA | What does the operator need, when? |

## Hard rules

- **Never** pass `dispatch_id` to `session_enter` for willow — rejected with `orchestrator_human_only`.
- Discussion is not authorization. Check envelopes / grants before cross-repo or destructive acts.
- Close with `session_handoff_write`, not dispatch v4 closeout.

## Related docs

- `docs/design/human-orchestrator.md`
- `docs/design/session-lifecycle.md`
- Charter `~/github/willow/ORIENT.md` (governance seat; not bundled here)
