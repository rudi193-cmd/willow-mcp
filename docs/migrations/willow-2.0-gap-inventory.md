# Migration Gap Inventory — willow-2.0 → willow-mcp

Status: **INVENTORY** (2026-07-18). This is a stock-take, not an implementation.
It reconciles the forward-looking language in `docs/design/*` against the
*current* state recorded in `docs/BUGS.md`, `CHANGELOG.md`, and the live tool
surface, so the "what's left" list reflects reality rather than the intent
captured when each design doc was written.

> **Method & caveat.** willow-2.0 (`~/github/willow`, the fleet service) is **not
> present in this sandbox** — this inventory could not diff against its source
> tree. The delta below is derived from willow-mcp's own docs, bug ledger,
> changelog, and the 69 registered MCP tools. Items that require reading
> willow-2.0 to size accurately are marked **[needs 2.0 source]**.

---

## 0. TL;DR

The migration is **much further along than the design docs read.** The largest
item several docs still describe as "not yet started" — the Kart task executor —
**shipped** (B-22 closed): Kart was extracted as the published
[`kartikeya`](https://pypi.org/project/kartikeya/) package, made a hard
dependency (`kartikeya>=0.0.3,<0.1.0`), and `willow-mcp worker` now drains the
queue. Several Kart design docs (`kart-productionization.md`,
`kart-lift-spec.md`) are **stale** and should be marked superseded.

What genuinely remains splits three ways:
1. **Unbuilt willow-mcp features** — DAG/orchestration tools, role-envelope
   enforcement, consent leases, canonical-identity modelling.
2. **Deliberate non-goals** — fylgja hooks, persona picker, Grove daemons.
   willow-mcp replaced these with "packet is boot" *by design*; they are **not**
   migration targets.
3. **Cross-repo blockers** — bugs whose fix lives in willow-2.0's writer code
   (consent, envelope metering). willow-mcp already reads defensively around
   them; full severance waits on the 2.0 side.

---

## 1. Already ported (done — do not re-migrate)

| Capability | willow-mcp home | Evidence |
|---|---|---|
| **SOIL store** (SQLite k/v + FTS + soft-delete) | `db.py`, `store_*` (11 tools) | live |
| **Postgres KB** (multi-keyword search graph) | `knowledge_*`, `kb_*` (7 tools) | live |
| **Kart executor** (sandbox, worker, lanes) | `kartikeya` PyPI dep + `willow-mcp worker` | **B-22 Fixed** |
| **Task queue** (Pg + SQLite) | `task_submit/status/list`, `WillowMcpTaskQueue` | live |
| **Dispatch / handoff / session stack** | `dispatch_*`, `handoff_*`, `session_*` | S1–S5 **done** |
| **Gap backlog** (propose→resolve→promote) | `gap_*` (6 tools), `gaps.py` | PR #54 shipped |
| **FRANK ledger** (append/read/verify) | `frank_*` (3 tools) | live |
| **Lineage / provenance** | `lineage_*` (4 tools) | live |
| **Identity + Ed25519 signing** | `signing.py`, `identity_binding.py` | end-to-end proven |
| **PGP verification** | `pgp.py` (ported from `willow-2.0/sap/core/gate.py`) | done |
| **Egress lease machinery** | `willow-mcp grant-net`, `egress_authorization.py` | B-37 Fixed |
| **Fail-closed consent reader** | `consent.py` | reads independently of 2.0 writer |

Tool surface: **69 registered MCP tools** vs. the "100+" attributed to
willow-2.0 in `session-lifecycle.md` §9. The residual ~30 are mostly the
deliberate non-goals in §3 plus the unbuilt features in §2 — not a flat backlog
of missing plumbing.

---

## 2. Remaining willow-mcp features to build

These are willow-mcp's own roadmap — capabilities willow-2.0 has that the product
still intends to own standalone.

| # | Gap | Status today | Source | Blocked on |
|---|---|---|---|---|
| G-1 | **DAG orchestration** — `dag_next`, `dag_status`, `status_report`; SOIL-backed DAG | **not built** (0 tools) | `session-lifecycle.md` S6 / §11 | — (design exists) |
| G-2 | **Role-envelope enforcement** — enforce persona allow/deny in `gate.py`/hook | metadata in `roles.py`; **no enforcement** | `session-lifecycle.md` S3 | operator ratifying the **permissions matrix** (`permissions-matrix.md`) |
| G-3 | **Consent leases** — issue/check time-boxed consent leases | **not built** | `schema-adaptation.md` §6.3 | schema §§1–5 not yet ratified |
| G-4 | **Canonical identity model** (§6.2) | **not built** | `schema-adaptation.md` §6.2/§9 | schema ratification |
| G-5 | **Jeles corpus (local half)** | only the **remote** search adapter is wired; the stateful corpus stays in `willow-2.0/core/jeles_sources.py` | `integrations.py` `JelesAdapter` | product decision: keep remote, or lift corpus **[needs 2.0 source]** |
| G-6 | **Grove / dreams subsystems** | **not present**; `Grove` MCP server requires separate auth | `product-layout.md` §5, `session-lifecycle.md` §9 | scope decision — see §3 |

**Recommended order:** G-2 → G-1 first (both are pure willow-mcp work with
designs in hand; G-2 unblocks the whole envelope story and only needs an
operator decision). G-3/G-4 move together once the schema is ratified. G-5/G-6
are scope calls, not plumbing.

---

## 3. Deliberate non-goals (NOT migration targets)

`session-lifecycle.md` §9 and §12 record these as intentional divergences.
willow-mcp replaced the mechanism, it did not fail to port it. Listing them so
"get everything over" does not accidentally sweep them back in:

- **fylgja hooks** — `session_start.py`, persona picker, boot-done flags, Grove
  daemons. willow-mcp uses **"packet is boot"** instead. Fleet-internal.
- **Session-scoped named-agent daemons** — replaced by "any MCP client +
  manifest `app_id`".
- **Charter `ORIENT.md`** — stays in the charter repo; product must **not**
  overwrite it (`product-layout.md` §6).
- **`envelopes/pre-approved.json` as an authority grant** — willow-mcp uses
  `persona_envelopes`/manifest with different semantics; do not import blindly.

If the operator *does* want any of these lifted, that is a new scope decision,
not a gap to close silently.

---

## 4. Cross-repo blockers (fix lives in willow-2.0)

These are open in `docs/BUGS.md` because the defective writer is willow-2.0 code.
willow-mcp already reads fail-closed around each; full state/network **severance**
is what waits on the 2.0 side.

| Bug | What | Why it blocks "everything over" |
|---|---|---|
| **B-31** (P1) | `global_settings.py` consent writer **fails open** (`DEFAULT_CONSENT` all-`True`) | willow-mcp reads fail-closed independently, but a shared consent file is still written permissively by 2.0 |
| **B-35** (P1) | Metered envelopes are **unmetered** — `envelope_citation` is never written anywhere in willow-2.0, so `max_count`/`EDQUOT` enforce nothing | verb 13 `envelope.apply` (licenses the orchestrator seat) is `enforced_by: null` |
| **B-28** (P3) | `completed_at` stays null on **failed** tasks — shared fleet Postgres trigger only fires on `completed` | operator-gated `ALTER` on shared DB; willow-mcp's own `mark_done` is already correct |
| **B-32/33/37/38** | egress / severance surface | mostly **mitigated** in willow-mcp (leases, closed sandbox lane); residual fixes are deployment-gated (`chown` + `WILLOW_MCP_STRICT_TRUST_ROOT=1`) or blocked on B-37 |
| **B-36** (P2) | `gap_*` / `kb_startup_continuity` gate-denied to `app_id=willow`; the `gaps` collection nonetheless lives in the **fleet** store under `$WILLOW_HOME` | store/DB **severance** must land before this dissolves |

**Severance is the real finish line.** B-36/B-38 both point at the same root:
willow-mcp and willow-2.0 still share `$WILLOW_HOME` (store, consent, KB). "Get
everything over" ultimately means willow-mcp owning its own state root so the
fleet is a genuine *optional overlay*, not a shared substrate.

---

## 5. Stale docs to reconcile (housekeeping)

Not migration work, but these mislead anyone reading the gap:

- `docs/design/kart-productionization.md` — "not yet started" → **superseded**; Kart shipped as `kartikeya` (B-22).
- `docs/design/kart-lift-spec.md` — "stage 5 deferred" language predates the `kartikeya` extraction; mark stages 1–4 done.
- Any `pip install willow-mcp[worker]` reference — the `[worker]` extra never existed (B-27); `kartikeya` is a hard dep.

---

## 6. Suggested migration checklist

```
[ ] G-2  Ratify permissions matrix → enforce role envelopes in gate.py    (unblocks the envelope story)
[ ] G-1  Build SOIL DAG + dag_next / dag_status / status_report           (S6; design exists)
[ ] --   Ratify schema-adaptation §§1–5
[ ]  └ G-3  Consent leases (issue/check)
[ ]  └ G-4  Canonical identity (§6.2)
[ ] SEV  Give willow-mcp its own $WILLOW_HOME state root                   (dissolves B-36, advances B-38)
[ ] G-5  Decide: keep Jeles remote-only, or lift the corpus half          [needs 2.0 source]
[ ] G-6  Decide: Grove/dreams in scope, or permanent non-goal
[ ] DOC  Mark kart-productionization.md / kart-lift-spec.md superseded
[ ] 2.0  Cross-repo: fix B-31 consent writer, B-35 envelope metering       (willow-2.0 side)
```

---

*Draft 0.1 — 2026-07-18. Reconciled against BUGS.md, CHANGELOG.md, and the live
69-tool surface. Tool-count and Jeles/Grove items marked **[needs 2.0 source]**
could not be diffed against willow-2.0 in this sandbox.*
