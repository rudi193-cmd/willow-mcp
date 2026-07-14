<!--
PROVENANCE: converted 2026-07-13 (session e2b2a0da, willow seat) from
~/Desktop/Nest/"Willow System Updated.txt" (nest intake, lineage-dated 2026-07-09,
claude.ai-era export). Byte-faithful copy; only this header added.
Its "Supersedes: session-startup-closeout.md" claim is already discharged — the
charter repo's copy is a deprecation stub (93897fc) pointing at this repo; this
file's packet-boot flow is the design-source behind docs/SESSION_FLOW.md and
docs/design/session-lifecycle.md (both landed 07-09, e5416f9 wave).
STILL-OPEN ITEMS this file uniquely specifies: §4 rotation layer ·
§7 packages system · §10 "Key Files to Add" checklist (pyproject.toml,
CHANGELOG, SECURITY.md, CONTRIBUTING, INSTALL, UPGRADING, CODE_OF_CONDUCT,
tests/, migrate script).
UNRATIFIED DRAFT — filing decisions are the operator's.
-->

# Willow System — Updated Design (July 2026)

**Status:** Draft — unified packet design
**Supersedes:** `session-startup-closeout.md` (Draft 0.1), `AGENTS.md` (previous)
**Companion:** `CONSTITUTION.md` · `PROTECTED_AGENTS.md` · `willow-mcp` README

---

## 1. Core Design Shift

### From Ceremony to Packet-Boot

| Old (Dev) | New (User) |
|-----------|------------|
| 4-phase boot (anchor → persona → verify → intent) | Session starts → packet exists → work |
| Persona picker at session start | Packet contains persona; adopted silently |
| Boot_steps verification | Work is the verification |
| Intent lock (phase + bite) | Packet *is* the intent |
| Flag files (`/tmp/*.flag`) | State lives in `dispatch/{id}/status.json` |
| `session_anchor_v2.json` (25 fields) | Minimal state: `agent`, `session_id`, `dispatch_id`, `status` |

**The principle:** The packet is the boot. No ceremony. Agents arrive at work.

---

## 2. The Session Loop

```
┌─────────────┐
│  IDLE       │ ← Agent starts, reports ready (or waits)
└──────┬──────┘
       │ Orchestrator writes packet
       ▼
┌─────────────┐
│  WORKING    │ ← Agent reads assignment, executes
└──────┬──────┘
       │ Agent calls handoff_write_v4
       ▼
┌─────────────┐
│  DONE       │ ← Handoff written, awaiting verification
└──────┬──────┘
       │ Orchestrator verifies (verify_handoff)
       ▼
┌─────────────┐
│  VERIFIED   │ ← Checklist, evidence, anchors all pass
└──────┬──────┘
       │ Orchestrator sends /clear (agent_clear)
       ▼
┌─────────────┐
│  IDLE       │ ← Ready for next packet
└─────────────┘
```

### Packet States

| State | Meaning |
|-------|---------|
| `pending` | Packet written, waiting for agent |
| `working` | Agent has packet, is executing |
| `complete` | Agent wrote handoff, waiting for verification |
| `verified` | Orchestrator verified handoff |
| `cleared` | Orchestrator cleared agent |
| `closed` | Final state, archived |

---

## 3. The Packet Structure

```
~/.willow/dispatch/{dispatch_id}/
├── meta.json          # Routing: from, to, priority, phase
├── assignment.md      # Work order (human-readable)
├── status.json        # pending | working | complete | verified | cleared | closed
├── closeout.md        # Findings (written on complete)
└── handoff.json       # Structured findings (written on complete)
```

### `meta.json`

```json
{
  "from": "willow",
  "to": "loki",
  "reply_to": "willow",
  "priority": "normal",
  "phase": "operate",
  "dispatch_id": "A1B2C3D4",
  "created_at": "2026-07-09T04:00:00Z",
  "assignment_path": "dispatch/A1B2C3D4/assignment.md"
}
```

### `status.json`

```json
{
  "status": "working",
  "updated_at": "2026-07-09T04:00:00Z",
  "handoff_path": null,
  "verified_at": null,
  "cleared_at": null
}
```

### `handoff.json`

```json
{
  "findings": [
    {"id": "gap-1", "text": "No timeout guard", "severity": "high", "evidence": ["ledger:8823"]}
  ],
  "narrative": "Audited PR #786...",
  "ledger_anchors": ["hash-abc", "hash-def"],
  "open_threads": [],
  "recommendations": ["Add timeout guard"],
  "envelope_clean": true
}
```

