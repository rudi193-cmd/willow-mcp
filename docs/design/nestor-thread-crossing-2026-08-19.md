# Nestor thread-crossing analysis — 2026-08-19

Fed 926 doc sections from across willow-mcp into a Nestor store (domain
`willow-doc`) and probed for cross-file concept overlap. The goal: find where
independent design documents converge on the same concern, which reveals both
the strongest seams and the likeliest next work items.

## Method

Each markdown section (heading + body) became one Nestor draft pair.
`memory.lookup()` with `context_threshold=0.15` on 20 topic probes, then
targeted cross-matching between `docs/ideas.md` and `docs/PRIOR_ART.md`.

## Highest-density crossings (5+ docs touching one topic)

| Topic | Docs | Files |
| --- | --- | --- |
| Dispatch & specialists | 8 | AGENTS, ROLES, ideas, permissions-matrix, agent-seed, pgp-and-persona, complete-system-packet, specialist-registry |
| Knowledge base & memory | 7 | PRIOR_ART, AGENTS, ideas, mai-conversion, willow-gate-seam, BOX_INVENTORY, ideas |
| Permission groups & access | 6 | permissions-matrix, hooks-and-skills, PRIOR_ART, SESSION_FLOW, consent-toggles, permissions-matrix |
| Federation | 6 | PRIOR_ART, integrations, BOX_INVENTORY, ideas, federation-wire-format |
| Human consent & approval | 6 | guardian-consent-seam, human-orchestrator, AGENTS, README, session-lifecycle |
| Commitment tracking | 6 | PRIOR_ART, ARCHITECT, ideas, README, agent-seed |
| Hooks & pre-tool-use | 5 | hooks-and-skills, README, NEST, AGENTS |
| FRANK ledger & audit | 5 | ideas, README, ROLES, CHANGELOG |
| Nestor integration | 5 | agent-seed, README, integrations, ideas |
| Grove messaging | 5 | README, integrations, PRIOR_ART, AGENTS |
| Exposure & slicing | 5 | ROLES, ARCHITECT, README, agent-seed, ideas |

## PRIOR_ART verdict × thread crossing — where they agree

1. **MCP Resources (adopt — high priority)** → shipped this PR. KB atoms and
   store collections now exposed as URI-addressable MCP resources.

2. **Cursor pagination (spec)** → shipped this PR. Keyset cursors on 10
   list/search tools.

3. **Annotations (spec)** → shipped PR #350. Marked as shipped in PRIOR_ART
   this PR.

4. **Threading consolidation (build)** — three independent threading models
   across 1.9/2.0/safe-app-store. Grove has `grove_reply`/`grove_get_thread`
   with FK-backed `reply_to_id`. Not yet consolidated into willow-mcp's Grove
   tools.

5. **Integration stubs → compose** — six stubs (Gmail, Slack, Notion, Drive,
   Datadog, Jira) all have Apache-compatible MCP servers. PRIOR_ART says
   compose, don't rebuild.

6. **Streamable HTTP transport (adopt — high priority)** — willow-mcp is a
   remote server by nature. Protocol is now stateless; willow already uses
   explicit handles (`app_id`).

## ideas.md → PRIOR_ART.md cross-matches (Nestor similarity)

| ideas.md section | PRIOR_ART match | sim |
| --- | --- | --- |
| Code graph | Code graph | 1.00 |
| Friction floor / mirror detector | Friction floor (sycophancy detection) | 0.74 |
| Commitments & human-required | Commitment membrane | 0.68 |
| Integrations & egress | Integration stubs — compose, don't rebuild | 0.56 |
| Nest & intake | The verdict column, unpacked | 0.52 |
| Grove (lessons / rings) | Model egress consent gate | 0.50 |

## What's unique to willow (no external equivalent found)

Eight shapes nobody else builds — differentiators to strengthen:

1. `gap_*` — self-observing backlog
2. `friction_scan` — KB edge tension detector
3. `lineage_*` with "why" — provenance chains recording reasoning
4. `frank_*` governance ledger — tamper-evident append-only
5. Dispatch federation — cross-agent with depth limits and envelope gating
6. Nestor tool routing — meaning-infrastructure-backed tool dispatch
7. Commitment membrane — ingest/surface/acknowledge lifecycle
8. Exposure membrane — data boundary slicing

## Annotation consistency findings (this PR)

The audit found 4 tools annotated `readOnlyHint=True` that actually write:

| Tool | What it writes | Fix |
| --- | --- | --- |
| `verify_handoff` | `dispatch_set_status("verified")` | → `ANNO_WRITE` |
| `agent_seed_mirror` | `store.put()` into `willow_agents_seeds` | → `ANNO_WRITE_IDEM` |
| `context_get` | `store.delete()` for expired records | → `ANNO_WRITE` |
| `context_list` | `store.delete()` for expired records | → `ANNO_WRITE` |

A structural test (`test_annotation_consistency.py`) now guards against
regressions — same source-reading approach as `test_authority_surface.py`.

## What feeds back to Nestor

The annotation mismatches are the same shape as `session_enter` (PR #350):
**a guarantee enforced by convention, and a second path that never passes it.**
This is `TODO.md`'s closing note and `IDEAS.md` §1.6/§1.7/§1.8 in the Nestor
repo. The structural test is the mechanism that replaces the convention.

The "threads crossing" result itself is a Nestor use case: a corpus too large
for one person to hold in working memory, surfaced by feeding it through the
matcher and seeing where the similarity scores cluster.
