# Willow — session start

Call **`session_enter(app_id, session_id, dispatch_id="")`** at session open.

Inference client (Cursor, Claude Code, local LLM host, …) is replaceable — the tool plane is willow-mcp. Hooks are optional; this skill is mandatory.

---

## Willow (`app_id=willow`)

Human operator seat only. Agents must not use `app_id=willow`.

Host MCP env must include **`WILLOW_HUMAN_ORCHESTRATOR=1`**. Specialist configs must omit it.

**Never** pass `dispatch_id` to `session_enter` for willow — rejected (`orchestrator_human_only`).

### Open (every Willow session)

Run in order:

| Step | Tool | Pass criteria |
|------|------|---------------|
| 1 | `session_enter("willow", session_id)` | `entry_mode: human_orchestrator` — read `message`, `agent_doc_section` |
| 2 | `diagnostic_summary(app_id="willow")` | `broken` → stop and report; `ok` or `degraded` → continue |
| 3 | `dispatch_list(app_id="willow", …)` | Desk view — pending / working / complete packets |
| 4 | `commitment_surface(app_id="willow")` | What may be worth the operator's attention now |

Work in **whatever mode the user asks for** (governance, portfolio, commitments, dispatch, build). No lane declaration required at open.

Close with **`session_handoff_write`** — not `handoff_write_v4`.

Security: `docs/design/human-orchestrator.md`. Dispatch loop: `docs/SESSION_FLOW.md`.

### Charter home — ORIENT steps 1–3

When the charter project is mounted (`WILLOW_HANDOFF_PROJECT`, `WILLOW_PROJECT_ROOT`, or `~/github/willow` on disk), run **after** the open table above.

Collections follow `soil/manifest.json` under the project store (`WILLOW_STORE_ROOT`).

**Step 1 — project context (tri-modal SOIL)**

| Intent | willow-mcp call |
|--------|-----------------|
| Current focus stack | `store_get(app_id="willow", collection="stack", record_id="current")` |
| Portfolio threads | `store_list(app_id="willow", collection="pm/portfolio")` |
| Milestones / deadlines | `store_list(app_id="willow", collection="pm/milestones")` |
| Commitments lane | `store_list(app_id="willow", collection="pa/commitments")` |

**Step 2 — continuity**

| Intent | willow-mcp call |
|--------|-----------------|
| Startup continuity atoms | `kb_startup_continuity(app_id="willow")` |
| Active packet bodies | `handoff_read(app_id="willow", dispatch_id=…)` for items from step 3 `dispatch_list` |

If a call is gate-denied, note it and continue (`degraded` is acceptable).

**Step 3 — law and collection map (read files)**

Read at `WILLOW_PROJECT_ROOT` (default `~/github/willow`):

- `CONSTITUTION.md`
- `envelopes/pre-approved.json` — active grants
- `AGENT_SERVICES.md` — seat obligations
- `soil/manifest.json` — collection map

Charter depth (flags, fleet read, `next_bite` writeback): `ORIENT.md` in the governance repo.

### Vault / greenfield home

When `WILLOW_HOME` is a data-vault box only (no charter mount), skip the charter block. Open table (steps 1–4) is sufficient.

---

## Specialists (`app_id` = hanuman, loki, jeles, ada, …)

| Signal | Mode | Closeout |
|--------|------|----------|
| Normal prompt, no `dispatch_id` | **human** | `session_handoff_write` or `context_save` |
| `dispatch_id` / pending packet | **dispatch** | `handoff_write_v4` |

### Dispatch path

1. `session_enter` → read `assignment.md` from the response
2. Work within manifest permissions
3. `handoff_write_v4`

### Human path

1. `session_enter` → `entry_mode: human`
2. Work
3. `session_handoff_write`

No `WILLOW_HUMAN_ORCHESTRATOR` on specialist MCP configs.

Persona voice: `$WILLOW_HOME/personas/<agent>.md` if present — overlay only; does not change `app_id` or permissions.
