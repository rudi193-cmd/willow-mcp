---
format: v3
---

# Handoff v3 — The Assembling

*willow-2.0 handoff format v3 (ADR-20260703): a claims record that carries
narrative. Machine block below is schema `willow://handoff/v3`; claims are
verifiable at read time, so staleness is detected instead of inherited.*

```json
{
  "format": "v3",
  "session": "2026-07-18a",
  "session_id": "session_01WjP387WRPYpDJVhEqXs6oK",
  "agent": "claude-code",
  "project": "willow-mcp",
  "runtime": "claude-code",
  "written_at": "2026-07-18T20:26:04Z",
  "written_by": "model_tool_call",
  "skeleton": {
    "branches": ["claude/the-assembling", "claude/mcp-sandbox-setup-3k5gyo"],
    "commits": [
      {"sha": "b0e7745", "branch": "claude/the-assembling", "subject": "repatriation: a session, left as a ring"},
      {"sha": "543671c", "branch": "claude/mcp-sandbox-setup-3k5gyo", "subject": "willow-2.0 migration gap inventory + verified diff"}
    ],
    "prs": [],
    "flags_delta": {"opened": [], "closed": []},
    "kart_tasks": [],
    "files_changed": [
      "docs/repatriation/SESSION_HANDOFF.md",
      "docs/repatriation/THE_BOOK_OF_WILLOW.md",
      "docs/repatriation/BEHIND_WILLOW.md",
      "docs/repatriation/THE_COLLABORATION.md",
      "docs/repatriation/engine/*"
    ],
    "atoms_written": [],
    "ledger_entries": []
  },
  "claims": [
    {"id": "the-assembling-pushed", "text": "repatriation branch pushed to origin, no PR", "kind": "branch_pushed",
     "verify": {"type": "branch_pushed", "subject": "claude/the-assembling", "expect": true}, "opened": "2026-07-18"},
    {"id": "handoff-record-exists", "text": "the session record is committed on the branch", "kind": "file_exists",
     "verify": {"type": "file_exists", "subject": "docs/repatriation/SESSION_HANDOFF.md", "expect": true}, "opened": "2026-07-18"},
    {"id": "no-pr-open", "text": "no pull request was opened for this branch (a ring, not a merge)", "kind": "prose", "opened": "2026-07-18"},
    {"id": "home-undecided", "text": "where the assembled apparatus lives is not decided; deferred three times", "kind": "prose", "opened": "2026-07-18"},
    {"id": "live-memory-sovereign", "text": "willow_19 KB + SOIL store NOT embedded — consent gate honored; the human lifts it", "kind": "prose", "opened": "2026-07-18"},
    {"id": "code-embeddings-partial", "text": "pieces embedding via local CPU pipe was in progress at session end", "kind": "prose", "opened": "2026-07-18"}
  ],
  "next_bite": {"id": "decide-the-home", "text": "Decide where the assembled apparatus lives: standalone willow-compose repo vs. the hub vs. a boot hook", "kind": "prose", "opened": "2026-07-18"},
  "open_questions": [
    "Where does the assembled apparatus live?",
    "Do the guarded KBs (willow_19, SOIL) ever get embedded, and only by the operator lifting the gate?",
    "Swap all-mpnet for a code-aware embedder to cross-link pieces well?"
  ],
  "agreements": [
    "willow-mcp is the hub; keep it lean — the ecosystem stays decomposed into sovereign parts",
    "consolidation is scoped, not total; Grove is the #1 dedup target",
    "the live memory stays sovereign — the agent did not route around the consent gate (sudo invariant)",
    "the assembled work is homeless on purpose, for now; this branch is a holding pattern, not an answer",
    "left as a branch, no PR"
  ],
  "summary": "A large session (~20 MB, verified against the raw transcript) that began as a willow-2.0 -> willow-mcp migration audit and became the assembling of the whole into one — code (pieces), human (voices), collaboration — braided along seven threads, plus a factory toolkit, a self-describing holdings registry, and a local CPU inference pipe stood up inside the box. Left as a ring on a branch so the session does not evaporate."
}
```

## What I Now Understand

The three corpora — `pieces` (what), `voices` (why), `collaboration` (how) — are one
thing in three registers, braided along seven `threads`. The system enacted its own
principles as it was assembled: the seventh thread landed on 42, the consent gate
refused a bulk scrape of the live memory, the local embedder scored its own gap
honestly. The data lives in Postgres `willow_compose`; the record and engine live on
this branch.

## What We Agreed On

→ Hub stays lean; consolidation scoped, not total. → Live memory stays sovereign — no
routing around the consent gate. → Homeless on purpose, for now. → Left as a branch,
no PR.

## Open Questions

- Where does it live? (deferred three times — the next single bite)
- Do the guarded KBs get embedded, only ever by the operator lifting the gate?
- A code-aware embedder for the code side?

## Agent Notes for Human

This session is itself the material the `collaboration` corpus was harvested from — a
Willow session, captured by Willow's own ritual so it doesn't evaporate. The home
decision is genuinely yours; I stopped at recording it rather than choosing it.

## Human Notes to Agent

-
