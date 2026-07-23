---
kind: doc
name: design-hooks-and-skills-ship-alongside-tools-not-after
description: "Design rule for willow-mcp: any new tool surface with a footgun or a multi-step human workflow ships its hook and/or skill in the same PR as the tool — covers the plugin packaging shape, the pre_tool_use.py contract, and the schema-confirm.md skill."
---

@markdownai v1.0

# Design: Hooks and Skills Ship Alongside Tools, Not After

Status: DRAFT — first hook + skill landing with this doc; not yet ratified as
a hard process rule, but intended as one.

@phase 1-problem-statement
## 1. Problem statement

`willow-mcp` ships MCP tools with nothing that teaches an agent — or a human
— how to use them correctly. Two concrete gaps existed before this change:

1. Nothing stops an agent from reaching for raw `psql`/`psycopg2`/`sqlite3`
   against the databases willow-mcp owns (`WILLOW_PG_DB`, `WILLOW_STORE_ROOT`)
   instead of the MCP tools. The fleet this package grew out of solves this
   with a hook; a standalone `pip install willow-mcp` gets none of that
   protection.
2. `schema_confirm_mapping` (docs/design/schema-adaptation.md §3.4) landed as
   a raw tool call with no guided workflow. A new adopter pointing willow-mcp
   at their own database has to hand-write a JSON `overrides` dict against a
   heuristic mapping they've never seen rendered — exactly the audience the
   schema-adaptation design exists to help, given the worst experience.

Both gaps share a root cause: hooks and skills were never part of "done" for
a tool. This doc makes them part of "done" going forward.

@phase 2-the-rule
## 2. The rule

**Every new tool surface that has a footgun (a wrong-but-easy way to use it)
or a multi-step human workflow (confirm a mapping, set up OAuth) ships its
hook and/or skill in the same PR as the tool.** Not a follow-up PR, not a
"someone should write a skill for this" note. If a tool doesn't need either
— most read tools don't — that's fine, nothing is required.

Two tools already shipped without this (PR #10's read-path tools needed
neither; PR #11's `schema_confirm_mapping` needed a skill and didn't get
one). This doc and its companion PR close that gap once, and the rule
applies from here on.

**Addendum (2026-07-08):** the rule then broke again — the task-queue surface
(`task_submit` + the `task_net` capability, B-19; the `# allow_net` directive
footgun, B-21/L-NET-01) shipped with neither skill nor hook, exactly the
footgun-plus-workflow case §2 describes. Closed retroactively: `skills/kart-tasks.md`
(submit/poll workflow, the `task_net`/`allow_net` model, the worker-liveness
caveat) and a `task_submit` matcher on `pre_tool_use.py` that warns when a
caller hand-embeds a stripped network directive. Logged as B-23. The lesson
stands: the rule is only real if it's checked at PR time, not remembered.

**Addendum (2026-07-09):** the rule held this time. B-32's egress leases
(`willow-mcp grant-net`, `lease.py`) shipped in the same PR as their guardrail:
a `Write|Edit|MultiEdit|NotebookEdit` matcher on `pre_tool_use.py`, plus a Bash
matcher, that **blocks** any call writing a key which authorizes the agent's own
egress — minting a lease under `mcp_apps/_net_leases/`, invoking `grant-net`, or
editing a manifest to add `task_net`. `skills/kart-tasks.md` gained the three-key
model in the same change. Note what the hook is and is not: it lives in the
agent's own harness, so it is a **guardrail, not a control** — the control is
`chown` plus `WILLOW_MCP_STRICT_TRUST_ROOT` (B-32 / L-NET-02). A hook that blocks
the crossing makes a mistake catchable and a deliberate crossing undeniable; it
does not make the crossing impossible, and the docs must never let it read that
way.

@phase 3-packaging-shape
## 3. Packaging shape

Bundled inside `willow-mcp` itself (not a separate plugin repo) — one
`pip install willow-mcp` gets the server, the tools, and the guardrails/
workflows together, matching "written alongside the tools." Modeled on the
Fylgja plugin layout already in use elsewhere in this operator's fleet, so
it's a familiar shape rather than a new convention:

```
willow-mcp/
  .claude-plugin/
    plugin.json          # registers hooks + skills for Claude Code
  hooks/
    pre_tool_use.py       # PreToolUse — guards + redirects
    tests_helpers ...      # pure functions, unit-tested directly
  skills/
    schema-confirm.md      # guided schema_confirm_mapping workflow
  src/willow_mcp/           # MCP server (unchanged)
```

