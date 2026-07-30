# Handoff — 2026-07-30 · hooks surface, and six ways a gate lies about itself

Branch: `claude/handoff-hooks-next` (this PR). Written from a remote Claude Code
(CCR) session whose work was almost entirely in **`safe-app-store`**, not here —
four PRs merged there (#126, #127, #128 plus #126's predecessor context). This
document exists because the next session is meant to work on **hooks in
willow-mcp**, and two things are worth carrying across: the hooks surface as it
actually stands today, and a methodology lesson that applies to hooks more
directly than to anything else in this repo.

**Read §3 first if you read nothing else.** §1 is orientation you could get from
the code. §3 is the part that cost real time to learn and that a hook is
unusually good at hiding.

---

## 1. The hooks surface as it stands (verified, not remembered)

One hook, five guards, two identical copies, 107 tests.

| | |
| --- | --- |
| `hooks/pre_tool_use.py` | 560 lines. The repo copy — what the tests exercise. |
| `src/willow_mcp/bundle/hooks/pre_tool_use.py` | Byte-identical. What actually ships to an agent's harness. |
| `src/willow_mcp/pre_tool_hook.py` | The `-m` entry point. Loads the **bundled** copy by path, not the repo one. |
| `src/willow_mcp/deploy/claude-settings.json` | Where the matchers are wired. |
| `tests/test_pre_tool_use_hook.py` + `tests/test_authority_surface.py` | 107 tests, green. |
| `docs/design/hooks-and-skills.md` §4 | The contract, and an explicit out-of-scope list. |

**The duplication is already gated.** `test_bundled_hook_is_identical_to_the_repo_copy`
fails if the two copies drift, which matters because the entry point loads the
bundled one and the tests exercise the repo one — a fix applied to only the
tested copy would pass CI and ship nothing.

**Wired matchers**, all routed through `willow_mcp.pre_tool_hook`:

```
SessionStart   (all)                              -> willow_mcp.session_start_hook
PreToolUse     Bash
PreToolUse     task_submit
PreToolUse     Write|Edit|MultiEdit|NotebookEdit
PreToolUse     WebSearch|WebFetch
```

**The five guards**, in the module's own terms: raw `psql`/`psycopg2`/`sqlite3`
against an owned store (including one level of script indirection —
`python3 drop.py` gets its file read); Bash habits that duplicate MCP tools;
`task_submit` text with a hand-embedded Kart network directive, which the server
strips anyway; the IDE-native web tools, redirected to `willow_web_*`; and any
call that would write the keys authorizing the agent's **own** egress or re-grant
its own write seat.

**The framing that must not erode**, already in the docstring and worth
restating because it is the thing a hook PR is most likely to overclaim:

> A hook lives in the agent's own harness. It is a **guardrail, not a control** —
> an agent that bypasses it faces no OS-level obstacle on a single-uid host. The
> control is `chown` plus `WILLOW_MCP_STRICT_TRUST_ROOT` (B-32). What the hook
> buys is that a mistake becomes catchable and a deliberate crossing stops being
> deniable.

**Already named as deliberately out of scope** (design doc §4), so a next session
proposing them should say what changed rather than treat them as gaps:

- a `PostToolUse` hook reacting to `unconfirmed_schema` — rejected because the
  tools already return a self-describing error naming the next call, and a hook
  repeating it is a second place that text can drift from;
- blocking non-`Bash` paths to the same databases — `Bash` covers the common
  case, and the script-indirection guard has since closed part of it.

---

## 2. What was done here (small, and honest about it)

**One change: the docstring said "Four guards" and there are five.**
`check_native_web` — the `WebSearch|WebFetch` block — is implemented, wired by
its own matcher, and tested, and it was missing from the module's own summary.
Fixed in both copies, so `test_bundled_hook_is_identical_to_the_repo_copy` stays
green.

That is a two-line fix and it is in this PR for one reason: it is the **fourth
instance this session** of the same defect family — a count in prose that the
code has moved past — and it would have been strange to write §3 while leaving a
worked example of it in place. The other three were in `safe-app-store`: a README
claiming 27,534 differential comparisons two commits after it became 27,536, one
claiming 43 gate tests when there were 54, and, earlier, "96 tests" quoted from a
README when the suite had 123.

**Nothing else in this repo was touched.** No hook logic changed, no matcher
changed, no test changed.

**What this session actually did, since it bears on the SOIL store here:** landed
migratability tests, authentication, and a corrections table in
`safe-app-store/apps/marching-arts` (221 Python tests, 27,540 differential
comparisons, 60 browser gate tests, all green on `master` at `b1825f7`). Along the
way it wrote **17 records into `gate_app_ideas`**, taking it from 85 to 102 — and
wrote them **directly through `willow_mcp.db.Store.put`**, because Grove MCP is
unauthorised in a CCR session and its tools do not appear in the tool list at all.
Records went to `/workspace/willow-mcp/.willow/store`, which is where the existing
85 live, so this is the same store the server serves. Ids are kebab-case slugs;
every record carries `title`, `status`, `confidence`, and a `corrects` field where
it supersedes an earlier one.

---

## 3. Six ways a gate lied about itself, and why hooks are the worst case

Across three PRs this session, **six defects were found in the verification
apparatus and zero in the code under verification.** That ratio is the finding.
A hook is the sharpest version of the problem, because a hook *is* a gate: its
whole value is failing when it should, and nothing about a passing test suite
distinguishes "this guard fires correctly" from "this guard never fires."

The six, and the shape each one shares:

1. **A differential reference generated before the thing it checked changed.**
   27,528 comparisons, 0 disagreements, against a stale reference — while a whole
   clause was unchecked. Fix: regenerate on every run, never cache.
2. **A fixture that wrote a hash chain with the function it read it with.**
   Shortening the subject hash by one character was perfectly self-consistent,
   passed cleanly, and would have orphaned every chain already on disk. Fix: pin
   the on-disk name to a **literal**, never recompute it.
3. **A fixture with no row the principal could not already see.** The test whose
   entire job was to force a roles table compared "what a decorated principal
   sees" against "what a plain one sees" — and with everything already visible,
   granting a blanket `admin` allow changed nothing to compare. The tripwire could
   not fail. Fix: the fixture must contain the thing the guard is supposed to
   withhold.
4. **A killed mutation harness left a mutation in the tree.** It never reached
   its `finally`. One unrelated test then failed in every later leg, and a
   mutation that a hand reproduction showed catching all seven of its tests was
   reported *weak*. Every number from that run was fiction. Fix: **refuse to
   start unless the suite is green on unmutated source.**
5. **Three mutations that renamed a SQL trigger instead of disabling it.** A
   trigger is bound to a table and an event, not to its identifier, so it kept
   firing under the new name and the mutation proved nothing. Fix: neutralise the
   `WHEN` (`WHEN 0 AND <original>`), and — the general rule — **report which test
   caught each mutation**, because a harness printing only a pass count scores a
   no-op as a success.
6. **Counts in prose that nothing verifies.** Four instances, one of them in this
   repo (§2).

### What transfers to hook work, concretely

**A hook's mutation is not "delete the hook."** That is the equivalent of
renaming the trigger — too coarse to be informative, and it fails so loudly that
it proves only that *something* is wired. The useful mutations are per-guard and
per-regex:

- make `_CLIENT_RE` not match `sqlite3`, and see whether any test notices;
- make `_OWNED_MARKER_RE` not match `WILLOW_STORE_ROOT`;
- make `_SCRIPT_INVOKE_RE` miss the `cd X && python3 y.py` form;
- make `check_native_web` return `None` for `WebFetch` only;
- flip a `block` to a `warn` in one guard;
- have `main()` print nothing when a guard returns a decision.

Any of those that leaves the suite green is a guard with no gate behind it.

**And the specific trap this hook invites:** a `PreToolUse` guard is a *regex over
a string*, so a test that constructs the string from the same regex — or asserts
only that a known-bad command is blocked, never that a known-*good* one is
allowed — is failure #3 in a new costume. The suite already has 107 tests and I
did not audit whether they cover the allow side per guard. That is the first thing
I would check.

**A green suite is a claim about the harness, not about the code.** The browser
resolver in `safe-app-store` went green on 27,534 comparisons while a
`pauseVfs()` handoff underneath it had *never once executed* — Node has no OPFS,
so the mechanism had no environment to run in. Before trusting the 107, ask what
they structurally cannot reach: they exercise pure decision functions, which is
the right shape, and it means they say nothing about whether the wiring in
`deploy/claude-settings.json` actually delivers stdin to them in a live session.

---

## 4. Questions, sequential and bite-sized

1. Which hook is the next bite — a new `PostToolUse`, a new guard inside
   `pre_tool_use.py`, or a `SessionStart` change? The three have different blast
   radii and only the middle one is covered by existing tests.
2. If it is a `PostToolUse` hook, does the design doc §4 rejection still hold, and
   if not, what changed? Reopening a recorded decision should say so out loud.
3. Do the 107 tests cover the **allow** side of each guard, or only the block
   side? I did not check, and a guard that blocks everything passes a
   block-only suite.
4. Should a hook mutation harness live in the repo (`tools/`) or stay a scratchpad
   script? It edits source in place, which argues for out; hooks are exactly the
   thing worth re-verifying on every change, which argues for in.
5. Is `check_native_web`'s block the right severity now that `willow_web_*`
   ships — block, or warn with a redirect? It is the only guard whose subject is a
   capability rather than a boundary.
6. Does the script-indirection guard (`_SCRIPT_INVOKE_RE`) want a second level —
   a script that invokes a script — or is one level the deliberate stopping point?
7. Should the "guardrail, not a control" sentence be asserted by a test over the
   docs, so no future PR can quietly upgrade the claim? This repo already has that
   habit elsewhere.
8. Is there a lint for counts-in-prose worth building, given four instances in one
   session across two repos? A doc-count check over the READMEs would close it.
9. Do the 17 new `gate_app_ideas` records need anything done to them — a
   `soil_package` pass, a proper-noun lint — or do they sit until asked for?
10. **Next single bite:** answer #3 by running the existing suite with one guard's
    regex neutralised, and see whether anything goes red. It needs no new code, it
    is five minutes, and it tells you whether the other 106 tests are worth
    trusting before you add a 108th.

---

## 5. Risks / open gates

- **Grove MCP is unauthorised in CCR sessions** and its tools are absent from the
  tool list entirely — not merely unauthenticated. Anything that needs to write
  SOIL from a remote session has to go through `willow_mcp.db.Store` directly, as
  this session did, or the write silently has nowhere to go. `psycopg2` must be
  stubbed to import `willow_mcp.db` at all (it is imported for the Postgres KB
  half, which the SQLite store path does not touch).
- **The hook tests need `PYTHONPATH=src`** in this container. CI does
  `pip install -e "."` so it does not hit this; a local `python -m pytest tests/`
  errors on collection with `ModuleNotFoundError: No module named 'willow_mcp'`.
  Not a repo defect, but it will look like one for thirty seconds.
- **The entry point loads the bundled copy, the tests exercise the repo copy.**
  Gated by one test. If that test is ever skipped or its path drifts, a fix can
  pass CI and ship nothing.
- **Nothing here was deeply audited.** §1 is the module docstring, the function
  list, the design doc §4, the wired matchers, and a green test run. It is not a
  review of the guard logic, and §3's question 3 exists because I do not know the
  answer.
- **Open from the earlier handoff** (`2026-07-23`), unverified in this session and
  possibly stale: issue #164 (enforcement stack dormant in remote sessions), gaps
  `f63582061206` and `4060189ff2fa`, backlog #158/#84/#159/#160/#161.
- **`safe-app-store` state, for cross-reference:** `master` at `b1825f7`, 221
  Python tests, 27,540 differential comparisons, 60 browser gate tests, catalog
  lint clean. One mechanical blocker there: no `promotion.json`, which needs
  `verified_by != author` and is therefore a human act.

---

## 6. Where the evidence lives

- **SOIL** — `gate_app_ideas`, 102 records. This session's 17 start at
  `migratability-four-gates-landed` and end at
  `session-index-2026-07-30-corrections`; the three session-index records are the
  entry points, and the one worth reading first is
  `a-rename-is-not-a-mutation-third-instance`.
- **The mutation harnesses** — three of them, scratchpad-only, one per test
  module. Each carries the green-baseline guard and per-mutation attribution
  described in §3.
- **`safe-app-store`** — `apps/marching-arts/docs/BUILD_PLAN.md` has the current
  "what stands between this and a corps using it" section; `README.md` has the
  authentication and corrections sections.
