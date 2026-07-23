---
kind: doc
name: permissions-matrix-ratified-policy
description: "Ratified policy for how manifest permissions, deny-tool overlays, and store scoping are enforced across Willow specialists."
---

@markdownai v1.0

# Permissions matrix — ratified policy

*Status: **RATIFIED** — 2026-07-09*  
*Machine source: `bundle/config/specialists.json` → compiled `mcp_apps/{id}/manifest.json`*

Companion: `specialist-registry.md` · `human-orchestrator.md` · `gate.py`

---

@phase 1-how-enforcement-works
## 1. How enforcement works

1. **Allow** — manifest `permissions` expands via `PERMISSION_GROUPS` in `gate.py` (groups and literal tool names).
2. **Deny** — manifest `deny_tools` is an overlay that wins over allows (defense in depth).
3. **Scope** — manifest `store_scope` confines SOIL collections (`prefix*` wildcards).
4. **Orchestrator writes** — `dispatch_send`, `verify_handoff`, `agent_clear`, `frank_append`, `envelope_apply` for `app_id=willow` additionally require `WILLOW_HUMAN_ORCHESTRATOR=1` (stdio) or OAuth binding (serve). (See `ORCHESTRATOR_WRITE_TOOLS` in `human_session.py`.)
5. **Egress** — `task_net` is never implied by `task_queue` or `full_access`; must be explicit on the manifest line.

**Compile:** edit registry → `willow-mcp compile-agents` (or `willow-mcp-init` on first scaffold).

---

@phase 2-permission-groups-reference
## 2. Permission groups (reference)

| Group | Tools (summary) |
|-------|-----------------|
| `store_read` | store_get, store_search, store_list, store_search_all, store_collections, store_stats |
| `store_write` | store_put, store_update, store_delete, store_purge_collection |
| `knowledge_read` | knowledge_search, kb_at, kb_startup_continuity |
| `knowledge_write` | knowledge_ingest, kb_ingest, kb_journal, kb_promote |
| `task_queue` | task_submit, task_status, task_list |
| `dispatch_read` | dispatch_read, dispatch_list, handoff_read, session_read, session_enter |
| `dispatch_write` | dispatch_send, dispatch_accept, handoff_write_v4, verify_handoff, agent_clear, session_handoff_write |
| `orchestrator` | Desk + dispatch + context + fleet read + limited store/kb read |
| `fleet_read` | fleet_status, fleet_health |
| `context` | context_save, context_get, context_list, context_expire |
| `gap_write` | gap_log, gap_resolve, gap_delete |
| `gap_purge` | gap_purge_topic (bulk, fleet-shared — its own opt-in line) |
| `schema_admin` | schema_confirm_mapping |
| `audit` | receipts_tail |
| `whoami` | *(ungated — like `diagnostic_summary`, always answers about your own manifest)* |
| `full_access` | Broad, but **not** everything. Excludes the own-line / egress groups — `integration_call`, `web_read` (`willow_web_search`/`willow_web_fetch`), and `fork_read`/`fork_write` — plus `frank_append`; the `task_net`/`integration_net`/`web_net` capability keys are never implied by any group. Includes the store/gap/specialist reads and the purge tools |

`diagnostic_summary` is intentionally **ungated** (self-check must work when manifest is broken).

---

@phase 3-specialist-matrix
## 3. Specialist matrix

| Name | permissions | deny_tools | store_scope | Rationale |
|------|-------------|------------|-------------|-----------|
| **hanuman** | dispatch_read, dispatch_write, task_queue, store_read, knowledge_read, fork_read, fork_write | kb_promote, knowledge_ingest | hanuman_* | Builder runs Kart; reads KB; tracks work units via fork_*; no ratification writes |
| **loki** | dispatch_read, dispatch_write, knowledge_read | task_submit, store_put, store_update, store_delete, knowledge_ingest | loki_* | Auditor reviews and closes; never builds or mutates store/KB |
| **jeles** | dispatch_read, dispatch_write, knowledge_read | task_submit, kb_promote, kb_journal, knowledge_ingest | jeles_* | Librarian retrieves; no shell, no KB writes |
| **ada** | dispatch_read, dispatch_write, fleet_read, knowledge_read | task_submit, store_put, store_update, knowledge_ingest | ada_* | Operator monitors fleet; no execution or store mutation |
| **skirnir** | dispatch_read, context | — | skirnir_* | Witness reads packets + session context only |
| **vishwakarma** | dispatch_read, store_read, knowledge_read | task_submit | vishwakarma_* | Architect reads; no Kart |

---

@phase 4-orchestrator-seat-willow
## 4. Orchestrator seat (willow)

| Field | Value |
|-------|-------|
| permissions | orchestrator, commitment_read, store_read, knowledge_read |
| deny_tools | — |
| store_scope | willow_*, projects_* |
| human_only | true |
| entry_mode | human_orchestrator |

Agents cannot `session_enter(willow, dispatch_id=…)`. Write tools require human host attestation.

---

@phase 5-change-control
## 5. Change control

1. Edit `bundle/config/specialists.json` (wheel) or `$WILLOW_HOME/config/specialists.json` (operator overlay).
2. Run `willow-mcp compile-agents` (`--force` to overwrite existing manifests).
3. Future: operator PGP signature on registry blob before compile (see `pgp-and-persona.md`).

---

*Ratified by operator authorization 2026-07-09. Replaces TBD placeholders in specialist-registry §4.*
