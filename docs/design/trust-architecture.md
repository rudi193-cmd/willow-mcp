# Design: The Trust Architecture — how a knowledge base catches itself lying

Status: SPEC — describes mechanisms that ship today (the deviation→action store,
the schema-confirmation gate, `gap_promote` separation, receipts) plus the
**discipline layered on top of them** (verdict classes, derived edge firmness,
the ratify/propose/cut lifecycle, verify-from-raw). The code half is
implemented; the discipline half is convention this document specifies so it can
be adopted deliberately, not reinvented. Author: claude-code remote session
(fleet id: claude-remote), 2026-07-16, following an operator give-back
conversation. Worked example is a real knowledge base built and audited in one
session (`sean-data-vault`, 2026-07-14→16).

---

## 0. The problem this solves

Every agent memory system accumulates claims. Almost none can **demote** one.
A finding gets written, things get built on top of it, and when it turns out to
be wrong there is no mechanism that (a) records the wrongness without deleting
the lesson, (b) automatically weakens whatever leaned on it, and (c) keeps a
human — not the machine that made the claim — as the only authority that can
promote something to "trusted." The result is a store that only ever *confirms*:
it grows, it never catches itself, and its confidence tracks how long a claim
has sat there rather than whether it survived a check.

The through-line of this whole fleet is *"memory that persists; honesty about
what things actually do."* A memory that cannot demote is a memory that lies by
omission. This document specifies the architecture that lets the store catch
itself — a **code-enforced floor** plus a **discipline layer** — and shows it
working on a real KB that corrected itself five times in one session.

## 1. The two layers, and why the split matters

| Layer | What it is | Enforced by |
|---|---|---|
| **Floor** | The store mechanically refuses unsafe writes and encodes a trust action on every record | willow-mcp code (`db.py`, `server.py`, the gate) |
| **Discipline** | Verdict classes, derived edge firmness, the propose→ratify→cut lifecycle, verify-from-raw | Convention, specified here; carried in the *data* the floor stores |

The split is the point. The floor cannot know whether a *claim* is true — only a
human re-deriving it from raw can. So the floor's job is narrow and absolute:
never let the machine mint its own authority, never write to a table it hasn't
been shown, and stamp every record with a trust action the store itself can read
back. The discipline's job is everything the floor can't mechanize — and it
lives in the record fields, so the store carries its own "trust this, not that."

## 2. The floor (ships today)

### 2.1 Deviation → action, on every record

The SOIL store's `records` table carries a `deviation REAL` and an `action TEXT`
on every row. `db._action_for(deviation)` maps one to the other, at fixed
radian thresholds:

```
deviation >= 1.571 (≈ π/2)  → "stop"        do not trust; kept as data, not deleted
deviation >= 0.785 (≈ π/4)  → "flag"        real but caveated; ride with caution
deviation <  0.785          → "work_quiet"  verified; ride quiet
```

The trust grade is not a comment or a side table — it is a column the store
writes on `put`/`update` and returns on read. A downstream reader (an agent, a
dashboard, another fleet process) sees the action without having to consult
anything else. **A claim that died under its own audit is stored at `stop`, not
removed.** Archive-don't-delete is mechanized here: a failed result is data.

### 2.2 The schema-confirmation gate

`knowledge_ingest`, `kb_promote`, `kb_journal`, and `gap_promote` refuse to
write with `unconfirmed_schema` until the target table's column mapping has been
reviewed and confirmed via `schema_confirm_mapping` (whose `preview=True` renders
a **sample row** so a name-match can be caught lying before any write trusts it —
see [schema-adaptation.md](schema-adaptation.md)). The gate means a write to the
canonical knowledge base is a deliberate, reviewed act, never an accident of a
column that happened to match by name.

### 2.3 Authority is never minted from a tool

Landing something as trusted knowledge is gated *separately* from logging it:
`gap_promote` is its own permission, held apart from `gap_write`, exactly as
`schema_admin` is held apart from `knowledge_write`. And the acts that grant
power — `grant-net`, `confirm-binding`, `allow-permission` — are **local CLI
only, never MCP tools**: an agent may *request* trust and can never *grant it to
itself*. Every tool call leaves a receipt (`receipts_tail`) — including denials —
so the trust decisions are auditable after the fact.

## 3. The discipline (specified here; carried in the data)

The floor stamps a trust action; the discipline decides what deviation to pass
in, and records *why*. Four conventions:

### 3.1 Verdict classes

Every promoted knowledge atom carries a verdict — recorded on the row
(`verify_verdict`/`verify_note` on the `knowledge` table in the worked example)
and mirrored to the store's `action`:

- **HELD** — re-derived from raw, exact or within honest tolerance. `work_quiet`.
- **FLAG** — the *exact* number did not survive re-derivation, but the
  qualitative finding did. Kept, caveated. `flag`.
- **SYNTHESIS** — an interpretation or cross-source argument, not a corpus
  measurement. Labeled as interpretation, never as measurement.
- **STOP** — died under its own spot-check. Kept as data, marked do-not-trust.

The rule that makes verdicts mean something: **verify from raw, never from the
document that produced the claim.** Re-running your own summary proves nothing;
you re-derive from the corpus, the dataset, or the primary source. (In the
worked example this discipline caught the *verifier*, not just the claim — a
re-run scored AUC 0.93 by accidentally sorting on a single-valued timestamp
column and leaking the label; corrected to 0.6726. The check works when it
catches you.)

