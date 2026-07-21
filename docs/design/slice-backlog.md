# Slice backlog — the one ordered board

Status: **LIVING** — started 2026-07-21. One place to see every outstanding
slice so they stop being rediscovered by hand. Consolidated from the roadmap
docs (`willow-2.0-gap-inventory.md §6`, `session-lifecycle.md §10-11`,
`kart-productionization.md §6`, the design-doc "open questions"), the `docs/BUGS.md`
cross-repo blockers, and a code sweep for `not yet` / `deferred` / seam-stub markers.

**How to read.** Each slice is a checkbox. Tiers, not just priority:

- **Ready now** — unblocked, self-contained, could be a PR today.
- **Cleanup** — near-zero drift this sweep surfaced (stale comments, stale counts).
- **Earn-first** — a real capability, but deliberately deferred until a
  willow-mcp consumer needs it (the "surface is earned" rule). Do NOT build
  ahead of a consumer.
- **Leave** — non-goals, listed so they stop being re-litigated.
- **Cross-repo** — the fix lives in `willow-2.0`, not here.
- **Decisions** — blocked on an operator call, not on engineering.

A ticked box links to where it landed. When a slice turns out already-done,
tick it and note the mechanism — a stale tracker is its own small drift.

---

## Ready now (unblocked, self-contained)

- [ ] **PG `dispatch_tasks` dual-write** when a host Postgres is present —
  filesystem stays canonical for standalone; mirror packets to PG when a fleet
  DB is configured. *(session-lifecycle §11.)* Needs a host DB to verify; design
  the mirror as best-effort, never blocking the filesystem write.
- [ ] **G-1 / S6 — SOIL DAG + `dag_next` / `dag_status`** — route dispatch by
  `function` → default `agent_id`. Design exists (S6); the two tools are absent
  from the live surface (verified). *(session-lifecycle §10 S6; gap-inventory §6.)*

## Cleanup (this sweep)

- [x] **Subject-consent enforcement is live** — driven end-to-end: a non-owner
  `subject_id` with no grant is denied `subject_consent_denied` at `_gate`
  (`server.py:687`), and the four subject-scoped tools carry `subject_id`. The
  "correct-but-dormant / next slice" comment in `subject_consent_binding.py` was
  stale and is corrected. (This was PR #138's stated "next bite" — already done.)
- [x] **Kart worker-run skill section** — `skills/kart-tasks.md §0` already
  documents `willow-mcp worker --lane/--once` and `fleet_health` liveness; the
  `kart-productionization.md §6` tracker item that called it deferred is stale
  and is marked done.
- [x] **`gap-inventory.md` stale tool count** — "server.py tools = 73" refreshed
  to the current surface (97 `@mcp.tool()` / 103 live).

## Earn-first (wire only when a consumer needs it)

Per `gap-inventory.md §3/§6` — real capabilities, all `full`-only and/or untested
in willow-2.0. Order is rough tractability.

- [ ] **`workflow_*`** (5) — multi-phase engine; rides the existing Kart `task_*`
  queue, so the most tractable of this tier.
- [ ] **`willow_web_search` Brave provider** — the seam ships (`web_search.py`
  `BraveSearchProvider`, `_IMPLEMENTED = False`); implement the real call +
  `BRAVE_API_KEY` path behind the `web_net` egress gate when a consumer needs a
  second provider. DDG is the working default today.
- [ ] **Calendar gcal OAuth transport** — the calendar source + tests exist;
  the live gcal transport is a home-box OAuth step, deferred (`server.py:3829`).
- [ ] **`intake_*`** (4) — KB-tier routing; needs jeles/binder/opus targets first.
- [ ] **`skill_*`, `index_*` / `cmb_*`, `cbm_*`, `mem_binder_*` / `mem_ratify_*`**
  — registries and extra KB sub-stores mirroring existing store patterns.
- [ ] **SOIL edges + `pg_edge_*`** (5) — graph edges over the store willow-mcp
  already owns.
- [ ] **Maintenance / analytics readers** — `ledger_repair`, `handoff_search` /
  `handoff_rebuild`, `routing_log_read`, `session_query` / `session_review`.
  Cheap, low priority.
- [ ] **6 integration stubs to earn** — `gmail`, `slack`, `notion`,
  `google-drive`, `datadog`, `jira`; each declared with what earns it
  (`integrations.py`).

## Leave (non-goals — do not port into a clean product without a strong reason)

`mem_jeles_*`, `infer_*` (local inference/TTS/image), `outcome_*`, `routine_*`,
`app_*` (SAFE-app lifecycle), `dream_*` / `wce_*`, fleet-daemon ops
(`fleet_reload/restart/persona/…`), `policy_*` (replaced by envelopes), and the
`product-layout.md` "future" shells (`packages/` loader, `ledgers/` writer).

## Cross-repo (fix lives in willow-2.0, tracked in `docs/BUGS.md`)

- [ ] **B-31** — consent writer fails open.
- [ ] **B-35** — envelope metering never written.
- [ ] **B-28** — `completed_at` set on failed tasks.
- [ ] **Kart lift-spec stage 5** — the willow-2.0 side of the executor lift
  (open by design; willow-mcp side shipped as `kartikeya`).

## Decisions (operator call, not engineering)

- [ ] **S3 / G-2 — role-envelope enforcement**: largely **subsumed** — the gate
  already enforces the registry `permissions` + `deny_tools` via the compiled
  manifest (`specialist-registry.md` S-R7, done), and `roles.py` is loader-only
  and unused at runtime. Decide: close S3, or re-scope the residual (a separate
  hook-side role check) as deliberate defense-in-depth. Not a clean build as
  written.
- [ ] **Guardian-consent — "Open questions for Sean"** (`guardian-consent-seam.md`):
  subject-identity model (stable owner-assigned handle vs per-corpus), where the
  consent store physically lives, and the Nest household default relation. These
  gate the household/UTETY consumers.
- [ ] **`gap-backlog.md §6`** — auto-drafting promotion candidates, and who
  verifies before `gap_promote` (operator / reviewer agent / quorum).
- [ ] **`schema-adaptation.md §8`** — open questions for the next schema pass
  (not blocking current writes).
