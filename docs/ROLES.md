# Fleet roles — specialist registry (user view)

*Machine source: `docs/design/specialist-registry.md` · seed: `bundle/config/specialists.json`*

> **Permissions not live yet.** The Tool use column lists intended gate groups. Runtime still uses hand-edited manifests and `roles.py` until registry compilation and `deny_tools` enforcement land.

## Specialists

| Function | Name | Roles | Tool use (intended) | Persona file |
|----------|------|-------|---------------------|--------------|
| BUILD | Hanuman | builder, coordinator | dispatch_write, task_queue, store_read, knowledge_read | `personas/hanuman.md` |
| AUDIT | Loki | auditor | dispatch_read, dispatch_write, knowledge_read | `personas/loki.md` |
| RESEARCH | Jeles | librarian, retrieval | dispatch_read, dispatch_write, knowledge_read | `personas/jeles.md` |
| OPERATE | Ada | operator, monitor | dispatch_read, dispatch_write, fleet_read, knowledge_read | `personas/ada.md` |
| EMISSARY | Skirnir | gate, witness | dispatch_read, context *(TBD)* | `personas/skirnir.md` |
| ARCHITECT | Vishwakarma | architect, safe | dispatch_read, store_read, knowledge_read *(TBD)* | `personas/vishwakarma.md` |

### Deny highlights

| Name | Must not |
|------|----------|
| Hanuman | kb_promote, knowledge_ingest, direct master commits |
| Loki | task_submit, store writes, knowledge_ingest |
| Jeles | task_submit, kb_promote — **not** a designer |
| Ada | task_submit, store writes, unsolicited changes |

## Orchestrator seat (not dispatched)

| Function | Name | Roles | Tool use (intended) | Persona |
|----------|------|-------|---------------------|---------|
| ORCHESTRATE | Willow | orchestrator, magistrate | orchestrator *(human + PGP gated)* | Charter picker only |

See `human-orchestrator.md` — agents cannot run this seat.

## Dispatch routing

- Route by **Function** in DAG → default **Name**.
- Address packets by **Name** (`to_app`).
- Persona voice loads silently from persona file on dispatch entry — no picker.