`plugin.json` is what a Claude Code user's `.mcp.json`/plugin config points
at to pick up both the MCP server *and* the hook/skill layer in one install
step; a user of a different MCP client (Cursor, a custom agent) is
unaffected — they just don't get the Claude Code-specific hook/skill layer,
same as they already don't get any client-specific integration today.

@phase 4-pre-tool-use-py-contract
## 4. `pre_tool_use.py` contract

Implements Claude Code's `PreToolUse` hook protocol: reads a JSON object
from stdin (`{"tool_name": ..., "tool_input": {...}, "session_id": ...}`),
optionally prints a JSON decision to stdout (`{"decision": "block"|"warn",
"reason": "..."}`), always exits `0` — the decision is communicated via the
printed JSON, not the exit code. No output means "allow, no comment."

Scope for this pass: `Bash` commands that reach for `psql`, `psycopg2`, or
`sqlite3` against a path/dbname willow-mcp owns (`WILLOW_STORE_ROOT`,
`WILLOW_PG_DB`, or the literal `knowledge`/`records` table names) get
`decision: "block"` with a message naming the matching MCP tool
(`store_*`/`knowledge_*`/`kb_*`/`schema_confirm_mapping`). Everything else
is unmatched and allowed silently — this hook is a narrow guard, not a
general security scanner (willow-mcp already has one of those, in
`server.py`'s `_sanitize`/`_guarded` pipeline, which runs inside the MCP
server itself and applies regardless of which client is calling it).

Deliberately out of scope for this pass, left for the next hook/skill that
actually needs them:
- A `PostToolUse` hook reacting to an `unconfirmed_schema` error by
  suggesting `schema_confirm_mapping` — useful, but the read/write tools
  already return a self-describing error message naming the exact next
  call; a hook doing the same thing adds a second place that message can
  drift from the tool's own text. Revisit if the plain error text proves
  insufficient in practice.
- Blocking non-Bash paths to the same databases (e.g. a Python one-liner
  tool) — `Bash` covers the common case; broadening the match surface is
  cheap to add later if a real gap shows up, not worth guessing at now.

@phase 5-schema-confirm-md-skill
## 5. `schema-confirm.md` skill

A guided walkthrough for the human/agent workflow the design doc's §3.2
mapping artifact implies but doesn't script:

1. Preview the mapping with `schema_confirm_mapping(table=..., preview=True)`
   — a read-only dry-run (added for issue #20) that returns the proposed
   mapping *and* a rendered `sample` row showing what each canonical field
   actually resolves to, writing nothing. Reviewing the sample is the whole
   point: a name match is an assertion, not evidence — a `content` column
   that is really a provenance blob (with the real text in `title`/`summary`)
   only reveals itself in the sample, not in the field names.
2. Show the guesses field-by-field *against the sample values*: which are
   `exact`, which are `alias` (name the aliased column), which are
   `unmapped` — and flag any field whose sample value is clearly the wrong
   data as an override to correct, not a mapping to accept.
3. Ask the human to accept each guess or supply a correction (or explicit
   "leave unmapped").
4. Call `schema_confirm_mapping` once with the accumulated overrides.
5. Confirm the result and note which write tools are now unlocked for that
   table.

This intentionally does not let the skill silently call
`schema_confirm_mapping` with zero overrides just to "get it working" —
confirming a mapping is a human decision (design doc §3.4/§8: gated more
strictly than a single write for exactly this reason), and the skill's job
is to make that decision well-informed, not to skip it.

@phase constraints
## Constraints

@constraint severity="critical"
**Addendum (2026-07-09):** the rule held this time. B-32's egress leases
(`willow-mcp grant-net`, `lease.py`) shipped in the same PR as their guardrail:
a `Write|Edit|MultiEdit|NotebookEdit` matcher on `pre_tool_use.py`, plus a Bash
matcher, that **blocks** any call writing a key which authorizes the agent's own
egress — minting a lease under `mcp_apps/_net_leases/`, invoking `grant-net`, or
editing a manifest to add `task_net`. `skills/kart-tasks.md` gained the three-key
model in the same change. Note what the hook is and is not: it lives in the
agent's own harness, so it is a **guardrail, not a control** — the control is
`chown` plus `WILLOW_MCP_STRICT_TRUST_ROOT` (B-32 / L-NET-02). A hook that blocks
the crossing makes a mistake catchable and a deliberate crossing undeniable; it
does not make the crossing impossible, and the docs must never let it read that
way.