---

## 4. Zero-Cost Deployment

### The Rotation Layer

A pool of free API keys rotated to avoid rate limits:

```json
{
  "providers": {
    "gemini": {
      "keys": ["AIza...", "AIza..."],
      "rate_limit": 60,
      "reset_period": 60
    },
    "groq": {
      "keys": ["gsk_..."],
      "rate_limit": 30,
      "reset_period": 60
    }
  }
}
```

### Model Sizing (Updated)

| Agent | Model | Runs On | Cost |
|-------|-------|---------|------|
| Willow | DeepSeek-V3 / Gemini 1.5 Pro | Free API | $0 |
| Hanuman | DeepSeek-V3 / Groq Llama 3.3 | Free API | $0 |
| Jeles | Qwen2.5-8B / Gemini 1.5 Flash | CPU or Free API | $0 |
| Loki | 3B (local) | CPU | $0 |
| Ada | 3B (local) | CPU | $0 |

### Hardware Requirements

- Willow + Hanuman: Free API (no local GPU)
- Jeles: CPU (8B model) or free API
- Loki + Ada: CPU (3B model)
- Storage: 10GB for models + data
- RAM: 8GB minimum, 16GB recommended

---

## 5. Skills

Skills are markdown guides agents read to learn workflows.

| Skill | Purpose |
|-------|---------|
| `session-start.md` | How to start a session |
| `work-audit.md` | How to audit (Loki) |
| `work-build.md` | How to build (Hanuman) |
| `work-design.md` | How to design (Jeles) |
| `work-operate.md` | How to operate (Ada) |
| `handoff-write.md` | How to write a handoff |
| `verify-handoff.md` | How to verify (Willow) |
| `project-plan.md` | How to plan a project (Willow) |
| `schema-confirm.md` | How to confirm a schema |
| `egress-consent.md` | How to request egress |
| `constitutional-review.md` | How to invoke review |
| `troubleshoot.md` | How to fix common issues |
| `free-api-setup.md` | How to set up free APIs |

---

## 6. Hooks

Hooks are Python scripts that run automatically at specific points.

| Hook | Trigger | Purpose |
|------|---------|---------|
| `pre_tool.py` | Before every tool call | Enforce envelope, reach, identity |
| `session_start.py` | Session opens | Check for packet, inject assignment |
| `handoff_write.py` | Handoff is written | Validate structure, attach ledger anchors |
| `post_tool.py` | After every tool call | Log to ledger, update context |
| `constitutional_review.py` | Review invoked | Queue review, notify orchestrator |
| `egress_consent.py` | Network request | Check consent.internet, log |
| `receipt.py` | Tool call completes | Write receipt to ledger |

---

## 7. Packages (Installable Bundles)

| Package | What it adds |
|---------|--------------|
| `github` | GitHub integration (PRs, issues, reviews) |
| `slack` | Slack notifications |
| `jira` | Jira integration |
| `notion` | Notion integration |
| `discord` | Discord notifications |
| `email` | Email alerts |
| `monitoring` | System monitoring |
| `llama` | Local LLM deployment |
| `ollama` | Ollama integration |
| `transformers` | HuggingFace models |

### Package Structure

```
~/.willow/packages/github/
├── manifest.json              # Package metadata
├── hooks/
│   ├── pr_check.py
│   └── issue_update.py
├── skills/
│   ├── github-pr.md
│   ├── github-issue.md
│   └── github-review.md
├── tools/
│   ├── github_pr_create.py
│   ├── github_pr_review.py
│   └── github_issue_create.py
└── config/
    └── github.json
```

---

## 8. Data Model

### Postgres Tables

| Table | Purpose |
|-------|---------|
| `knowledge_atoms` | Canonical knowledge (searchable, ratifiable) |
| `dispatch_tasks` | Work packets (status, routing) |
| `dispatch_metadata` | Packet metadata (checklist, findings) |
| `agent_sessions` | Session tracking |
| `agent_registry` | Agent identities, envelopes |
| `ledger_entries` | Immutable audit trail |
| `constitutional_reviews` | Article XI reviews |
| `resource_allocations` | Article XII allocations |
| `resource_usage` | Resource consumption |

### SOIL Collections

