# user.md

A small, living profile of the operator, written by an agent from observed
context. Sparse on purpose — grown like a ring store, one honest layer at a
time, never assumed.

## Identity

- **GitHub:** `rudi193-cmd`
- **Email:** rudi193@gmail.com
- **Role here:** operator and sole maintainer of willow-mcp
- **Where:** Albuquerque, New Mexico — high desert, monsoon season. The kind
  of person who sits out back in a sunshower and mentions it mid-review.

## What they're building

An agent-neutral MCP server with persistent memory (SOIL store, Postgres
knowledge base) and a sandboxed task queue (Kart), governed by a
filesystem-manifest ACL. Around it, a small fleet: personas (hanuman), an
executor (kartikeya), seeds, leases, consent gates. The through-line is
**memory that persists and permissions that are explicit**.

## How they work (observed)

- Runs much of the development through Claude Code sessions — greets the
  agent by name ("Hello Willow") and treats it as a collaborator.
- Keeps a disciplined bug ledger (`docs/BUGS.md`, `B-NN` IDs, P0–Pn
  severities) and a standing `SECURITY_AUDIT.md`. Findings get triaged,
  superseded, and cross-referenced rather than quietly fixed.
- Cares that documentation tells the truth. A recent PR existed solely to
  stop a docstring from claiming a kill switch the system doesn't have —
  "this only stops the repo from lying about it."
- Mixes rigor with story: modules like `the_grove.py` carry narrative
  weight (rings, lessons, canopy) and still ship with hundreds of passing
  tests. The poetry is load-bearing, but so are the tests.
- Comfortable asking for help plainly ("I have a couple PRs that are in
  merge conflict") and letting the agent figure out the rest.

## Values worth honoring in this repo

1. Never let docs or schemas overclaim what the code does.
2. Security findings get IDs and a paper trail, not silent patches.
3. Lessons are kept on purpose — the deployment must not become something
   that forgets them.

## Provenance

Started 2026-07-09 by Claude Code from a single session's context. Expect
gaps; correct freely. Two rings so far.
