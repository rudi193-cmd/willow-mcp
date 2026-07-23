---
name: debugging
description: Systematic bug hunt — search prior context before reproducing, fix only what is broken, never ship a fix without a test
---

@markdownai v1.0

# /debugging

Structured approach to finding and fixing bugs. Prevents guessing, scope creep,
and fixes-without-tests.

## When to use this

- A bug is reported or a test fails
- Unexpected behavior in an MCP tool, hook, or CLI path
- You're about to change code without a clear hypothesis

## Steps

@if consumer="ai"
1. **Search for prior context** — `knowledge_search` and/or grep the repo for the
   error message, tool name, or module. Check `docs/BUGS.md` for known issues.
2. **State the bug** — exact error, `file:line` if known, expected vs actual.
3. **Identify the smallest reproduction** — minimum input or test that triggers it.
4. **Hypothesize** — list 2–3 candidate causes, ranked by likelihood.
5. **Test the top hypothesis first** — read the relevant file, confirm or eliminate.
6. **Fix only what is broken** — no surrounding cleanup, no refactoring. One surgical change.
7. **Run the relevant test** — confirm the fix holds. If no test exists, write one first
   (see `tdd.md`).
8. **Commit** — message: `fix(<module>): <what was wrong> — <why it was wrong>`
@endif

## Rules

- Never skip step 1. Prior context often contains the root cause.
- Never fix without a test. A fix without a test is just a guess.
- Step 6 is a hard constraint: surgical only. Bug fixes don't get free refactors.

## willow-mcp tips

- **Unit tests:** `pytest tests/test_<area>.py -q` — most tool logic is plain Python.
- **Shell repro:** prefer `task_submit` (Kart) over ad-hoc agent Bash when the bug
  involves git, network, or destructive commands (see `kart-tasks.md`).
- **Diagnostics:** `diagnostic_summary(app_id=...)` surfaces consent, leases, workers,
  and binding problems that look like tool bugs.
- **Hooks:** hook handlers are tested by feeding mock stdin and capturing stdout —
  see `tdd.md` § Hook handler pattern.

## Tips

- If you can't reproduce it in step 3, you don't understand it yet. Don't fix what you
  can't reproduce.
- Two hypotheses is enough. Three is a sign you need more data, not more guesses.
- The commit message format (`fix(<module>): what — why`) is the most useful part of
  the git log six months from now.

## Constraints

@constraint severity=error
Never fix without a test — a fix without a test is just a guess. Never skip step 1 (search for prior context); it often contains the root cause.