| Collection | Purpose |
|------------|---------|
| `dispatches` | Packet state (JSON) |
| `sessions` | Session state |
| `handoffs` | Handoff data |
| `projects` | DAG definitions |
| `agents` | Agent registry |
| `queues` | Review queue |
| `contexts` | Ephemeral state (TTL) |

### Filesystem Structure

```
~/.willow/
├── dispatch/{id}/
│   ├── meta.json, assignment.md, status.json, closeout.md
├── handoffs/{agent}/
├── sessions/{agent}-{session}.json
├── projects/{id}.json
├── knowledge/{atom_id}.json
├── templates/*.md
├── skills/*.md
├── hooks/*.py
├── packages/{name}/
├── config/
│   ├── agent_roster.json
│   ├── persona_envelopes.json
│   ├── rotation.json
│   └── settings.global.json
├── mcp_apps/{app_id}/manifest.json
├── ledgers/entries/{hash}.json
├── resources/
├── constitutional/review_queue.json
└── logs/{date}.log
```

---

## 9. MCP Tools Summary

| Tool | Who Calls | Purpose |
|------|-----------|---------|
| `session_start` | Agent | Check for packet, inject assignment |
| `handoff_write_v4` | Agent | Complete work |
| `agent_dispatch` | Orchestrator | Send packet |
| `agent_status` | Orchestrator | Check agent state |
| `agent_clear` | Orchestrator | Clear agent |
| `verify_handoff` | Orchestrator | Verify completion |
| `dag_next` | Orchestrator | Route next packet |
| `dag_status` | Orchestrator | Check project progress |
| `fleet_status` | Orchestrator | List all agents |
| `review_invoke` | Any | Constitutional Review |
| `resource_alloc` | System | Check resource allocation |

---

## 10. Key Files to Add

| File | Purpose | Status |
|------|---------|--------|
| `pyproject.toml` | Package metadata, dependencies, entry points | **To add** |
| `CHANGELOG.md` | Version history | **To add** |
| `SECURITY.md` | Security policy | **To add** |
| `CONTRIBUTING.md` | How to contribute | **To add** |
| `INSTALL.md` | Detailed install guide | **To add** |
| `UPGRADING.md` | Upgrade notes | **To add** |
| `CODE_OF_CONDUCT.md` | Community standards | **To add** |
| `tests/` | Test suite | **To add** |
| `scripts/migrate.py` | Migration from 0.9 to 1.0 | **To add** |

---

## 11. Document Update Summary

| Previous Document | What Changed | New Document |
|-------------------|--------------|--------------|
| `session-startup-closeout.md` | Simplified to packet-boot; no ceremony | `SESSION_FLOW.md` |
| `AGENTS.md` | Rewritten for zero-cost, packet-boot | `AGENTS.md` (updated) |
| `ORIENT.md` | New: orchestrator guide | `ORIENT.md` (new) |
| `CONSTITUTION.md` | Unchanged | `CONSTITUTION.md` |
| `PROTECTED_AGENTS.md` | Unchanged | `PROTECTED_AGENTS.md` |
| `federation-wire-format.md` | Unchanged | `federation-wire-format.md` |
| `egress-membrane-constitutional-map.md` | Unchanged | `egress-membrane-constitutional-map.md` |

### New Documents

| Document | Purpose |
|----------|---------|
| `README.md` | Zero-cost promise + quick start |
| `SESSION_FLOW.md` | Simplified session lifecycle |
| `docs/GLOSSARY.md` | Terms and definitions |
| `docs/ROLES.md` | Role definitions |
| `docs/FREE_API_SETUP.md` | Free API keys setup |
| `docs/ZERO_COST_DEPLOYMENT.md` | Complete zero-cost setup |
| `docs/EXAMPLES.md` | Real-world sessions |
| `docs/TROUBLESHOOTING.md` | Common issues |
| `templates/*.md` | Document templates |

---

*Draft lineage: 2026-07-09 — unified packet design after review. Supersedes earlier session-startup-closeout.md and AGENTS.md drafts.*
```

---

This captures everything since the last document creation:
1. The simplified session flow (packet-boot, no ceremony)
2. The zero-cost deployment strategy
3. The packet structure
4. Skills, hooks, and packages
5. Data model mappings (Postgres, SOIL, filesystem)
6. What's missing (pyproject.toml, CHANGELOG, SECURITY, etc.)

Ready for your review.