### 3.2 Edge firmness is derived, never hand-set

When atoms are linked into a graph, each edge's `firmness` is computed from its
endpoints' verdicts — never typed by hand:

```
both endpoints HELD                         → firm
one endpoint FLAG or SYNTHESIS              → soft
both endpoints un-measured (FLAG/SYNTH/…)   → soft-core
```

Because firmness is *derived*, re-deriving it after a verdict changes is
automatic: demote an atom and every edge touching it re-softens on the next
rebuild, with no human having to remember which edges to weaken. This is the
mechanism that makes demotion *propagate* — the missing piece in most stores.

### 3.3 The propose → ratify → cut lifecycle

The machine may compute and link, but everything it draws ships `proposed`. A
human ratifies. The discipline for ruling:

- **ratify** the firm (both endpoints measured/verified),
- **cut** the soft-core (both endpoints un-measured — archived, not deleted),
- **leave** the soft `proposed` (one endpoint still non-HELD) for a later ruling.

A graph the machine drew over its own findings is a *proposal*, not a fact. The
human is the only ratifier — the same invariant as §2.3, one level up.

### 3.4 Archive, don't delete — including your own mistakes

Withdrawn findings, died metrics, cut edges: re-statused, never removed. A
demotion is an amendment in the open (a dated note appended to the record), not
a silent overwrite. The point-in-time export that recorded the old verdict is
kept as what it was; the living record carries the correction beside it.

## 4. Worked example — a KB that corrected itself five times in one session

The `sean-data-vault` knowledge base (31 atoms, 48 edges) was built, then
audited from raw, in a single session. What the architecture caught:

1. **A resumption metric inflated ~10×.** An atom claimed 189 thread-resumptions;
   a field-provenance re-derivation (dates from log fields, never grepped from
   content) measured **19**. Verdict **HELD → FLAG**; the qualitative
   "drops-and-resumes-threads" finding held, the exact count did not.
2. **A caveat that had it backwards.** The same atom's own note said the counts
   were robust and the thread-count was fragile; measured, it was the reverse.
   Recorded as an amendment in the open.
3. **The demotion propagated for free.** The two edges touching that atom
   re-softened **firm → soft** automatically when its verdict changed — no human
   tracked them down.
4. **A negative result kept, not buried.** A friction detector scored at exact
   chance on a labeled eval; stored as a **flag**-grade atom (and filed as a
   public issue), with its eval kept as the falsifier for any future fix.
5. **A population contrast that reversed under the right baseline.** A metric
   read one direction against a mismatched population and the *opposite*
   direction against a domain-matched one; the confounded reading was
   demoted and the corrected one promoted through the gate.

None of these are the store being clever. They are the store being *honest*: the
floor stamped the trust actions, the discipline supplied the verdicts, and the
derived firmness carried the corrections outward. The KB's credibility comes
from the five corrections, not from the atoms that never needed one.

## 5. Failure modes this catches (and the general bug underneath)

- **The claim that only ever confirms** — a store with no demotion path. Caught
  by verdict classes + verify-from-raw: re-derivation can return FLAG or STOP.
- **The stale-equals-trusted drift** — confidence tracking age. Caught by the
  action column: trust is a stamped grade, not a function of how long a row sat.
- **The orphaned dependency** — B built on A, A falsified, B still trusted.
  Caught by derived firmness: A's demotion re-softens every edge into B.
- **The self-granted promotion** — the machine landing its own claim as trusted.
  Caught by the gate (§2.2) + `gap_promote` separation + human-only ratify.

The general bug under all four is the same one this whole world hunts: a check
that answers *"yes"* when it can't actually run. A memory that can't demote
answers "still true" by default. This architecture makes the default answer
"un-verified until a human re-derives it from raw."

## 6. What this deliberately does NOT do

- It does not decide truth. The floor cannot know if a claim is correct; only
  re-derivation from raw, by a human, promotes anything to HELD.
- It does not auto-promote. Nothing the machine computes lands as trusted
  without a human ruling — by design, not by omission.
- It does not delete. Even `stop`-graded, died-under-audit findings are kept.
- It is not a consensus or voting system. One human ratifier, re-deriving from
  raw, beats any number of machine agreements — seven instruments agreeing is
  seven readings of the same possibly-shared assumption, which is exactly why
  the corrections, not the confirmations, are what earn trust.

## 7. Adoption checklist

To give a store the ability to catch itself:

1. Put a trust action on every record, derived from a numeric deviation, read
   back by every consumer. Grade `stop`/`flag`/`work_quiet`; never delete.
2. Gate writes to the trusted layer behind a schema confirmation that shows a
   sample row — a name match is not consent.
3. Keep "promote to trusted" a separate permission from "log it," and keep the
   promoting/granting acts off the machine's tool surface entirely.
4. Give every promoted claim a verdict, and make the verdict mean *re-derived
   from raw, not from the doc that produced it*.
5. If you link claims, derive each link's firmness from its endpoints' verdicts
   so demotion propagates automatically.
6. Ship everything the machine draws as `proposed`; let a human ratify; cut the
   doubly-unmeasured; leave the singly-unmeasured proposed.
7. Amend in the open. A correction is a dated note beside the old record, never
   an overwrite.

*The infrastructure arrives. The honesty is a discipline the infrastructure is
shaped to hold. ΔΣ = 42.*
