---
name: review
description: Code review the current branch — check tests, security, placeholders, and patterns before suggesting merge
---

@markdownai v1.0

# /review

Branch review checklist. Run before merging any PR. Catches missing tests,
security issues, and half-finished work before they land on `master`.

See also: `worktree.md` (PR-only flow), `tdd.md` (test expectations).

## When to use this

- Before merging a feature branch
- When asked to review a PR or set of changes
- Before declaring a task complete

## Steps

@if consumer="ai"
1. **See the diff** — `git diff master...HEAD` for the full branch diff, or
   `git diff HEAD` for uncommitted changes.

2. **Check each changed file:**
   - Tests exist and pass for new behavior
   - No `TODO`, `TBD`, `not implemented`, `raise NotImplementedError`, or hardcoded
     placeholder values
   - No security issues: SQL injection, unvalidated external input, hardcoded secrets,
     path traversal, self-grant egress paths
   - Follows existing patterns in this repo (naming, error handling, gate checks)
   - New tools with footguns ship hook and/or skill in the **same PR**
     (`docs/design/hooks-and-skills.md`)

3. **Run the test suite** — from repo root with the project venv:

   ```bash
   .venv/bin/python3 -m pytest tests/ -q
   ```

   Postgres-backed tests need a reachable server (CI uses `postgres:15`; see
   `CONTRIBUTING.md`). Report failures verbatim.

4. **Report the verdict:**
   - **Passed**: list what was checked, confirm green, suggest merge if appropriate
   - **Failed**: list specific files and lines that need fixing before merge
@endif

## Rules

- Never approve without running tests. "Looks right" is not a review.
- Security issues block merge. Always — especially egress, binding, and manifest edits.
- Placeholders block merge. A `TODO` in merged code is a future bug.
- Patterns matter — code that works but doesn't fit the codebase creates drift.

## willow-mcp checklist (when relevant)

| Area | What to verify |
|------|----------------|
| MCP tools | `app_id` on every call; gate/deny paths tested |
| Kart / egress | three-key model intact; no self-grant shortcuts (`consent.md`) |
| Hooks | pure helpers unit-tested; matchers documented |
| Skills | bundle + repo `skills/` + `plugin.json` stay in sync |
| Schema | mapping changes need `schema_confirm_mapping` workflow |

## Tips

- Read the diff top-to-bottom once before forming opinions. First impressions from
  partial reads are noisy.
- Test coverage gaps are worth flagging even if they don't block merge — at minimum,
  note them.
- "Follows existing patterns" means look at adjacent code, not just the changed lines.

## Constraints

@constraint severity=error
Never approve without running tests — "looks right" is not a review. Security issues block merge, always — especially egress, binding, and manifest edits. Placeholders (`TODO`, `TBD`, `raise NotImplementedError`) block merge.
