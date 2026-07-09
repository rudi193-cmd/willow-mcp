# Permissions matrix — ratified policy

*Status: **RATIFIED** — 2026-07-09*  
*Machine source: `bundle/config/specialists.json` → compiled `mcp_apps/{id}/manifest.json`*

Companion: `specialist-registry.md` · `human-orchestrator.md` · `gate.py`

---

## 1. How enforcement works

1. **Allow** — manifest `permissions` expands via `PERMISSION_GROUPS` in `gate.py` (groups and literal tool names).
2. **Deny** — manifest `deny_tools` is an overlay that wins over allows (defense in depth).
3. **Scope** — manifest `store_scope` confines SOIL collections (`prefix*` wildcards).
4. **Orchestrator writes** — `dispatch_send`, `verify_handoff`, `agent_clear` for `app_id=willow` additionally require `WILLOW_HUMAN_ORCHESTRATOR=1` (stdio) or OAuth binding (serve).
5. **Egress** — `task_net` is never implied by `task_queue` or `full_access`; must be explicit on the manifest line.

**Compile:** edit registry → `willow-mcp compile-agents` (or `willow-mcp-init` on first scaffold).

---

## 2. Permission groups (reference)

| Group | Tools (summary) |
|-------|-----------------|
| `store_read` | store_get, store_search, store_list, store_search_all |
| `store_write` | store_put, store_update, store_delete |
| `knowledge_read` | knowledge_search, kb_search, kb_at, kb_startup_continuity |
| `knowledge_write` | knowledge_ingest, kb_ingest, kb_journal, kb_promote |
| `task_queue` | task_submit, task_status, task_list |
| `dispatch_read` | dispatch_read, dispatch_list, handoff_read, session_read, session_enter |
| `dispatch_write` | dispatch_send, dispatch_accept, handoff_write_v4, verify_handoff, agent_clear, session_handoff_write |
| `orchestrator` | Desk + dispatch + context + fleet read + limited store/kb read |
| `fleet_read` | fleet_status, fleet_health |
| `context` | context_save, context_get, context_list, context_expire |
| `schema_admin` | schema_confirm_mapping |
| `audit` | receipts_tail |
| `full_access` | All gated tools except `task_net` |

`diagnostic_summary` is intentionally **ungated** (self-check must work when manifest is broken).

---

## 3. Specialist matrix

| Name | permissions | deny_tools | store_scope | Rationale |
|------|-------------|------------|-------------|-----------|
| **hanuman** | dispatch_write, task_queue, store_read, knowledge_read | kb_promote, knowledge_ingest | hanuman_* | Builder runs Kart; reads KB; no ratification writes |
| **loki** | dispatch_read, dispatch_write, knowledge_read | task_submit, store_put, store_update, store_delete, knowledge_ingest | loki_* | Auditor reviews and closes; never builds or mutates store/KB |
| **jeles** | dispatch_read, dispatch_write, knowledge_read | task_submit, kb_promote, kb_journal, knowledge_ingest | jeles_* | Librarian retrieves; no shell, no KB writes |
| **ada** | dispatch_read, dispatch_write, fleet_read, knowledge_read | task_submit, store_put, store_update, knowledge_ingest | ada_* | Operator monitors fleet; no execution or store mutation |
| **skirnir** | dispatch_read, context | — | skirnir_* | Witness reads packets + session context only |
| **vishwakarma** | dispatch_read, store_read, knowledge_read | task_submit | vishwakarma_* | Architect reads; no Kart |

---

## 4. Orchestrator seat (willow)

| Field | Value |
|-------|-------|
| permissions | orchestrator |
| deny_tools | — |
| store_scope | willow_*, projects_* |
| human_only | true |
| entry_mode | human_orchestrator |

Agents cannot `session_enter(willow, dispatch_id=…)`. Write tools require human host attestation.

---

## 5. Change control

1. Edit `bundle/config/specialists.json` (wheel) or `$WILLOW_HOME/config/specialists.json` (operator overlay).
2. Run `willow-mcp compile-agents` (`--force` to overwrite existing manifests).
3. Future: operator PGP signature on registry blob before compile (see `pgp-and-persona.md`).

---

*Ratified by operator authorization 2026-07-09. Replaces TBD placeholders in specialist-registry §4.*
