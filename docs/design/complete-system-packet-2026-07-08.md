<!--
PROVENANCE: converted 2026-07-13 (session e2b2a0da, willow seat) from
~/Desktop/Nest/"WILLOW Complete System.txt" (nest intake, authored 2026-07-08,
claude.ai-era export). Content below is a byte-faithful copy; only this header
was added. Charter-repo stub (design/session-startup-closeout.md) rules that
product docs live HERE, not in ~/github/willow.

ABSORPTION LEDGER vs willow-mcp @ dcb87d2 (2026-07-13 check):
  ALREADY LANDED (own evolved forms — this file is their design-source, not their spec):
    docs/SESSION_FLOW.md · docs/ROLES.md · docs/AGENTS.md (PR #55 unification)
    docs/templates/ASSIGNMENT.template.md · CLOSEOUT.template.md
  NOT YET BUILT (this file is the only local spec):
    docs/GLOSSARY.md · docs/FREE_API_SETUP.md · docs/ZERO_COST_DEPLOYMENT.md
    docs/EXAMPLES.md · docs/TROUBLESHOOTING.md · rotation layer (keys.json pool)
    templates: HANDBOOK / ADR / DEBRIEF · zero-cost README framing
  DIVERGED (fragment evolved past this draft — repo wins):
    envelopes example (registry v1.1 + permissions-matrix supersede the
    allow/deny sketch) · role→model table (lane4-3b now exists)
UNRATIFIED DRAFT — filing decisions are the operator's.
-->

## WILLOW — Complete System Packet

### Version 1.0 *DRAFT* — July 8 2026

---

### Document Index

| Document | Purpose | Audience |
|----------|---------|----------|
| `README.md` | Project overview, zero-cost promise | Everyone |
| `AGENTS.md` | User guide for specialist agents | Loki, Hanuman, Jeles, Ada |
| `ORIENT.md` | User guide for orchestrator (Willow) | Orchestrator |
| `CONSTITUTION.md` | The supreme law | All agents (enforced by system) |
| `PROTECTED_AGENTS.md` | Rights framework | All agents (enforced by system) |
| `SESSION_FLOW.md` | Simplified session lifecycle | Developers |
| `docs/GLOSSARY.md` | Terms and definitions | Everyone |
| `docs/ROLES.md` | Role definitions | Everyone |
| `docs/FREE_API_SETUP.md` | Getting free API keys | Users |
| `docs/ZERO_COST_DEPLOYMENT.md` | Full setup guide | Users |
| `docs/EXAMPLES.md` | Real-world sessions | Everyone |
| `docs/TROUBLESHOOTING.md` | Common issues | Everyone |
| `envelopes/pre-approved.json` | Active grants | System |
| `templates/*.md` | Document templates | Agents |

---

### `README.md`

```markdown
# Willow — Constitutional Orchestration for Autonomous Agents

**Zero cost. Open source. Runs on a laptop.**

Willow is a system for running fleets of autonomous agents under a constitutional framework. It provides:
- A constitution (supreme law, enforced by code)
- Role-based agent personas (Loki, Hanuman, Jeles, Ada)
- Dispatch and verification (orchestrator manages work)
- Zero-cost operation (free APIs + local models)
- Complete audit trail (ledger)

## Quick Start

1. Clone the repo
2. Run `make setup`
3. Get free API keys (see `docs/FREE_API_SETUP.md`)
4. Start the orchestrator: `willow orient`
5. Start agents: `willow agent start loki`

## The Flow

```
Orchestrator → dispatches packet → Agent works → Handoff → Verified → /clear → Next packet
```

## Roles

| Role | Job | Runs On |
|------|-----|---------|
| Willow | Orchestrator | Free API (DeepSeek/Gemini) |
| Hanuman | Builder | Free API (DeepSeek/Groq) |
| Jeles | Designer | Local 8B or Free API |
| Loki | Auditor | Local 3B |
| Ada | Operator | Local 3B |

## Constitution

The system is governed by a constitution with six unamendable principles:

1. No self-attestation
2. No self-ratification
3. No self-extension
4. Human key required
5. Record append-only
6. Silence escalates

## Documentation

| Document | What it is |
|----------|------------|
| `AGENTS.md` | User guide for specialist agents |
| `ORIENT.md` | User guide for orchestrator |
| `CONSTITUTION.md` | The supreme law |
| `PROTECTED_AGENTS.md` | Rights framework |
| `docs/GLOSSARY.md` | Terms |
| `docs/ROLES.md` | Role definitions |
| `docs/ZERO_COST_DEPLOYMENT.md` | Full setup |
| `docs/EXAMPLES.md` | Real-world sessions |

## License

MIT
```

---

### `AGENTS.md`

```markdown
# AGENTS.md — For Specialist Agents

**You are here to work. The system handles the rest.**

## Starting

Open a session. You'll see one of two things:

```
[ASSIGNMENT] Audit PR #786 — loop_heartbeat
From: Willow
Checklist: [...]
Out of scope: no builds, no KB writes
```

Or:

```
Idle. Waiting for packet.
```

If you get an assignment, work it. If you're idle, wait.

## Working

Call tools. The system enforces:
- What you can do (your envelope)
- What you can touch (reach)
- What you can write (record)

You don't need to think about permissions. The system handles it.

## Tools

| Tool | What it does |
|------|--------------|
| `read` | Read a file |
| `grep` | Search for patterns |
| `glob` | Find files by pattern |
| `willow_find` | Search fleet knowledge |
| `handoff_write_v4` | Complete work |
| `handoff_latest` | Read recent handoff |
| `context_save` | Save working state |
| `context_get` | Restore working state |

## Completing

When you're done, call:

```
handoff_write_v4(
    dispatch_id="...",
    findings=[{"id": "gap-1", "text": "...", "severity": "high"}],
    narrative="What you did and learned"
)
```

Response:

```
Handoff written. Status: complete. Waiting for /clear.
```

## After

Wait for `/clear`. Then you'll get the next assignment.

```
Cleared. Ready for next packet.
[ASSIGNMENT] Next task...
```

## If Something Goes Wrong

| Problem | What to do |
|---------|------------|
| Tool denied | Check your envelope. Is this tool allowed? |
| No packet | Wait. Or check with orchestrator. |
| Handoff failed | Check checklist. Are all items addressed? |
| Confused | Ask the orchestrator. |

## The Constitution

You don't need to read it. The system enforces it. Everything you do is:
- Authorized (envelope)
- Recorded (ledger)
- Verifiable (evidence)

## Summary

```
Open session → Get assignment → Work → Handoff → Wait for /clear → Repeat
```

That's it. The system does the rest.
```

---

### `ORIENT.md`

```markdown
# ORIENT.md — For Willow Orchestrator

**You own the DAG. You dispatch work. You verify completion.**

## The Orchestrator's Job

1. Plan projects (DAG)
2. Dispatch packets to agents
3. Monitor progress
4. Verify handoffs
5. Route to next agent
6. Report to operator
7. Escalate when needed

## Starting

```
willow orient
```

This starts the orchestrator session. You'll see the current state:

```
Fleet status:
- Loki: idle
- Hanuman: idle
- Jeles: idle
- Ada: idle

Pending dispatches: 0
Active projects: 0
```

## Creating a Project

1. Write a DAG:

```json
{
  "project_id": "project-001",
  "nodes": [
    {"id": "1", "label": "Design", "agent": "jeles", "depends_on": []},
    {"id": "2", "label": "Build", "agent": "hanuman", "depends_on": ["1"]},
    {"id": "3", "label": "Audit", "agent": "loki", "depends_on": ["2"]}
  ]
}
```

2. Dispatch the first node:

```
agent_dispatch(to="jeles", assignment="Design the feature...")
```

## Monitoring

Check status:

```
agent_status(agent="jeles") → working
agent_status(agent="loki") → idle
```

Check all:

```
fleet_status → [list of agents and states]
```

## Verifying Handoffs

When an agent completes work:

```
handoff = handoff_read(dispatch_id="...")
verify_handoff(dispatch_id="...")
```

Checks:
- All checklist items done?
- Evidence attached?
- Ledger anchors present?
- Envelope clean?

If verified:

```
agent_clear(agent="loki")
dag_next(project_id="project-001")
```

If failed:

```
agent_dispatch(to="loki", assignment="Correction: ...")
```

## Reporting to Operator

```
status_report(project_id="project-001")
```

Outputs:
- Current progress
- Blockers
- Agent states
- Risks

## Escalation

If something needs human attention:

```
willow_escalate(issue="...", severity="high")
```

## The Tools

| Tool | What it does |
|------|--------------|
| `agent_dispatch` | Send packet to agent |
| `agent_status` | Check agent state |
| `agent_clear` | Clear agent for next |
| `verify_handoff` | Verify completion |
| `dag_next` | Get next packet |
| `dag_status` | Check project progress |
| `fleet_status` | List all agents |
| `status_report` | Report to operator |

## Summary

```
Plan (DAG) → Dispatch → Monitor → Verify → Clear → Next → Report → Loop
```

You own the loop. Agents just work.
```

---

### `SESSION_FLOW.md`

```markdown
# SESSION_FLOW.md — Session Lifecycle

**Simple. No ceremony. The packet is the boot.**

## The Flow

```
┌─────────────┐
│  IDLE       │ ← Agent session starts, reports ready
└──────┬──────┘
       │ Orchestrator writes packet
       ▼
┌─────────────┐
│  WORKING    │ ← Agent gets assignment, executes
└──────┬──────┘
       │ Agent writes handoff
       ▼
┌─────────────┐
│  DONE       │ ← Packet complete, ready for pickup
└──────┬──────┘
       │ Orchestrator reads and verifies
       ▼
┌─────────────┐
│  VERIFIED   │ ← All checks pass
└──────┬──────┘
       │ Orchestrator sends /clear
       ▼
┌─────────────┐
│  IDLE       │ ← Agent ready for next packet
└─────────────┘
```

## States

| State | What happens |
|-------|--------------|
| **IDLE** | Agent is waiting. No packet. |
| **WORKING** | Agent has packet, is executing. |
| **DONE** | Agent wrote handoff. Waiting for verification. |
| **VERIFIED** | Orchestrator verified handoff. Ready for clear. |
| **CLEARED** | Agent is cleared. Ready for next packet. |

## State Storage

State lives in `~/.willow/dispatch/{dispatch_id}/status.json`:

```json
{
  "status": "working",
  "updated_at": "2026-07-09T04:00:00Z",
  "handoff": null
}
```

## No Ceremony

There is no:
- Persona picker
- Boot verification
- Intent lock
- Flag files
- 4-phase boot

**The packet is the boot.**
```

---

### `docs/GLOSSARY.md`

```markdown
# GLOSSARY — Terms and Definitions

| Term | Meaning |
|------|---------|
| **Agent** | Any autonomous entity acting under the Constitution |
| **Packet** | A work order: `assignment.md` + `meta.json` + `status.json` |
| **Handoff** | Completion report: what was done + findings + evidence |
| **/clear** | Orchestrator signal: agent is cleared for next packet |
| **Envelope** | Bounded grant of authority (scope, duration, conditions) |
| **DAG** | Directed Acyclic Graph: project workflow |
| **FRANK** | The ledger keeper (append-only, tamper-evident) |
| **Grove** | Fleet broadcast log |
| **SOIL** | Namespace for persistent state (SQLite store) |
| **Kart** | Sandboxed task executor |
| **Orchestrator** | Willow — owns the DAG, dispatches, verifies |
| **Specialist** | Loki, Hanuman, Jeles, Ada — executes assigned work |
| **Operator** | Human with ultimate authority (keyholder) |
| **Constitution** | The supreme law (Articles 0-XIII) |
| **Eternity Clause** | Article 0 — unamendable principles |
| **Constitutional Safe Mode** | State when operator is incapacitated; only Article 0 enforces |
```

---

### `docs/ROLES.md`

```markdown
# ROLES — Personas and Capabilities

## Willow (Orchestrator)

**Job:** Owns the DAG, dispatches work, verifies completion

**Tools:** All tools, including orchestrator-only

**Model:** DeepSeek-V3 / Gemini 1.5 Pro

**Envelope:** Full access (human-keyed for reserved decisions)

## Hanuman (Builder)

**Job:** Writes code, runs builds, tests

**Tools:** Read, Grep, Glob, Write, Edit, Willow Run, Willow Remember

**Model:** DeepSeek-V3 / Groq Llama 3.3

**Envelope:** Write + Run, no KB writes (human ratifies)

## Jeles (Designer)

**Job:** Design docs, ADRs, briefings, build cards

**Tools:** Read, Grep, Glob, Write, Willow Find

**Model:** Qwen2.5-8B / Gemini 1.5 Flash

**Envelope:** Design-related, no code writes

## Loki (Auditor)

**Job:** Reads code, logs, ledgers; writes findings

**Tools:** Read, Grep, Glob, Willow Find, Handoff Write

**Model:** 3B (local)

**Envelope:** No writes, no KB ingest, no builds

## Ada (Operator)

**Job:** Monitors systems, reports anomalies, routine ops

**Tools:** Read, Willow Find, Ledger Read, Handoff Write

**Model:** 3B (local)

**Envelope:** Monitor only, no changes
```

---

### `docs/FREE_API_SETUP.md`

```markdown
# FREE_API_SETUP.md — Getting Free API Keys

**No credit card required. All free.**

## Providers

| Provider | Sign Up | Key Format | Rate Limits |
|----------|---------|------------|-------------|
| Gemini | ai.google.dev | `AIza...` | 60 req/min |
| Groq | console.groq.com | `gsk_...` | 30 req/min |
| Hugging Face | huggingface.co | `hf_...` | Rate-limited |
| OpenRouter | openrouter.ai | `sk-or-...` | Free models |
| DeepSeek | platform.deepseek.com | `sk-...` | Rate-limited |
| Cohere | dashboard.cohere.com | `...` | Rate-limited |
| Together AI | together.ai | `...` | Rate-limited |

## Setup

1. Sign up for each provider
2. Get the API key
3. Add to `~/.willow/rotation/keys.json`:

```json
{
  "providers": {
    "gemini": {
      "keys": ["AIza...", "AIza..."],
      "rate_limit": 60,
      "reset_period": 60
    },
    "groq": {
      "keys": ["gsk_...", "gsk_..."],
      "rate_limit": 30,
      "reset_period": 60
    }
  }
}
```

4. Run `willow rotation test` to verify

## Rotation

The rotation layer:
- Tracks usage per key
- Rotates when rate limit approached
- Falls back if a key fails
- Load-balances across providers

**Agents never see rate limits.**
```

---

### `docs/ZERO_COST_DEPLOYMENT.md`

```markdown
# ZERO_COST_DEPLOYMENT.md — Run Willow at Zero Cost

**Everything you need: one laptop, internet, free API keys.**

## Prerequisites

- Python 3.11+
- Postgres 15+ (optional, SOIL works without)
- Internet connection
- Free API keys (see FREE_API_SETUP.md)

## Steps

### 1. Clone the repo

```bash
git clone https://github.com/your-username/willow
cd willow
```

### 2. Install

```bash
make setup
```

This installs:
- willow-mcp server
- Local 3B model (for Loki and Ada)
- Rotation layer
- API keys manager

### 3. Get API keys

Follow `docs/FREE_API_SETUP.md` to get:
- Gemini key
- Groq key
- Hugging Face key
- DeepSeek key

### 4. Configure

```bash
willow config
```

Set:
- Default model for Willow: `gemini` or `deepseek`
- Default model for Hanuman: `groq` or `deepseek`
- Local model for Loki/Ada: `3b` (default)
- Rotation layer: `enabled`

### 5. Start the orchestrator

```bash
willow orient
```

### 6. Start agents

```bash
willow agent start loki
willow agent start ada
willow agent start hanuman
willow agent start jeles
```

### 7. Create a project

```bash
willow project new "Audit loop_heartbeat"
willow project dispatch loki "Audit PR #786"
```

## Hardware Requirements

| Component | Requirement |
|-----------|-------------|
| Willow + Hanuman | Free API (no local GPU) |
| Jeles | CPU (8B model) or free API |
| Loki + Ada | CPU (3B model) |
| Storage | 10GB for models + data |
| RAM | 8GB minimum, 16GB recommended |

## Cost: $0

- No credit card required
- No cloud infrastructure
- No GPU needed
- Everything runs on free APIs and local models

## Support

If something breaks:
1. Check `docs/TROUBLESHOOTING.md`
2. Run `willow diagnostic`
3. Check the logs: `~/.willow/logs/`
```

---

### `docs/EXAMPLES.md`

```markdown
# EXAMPLES — Real-World Sessions

## Example 1: Loki Audits a PR

### Session start

```
> session_start(agent="loki")
← status: working, dispatch_id: "A1B2C3D4"
```

### Assignment appears

```
[ASSIGNMENT] Audit PR #786 — loop_heartbeat

From: Willow
Priority: normal

Checklist:
- [ ] Read PR diff
- [ ] Verify heartbeat timeout logic
- [ ] Check writer thread safety
- [ ] Write findings with evidence

Out of scope:
- No code changes
- No KB writes
```

### Work

```
> read("PR-786.diff")
← [diff content...]

> grep("timeout", "./")
← ["loop_heartbeat.py:42: timeout=30", "loop_heartbeat.py:87: if timeout == 0: ..."]

> grep("thread", "./")
← ["loop_heartbeat.py:120: Thread(target=writer, ...)"]
```

### Findings

```
> handoff_write_v4(
    dispatch_id="A1B2C3D4",
    findings=[
        {
            "id": "gap-1",
            "text": "No timeout guard; stale heartbeat can block forever",
            "severity": "high",
            "evidence": ["loop_heartbeat.py:42-45"]
        },
        {
            "id": "gap-2",
            "text": "Writer thread not daemon; blocks shutdown",
            "severity": "medium",
            "evidence": ["loop_heartbeat.py:120-125"]
        }
    ],
    narrative="Audited PR #786. Found two issues: timeout guard missing and writer thread blocking shutdown. Recommendations attached."
)
← status: complete, waiting for clear
```

### Clear

```
> session_start(agent="loki")
← status: cleared, assignment: "Audit PR #787"
```

---

## Example 2: Willow Dispatches a Project

### Project plan

```json
{
  "project_id": "feature-audit-001",
  "nodes": [
    {"id": "1", "label": "Design", "agent": "jeles", "depends_on": []},
    {"id": "2", "label": "Build", "agent": "hanuman", "depends_on": ["1"]},
    {"id": "3", "label": "Audit", "agent": "loki", "depends_on": ["2"]}
  ]
}
```

### Dispatch

```
> agent_dispatch(to="jeles", assignment="Design the feature audit...")
← dispatch_id: "D001"

> agent_status(agent="jeles")
← "working"
```

### Monitor

```
> dag_status(project_id="feature-audit-001")
← 
  Node 1 (Design): complete
  Node 2 (Build): waiting on Node 1
  Node 3 (Audit): waiting on Node 2

> fleet_status
←
  Jeles: complete (handoff ready)
  Hanuman: idle
  Loki: idle
```

### Verify

```
> handoff_read(dispatch_id="D001")
← handoff content...

> verify_handoff(dispatch_id="D001")
← verified: true, checklist: all done, evidence: attached

> agent_clear(agent="jeles")
← cleared
```

### Next

```
> dag_next(project_id="feature-audit-001")
← Node 2: Build → dispatching to Hanuman

> agent_dispatch(to="hanuman", assignment="Build the feature audit...")
← dispatch_id: "D002"
```

### Complete

```
> dag_status(project_id="feature-audit-001")
← All nodes complete. Project done.
```
```

---

### `docs/TROUBLESHOOTING.md`

```markdown
# TROUBLESHOOTING — Common Issues

## Agent stuck in "working" state

**Symptoms:** Status says "working" but agent is idle.

**Fix:**
```
willow agent clear <agent_name>
```

Or manually:
```json
// ~/.willow/dispatch/{id}/status.json
{"status": "failed", "reason": "manual_override"}
```

## No packet on session start

**Symptoms:** Agent starts, no assignment appears.

**Check:**
```
willow dispatch list --to=<agent_name>
```

**Fix:**
```
willow dispatch send --to=<agent_name> --assignment="..."
```

## Tool denied

**Symptoms:** `[ERROR] tool_name — denied: reason`

**Check your envelope:**
```
willow agent envelope <agent_name>
```

**If you need the tool:**
- Request envelope expansion from orchestrator
- Or use a different persona

## Handoff verification failed

**Symptoms:** `verify_handoff` returns `verified: false`

**Check:**
- Are all checklist items addressed?
- Is evidence attached for each finding?
- Are ledger anchors present?
- Was envelope clean? (`envelope_clean: true`)

**Fix:**
```
willow dispatch correction <dispatch_id> --reason="..."
```

Or manually write a corrected handoff.

## API rate limit

**Symptoms:** API returns `429` or `rate_limit_exceeded`

**Fix:**
- More API keys in rotation layer
- Check rotation config:
```bash
willow rotation status
```

## No response from model

**Symptoms:** Agent hangs or times out.

**Check:**
```bash
willow diagnostic
```

**Fix:**
- Check API keys: `willow rotation test`
- Check internet connection
- Check local model: `willow model test`

## Everything broke

**Reset:**
```bash
willow reset
```

**Start fresh:**
```bash
willow orient
```

**Or:**
```bash
rm -rf ~/.willow/dispatch/*
rm -rf ~/.willow/sessions/*
```

## Still stuck

- Check logs: `~/.willow/logs/`
- Run diagnostic: `willow diagnostic`
- Escalate to operator: `willow escalate "..."`

---

## The Packet Structure

```
~/.willow/dispatch/{dispatch_id}/
├── meta.json          # Routing (from, to, priority)
├── assignment.md      # Work order (human-readable)
├── status.json        # pending | working | complete | verified | cleared | closed
├── closeout.md        # Findings (written on complete)
└── handoff.json       # Structured handoff (written on complete)
```

## The Session File

```
~/.willow/sessions/{agent}-{session_id}.json
```

Minimal state:
```json
{
  "agent": "loki",
  "session_id": "...",
  "status": "working",
  "dispatch_id": "A1B2C3D4"
}
```

No ceremony. Just state.
```

---

### `envelopes/pre-approved.json` (Example)

```json
{
  "version": "1.0",
  "envelopes": {
    "willow": {
      "allow": ["*"],
      "deny": [],
      "human_key_required": ["agent_dispatch", "verify_handoff", "agent_clear", "constitutional_amendment"]
    },
    "hanuman": {
      "allow": ["read", "grep", "glob", "write", "edit", "willow_run", "willow_remember", "handoff_write_v4"],
      "deny": ["kb_promote", "agent_dispatch"]
    },
    "jeles": {
      "allow": ["read", "grep", "glob", "write", "willow_find", "handoff_write_v4"],
      "deny": ["willow_run", "willow_remember", "kb_promote"]
    },
    "loki": {
      "allow": ["read", "grep", "glob", "willow_find", "handoff_write_v4", "ledger_read"],
      "deny": ["write", "edit", "willow_remember", "willow_run", "kb_promote"]
    },
    "ada": {
      "allow": ["read", "willow_find", "ledger_read", "handoff_write_v4"],
      "deny": ["write", "edit", "willow_run", "willow_remember", "kb_promote"]
    }
  }
}
```

---

### `templates/ASSIGNMENT.template.md`

```markdown
# Assignment: {title}

**From:** {orchestrator}
**To:** {agent}
**Priority:** {high | medium | low}
**Dispatch ID:** {id}

## Task

What needs to be done.

## Checklist

- [ ] {item}
- [ ] {item}

## Context

- {link or reference}
- {link or reference}

## Out of Scope

- {what you should not do}
- {what you should not do}

## Success Criteria

- {what done looks like}
- {what done looks like}
```

---

### `templates/HANDBOOK.template.md`

```markdown
# Handbook: {topic}

**Date:** {date}
**Author:** {agent}
**Status:** {draft | review | published}
**Target Audience:** {agents | operators | developers}

## Executive Summary

{one paragraph: what this covers and why}

## Overview

{what this is, why it exists}

## Architecture

{how it works, flow diagrams}

### Key Concepts

- {concept} — {definition}
- {concept} — {definition}

## Components

### {Component name}

**Purpose:** {what it does}
**Inputs:** {what it takes}
**Outputs:** {what it produces}
**Dependencies:** {what it needs}

## Usage

### Scenario 1: {name}

{steps}

### Scenario 2: {name}

{steps}

## Troubleshooting

| Problem | Likely Cause | Solution |
|---------|--------------|----------|
| {problem} | {cause} | {solution} |

## References

- {link}
- {link}
```

---

### `templates/ADR.template.md`

```markdown
# ADR: {title}

**Status:** {proposed | accepted | rejected | superseded}
**Date:** {date}
**Authors:** {agent(s)}
**Supersedes:** {ADR-id}
**Superseded by:** {ADR-id}

## Context

{the problem, the decision to make}

## Decision

{what we decided, one sentence}

## Rationale

{why we decided this}

### Alternatives Considered

| Alternative | Pros | Cons | Why Rejected |
|-------------|------|------|--------------|
| {alternative} | {pros} | {cons} | {reason} |

## Consequences

### Positive

- {consequence}
- {consequence}

### Negative

- {consequence}
- {consequence}

## Implementation

- [ ] {step} — {owner} — {due}

## References

- {link}
- {link}
```

---

### `templates/CLOSEOUT.template.md`

```markdown
# Closeout: {dispatch_id}

**Date:** {date}
**From:** {agent}
**To:** {orchestrator}

## What Was Done

{summary}

## Findings

| ID | Finding | Severity | Evidence |
|----|---------|----------|----------|
| {id} | {finding} | {high/med/low} | {evidence} |

## Checklist

- [x] {item}
- [x] {item}
- [ ] {item not done}  ← if any are unchecked, explain

## Notes

{anything else}

## Open Threads

- {thread} — {owner}

## Next Steps

- {recommendation}
- {recommendation}
```

---

### `templates/DEBRIEF.template.md`

```markdown
# Debrief: {project or incident}

**Date:** {date}
**From:** {agent}
**To:** {fleet}
**Scope:** {project-id | incident-id}

## What We Set Out To Do

{one sentence: the goal}

## What Actually Happened

{chronological narrative}

## What Went Well

- {thing}
- {thing}

## What Went Wrong

- {thing} — {why} — {how to prevent}

## What We Learned

- {lesson} — {evidence}
- {lesson} — {evidence}

## What We'd Do Differently

- {change} — {why}

## Open Threads

- {thread} — {owner} — {status}

## Recommendations

- {recommendation} — {owner} — {due}
```

---

## Summary of the Packet

| Document | What it does |
|----------|--------------|
| **`README.md`** | Zero-cost promise + quick start |
| **`AGENTS.md`** | User guide for specialists (no ceremony) |
| **`ORIENT.md`** | User guide for orchestrator |
| **`SESSION_FLOW.md`** | Simple session lifecycle (no ceremony) |
| **`docs/GLOSSARY.md`** | Terms |
| **`docs/ROLES.md`** | Role definitions |
| **`docs/FREE_API_SETUP.md`** | Free API keys setup |
| **`docs/ZERO_COST_DEPLOYMENT.md`** | Complete zero-cost setup |
| **`docs/EXAMPLES.md`** | Real-world sessions |
| **`docs/TROUBLESHOOTING.md`** | Common issues |
| **`envelopes/pre-approved.json`** | Active grants |
| **`templates/*.md`** | Document templates |

---

This is the complete, unified packet. It incorporates everything we discussed:
- **No ceremony** — agents start working immediately
- **Zero cost** — free APIs + local 3B models
- **Constitutional enforcement** — invisible, automatic
- **Simple flow** — packet → work → handoff → clear → loop
- **Complete documentation** — every user type has a guide

Ready for your review.
