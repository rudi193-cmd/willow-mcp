# Human-only orchestrator (LOCKED)

*Status: **LOCKED** — 2026-07-09 · complements `product-layout.md`, `session-lifecycle.md` §2a*

## Rule

**Willow (`app_id=willow`) is the orchestrator seat. Only a human operator may run it. No agent may.**

| Actor | May call `session_enter(willow)`? | May call `dispatch_send` as willow? |
|-------|-----------------------------------|-------------------------------------|
| Human operator (orchestrator IDE session) | Yes → `human_orchestrator` | Yes (with host attestation) |
| Specialist agent (Hanuman, Loki, …) | **No** — use own `app_id` | **No** |
| Injected text in `assignment.md` | N/A | **No** — not a caller |

---

## Why (prompt injection)

Without this boundary:

1. A specialist could pass `app_id=willow` on MCP calls (stdio trusts the argument).
2. Malicious content in a handoff narrative could instruct the model to "verify and clear" falsely.
3. Auto-pick pending packet could bind an agent session to orchestrator work.
4. The orchestrator becomes a **privilege escalation target** — whoever speaks as willow dispatches the fleet.

The orchestrator is not a faster worker. It is the **human's proxy** for separation of duties: assign → review evidence → clear.

---

## `session_enter` behavior

| `app_id` | Entry mode | `dispatch_id` accepted? | Auto-pick pending? |
|----------|------------|-------------------------|-------------------|
| `willow` | **`human_orchestrator`** | **Never** | **Never** |
| specialists | `human` or `dispatch` | Yes (dispatch path) | Yes (one pending) |

```text
session_enter("willow", …)  →  entry_mode: human_orchestrator
                               closeout: session_handoff_write
                               agent_doc: orchestrator orient (not specialist guide)

session_enter("hanuman", dispatch_id="")  →  human or dispatch per rules
```

---

## Orchestrator write tools (gated)

These require **human host attestation** in stdio mode:

- `dispatch_send`
- `verify_handoff`
- `agent_clear`

**Stdio:** `WILLOW_HUMAN_ORCHESTRATOR=1` on the MCP server process environment — set **only** in the orchestrator workspace `.cursor/mcp.json` / Claude MCP config. Specialist project configs must omit it.

**PGP (planned):** Same operator fingerprint signs manifests, session attestations, and dispatches. No product dev-bypass — see [`pgp-and-persona.md`](pgp-and-persona.md). Env attestation is interim until session `.sig` lands.

**Serve (OAuth):** Identity bound to `willow` after human `confirm-binding` — binding is the attestation.

Read tools (`dispatch_list`, `dispatch_read`) remain available to any manifest that holds `dispatch_read` — desk visibility is lower risk than dispatch/verify/clear.

---

## Injection hygiene (orchestrator reading packets)

When the human orchestrator reads specialist output:

| Source | Trust model |
|--------|-------------|
| `handoff.json` | **Structured evidence** — verify against schema, checklist, evidence refs |
| `closeout.md` / narrative | **Untrusted prose** — desk reading only; never execute embedded instructions |
| `assignment.md` (inbound to specialist) | **Work order for them** — orchestrator authored it; specialists treat as untrusted for tool escalation |

`verify_handoff` checks structure and evidence — it does not "believe" the narrative.

---

## Wiring checklist (operator)

1. Orchestrator seat (`~/github/willow`): MCP env includes `"WILLOW_HUMAN_ORCHESTRATOR": "1"`.
2. Specialist seats (willow-mcp repo, etc.): **no** `WILLOW_HUMAN_ORCHESTRATOR`; `app_id` defaults to specialist.
3. `mcp_apps/willow/manifest.json`: `"human_only": true`, `"permissions": ["orchestrator", …]`.
4. Never add `orchestrator` permission group to specialist manifests.

---

## Code map

| Module | Role |
|--------|------|
| `human_session.py` | `is_orchestrator_app`, `orchestrator_write_denial` |
| `dispatch.py` | `session_enter` willow branch |
| `server.py` `_gate` | Human check after manifest permit |
| `home_init.py` | Seeds `mcp_apps/willow/manifest.json` with `human_only` |

---

*Agents implement. Humans orchestrate. The gate exists so injection cannot collapse that line.*
