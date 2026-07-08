# Design: Hooks and Skills Ship Alongside Tools, Not After

Status: DRAFT — first hook + skill landing with this doc; not yet ratified as
a hard process rule, but intended as one.

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

## 5. `schema-confirm.md` skill

A guided walkthrough for the human/agent workflow the design doc's §3.2
mapping artifact implies but doesn't script:

1. Read the current (possibly unconfirmed) mapping for a table — either
   from the `_unmapped` field on a read tool's response, or by calling
   `schema_confirm_mapping` read-only... except the tool has no read-only
   mode (it always confirms). The skill's first step is calling the
   read-path tools (`knowledge_search`, `kb_at`, etc.) to surface the
   *current* heuristic mapping's `_unmapped` list and any visible
   `tier: "alias"` guesses, without side effects — confirmation only
   happens at the end, once a human has seen what it would do.
2. Show the heuristic guesses field-by-field: which are `exact`, which are
   `alias` (name the aliased column), which are `unmapped`.
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
