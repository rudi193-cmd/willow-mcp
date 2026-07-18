#!/usr/bin/env python3
"""Seed pack — the provenance of *this* willow's build, as lineage atoms.

Kept OUT of the agent-neutral base on purpose (lineage.py: "willow's specific
history, if it ships at all, is a separate seed/lore pack"). This is content, not
mechanism: real atoms about how willow-mcp's willow-gate authorization seam was
built, each answering a question an agent will actually ask and citing a real
artifact (a PR, a commit, a file, a design-doc section). Discipline enforced by
Lineage.record: no rationale or no evidence → refused.

Run it against the live willow-mcp store (the one WILLOW_STORE_ROOT points at):

    python seed/lineage_willow.py            # seed + print a sample `why`
    python seed/lineage_willow.py --dry-run  # show what would be written

Idempotent: every atom has a stable slug and every edge a composite id, so
re-running (or extending ATOMS and re-running) never duplicates. It writes ONLY
the `lineage` and `lineage_edges` collections — never anything else, never a
personal-data vault.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from willow_mcp.db import Store          # noqa: E402
from willow_mcp.lineage import Lineage   # noqa: E402


# Each dict is kwargs to Lineage.record. supersedes / derived_from / motivated_by
# are lists of atom slugs (or any external node id). The graph they form is the
# point: `why` walks supersedes for decision history, and reads derived_from /
# motivated_by for "where from" and "why now".
ATOMS: list[dict] = [
    # ── foundations ──────────────────────────────────────────────────────────
    dict(
        id="willow-gate-seam",
        title="The willow-gate ↔ willow-mcp seam",
        rationale=("willow-mcp's entire ACL trusted the `app_id` argument as honest; "
                   "in stdio it is just a string any caller can type. The seam adds an "
                   "agent-side identity binder — an HMAC over a signed header, the secret "
                   "held by the gate, the claimed trust capped at a registered ceiling — so "
                   "'which agent is calling' becomes provable, not asserted."),
        origin="a runnable spike that mapped the two systems and attacked the bridge before any wiring",
        authority="operator (Sean) — 'bring in willow-gate'",
        evidence=["docs/design/willow-gate-seam.md", "PR #101"],
        tags=["auth", "willow-gate", "identity", "seam"],
    ),
    dict(
        id="sudo-invariant",
        title="The sudo invariant — request and confirm are separate authorities",
        rationale=("An agent may REQUEST egress, a grant, or a trust change; it may never "
                   "CONFIRM one itself. Minting manifests, leases, secrets, and trust "
                   "ceilings stays CLI/operator-only, and admin-tier (Elder) is NOT sudo. "
                   "This is the line every gate and hook in willow defends."),
        origin="FRANK 90e52ab7",
        authority="operator invariant",
        evidence=["hooks/pre_tool_use.py", "gate.py PERMISSION_GROUPS", "FRANK 90e52ab7"],
        tags=["auth", "sudo", "invariant", "security"],
    ),
    dict(
        id="appid-only-binding",
        title="app_id-only identity (the original, unbound model)",
        rationale=("Before the seam a tool call carried only `app_id` as plaintext, so a "
                   "caller passing app_id=operator rode operator's authority with no proof "
                   "of its own. Recorded so an agent understands what the binding replaced "
                   "and why app_id alone must never be trusted for authorization."),
        origin="willow-mcp v2 stdio ACL",
        authority="superseded",
        evidence=["docs/design/willow-gate-seam.md §H1 (APPID_ONLY = HOLE)"],
        tags=["auth", "identity", "h1", "archived"],
    ),
    # ── the three holes ──────────────────────────────────────────────────────
    dict(
        id="h1-per-call-signed",
        title="H1 — per-call SIGNED HMAC credential",
        rationale=("A bound session alone does not tie a given CALL to it — a bearer token "
                   "closes the ride but replays for any later call. Only a per-call HMAC over "
                   "(session_id|app_id|tool|call_nonce), riding the request's out-of-band "
                   "`_meta`, closes ride AND replay AND tamper. The client harness signs; the "
                   "model never sees the secret."),
        origin="the H1 spike, attacking appid-only / bearer / signed with ride, replay, tamper",
        authority="settled by spike",
        evidence=["docs/design/willow-gate-seam.md §H1", "session_binder.py", "signing.py"],
        tags=["auth", "identity", "h1", "hmac"],
        supersedes=["appid-only-binding"],
        derived_from=["willow-gate-seam"],
    ),
    dict(
        id="h2-authorize-in-gate",
        title="H2 — the tier ceiling must BE _gate, not sit beside it",
        rationale=("If the tier check runs anywhere but inside the single `_gate` funnel, "
                   "willow-gate is a ledger not a gate — a call reaching a tool another way is "
                   "neither prevented nor recorded. So the ceiling is applied inside `_gate` "
                   "after `permitted()`: effective = manifest ∩ tier."),
        evidence=["docs/design/willow-gate-seam.md §H2", "server.py _enforce_binding_gate", "tier_policy.py"],
        tags=["auth", "tier", "h2"],
        derived_from=["willow-gate-seam"],
    ),
    dict(
        id="h3-reconcile-from-receipts",
        title="H3 — reconciliation fed from the receipt log",
        rationale=("Check-out's declare-vs-did diff only sees tools that passed the gate. If "
                   "`tools_used` comes from anywhere but the ReceiptLog it silently passes on "
                   "out-of-band use. The agent declares the tool CLASSES it did; the server "
                   "diffs that against the DISTINCT ok-receipts — the ground truth the agent "
                   "cannot feed."),
        evidence=["docs/design/willow-gate-seam.md §H3", "session_binder.reconcile", "receipts.distinct_tools"],
        tags=["auth", "reconcile", "h3"],
        derived_from=["willow-gate-seam"],
    ),
    # ── the settled decisions ────────────────────────────────────────────────
    dict(
        id="d1-tier-group-map",
        title="D1 — trust tier ↔ permission-group map (the ceiling)",
        rationale=("willow-gate tiers unlock coarse CLASSES (read/write/execute/admin) "
                   "cumulatively; willow-mcp has fine-grained groups. Do not collapse them — "
                   "intersect: expand(manifest) ∩ groups(tier). Egress stays double-gated, "
                   "store_purge stays write-class (it is reversible), and admin never reaches "
                   "authority."),
        evidence=["docs/design/willow-gate-seam.md D1", "tier_policy.py TOOL_CLASS"],
        tags=["auth", "tier", "d1"],
        derived_from=["h2-authorize-in-gate"],
    ),
    dict(
        id="d2-keystore",
        title="D2 — the identity keystore (secrets outside mcp_apps/)",
        rationale=("Per-agent secrets live in $WILLOW_HOME/gate/ (0600 keys, 0700 dir) "
                   "OUTSIDE mcp_apps/ so no store/list tool can even enumerate them, while the "
                   "ceiling registry stays auditable. register/rotate/revoke are CLI-only and "
                   "blocked in the PreToolUse guard — an agent never writes its own secret."),
        evidence=["docs/design/willow-gate-seam.md D2", "agent_registry.py", "hooks/pre_tool_use.py _KEYSTORE_RE"],
        tags=["auth", "keystore", "d2", "sudo"],
        derived_from=["h1-per-call-signed"],
        motivated_by=["sudo-invariant"],
    ),
    dict(
        id="d3-opt-in",
        title="D3 — enforcement is opt-in (two locks)",
        rationale=("Turning binding on before a registered agent's client can sign would "
                   "brick it. Two locks: the WILLOW_MCP_ENFORCE_BINDING env switch (off by "
                   "default = observe-only) AND per-agent registration (an unregistered app "
                   "stays manifest-only). So a plain local clone is unchanged and the cutover "
                   "is deliberate and reversible."),
        evidence=["docs/design/willow-gate-seam.md D3", "server._enforce_binding"],
        tags=["auth", "opt-in", "d3"],
        derived_from=["h2-authorize-in-gate"],
    ),
    dict(
        id="d5-vendor-pure",
        title="D5 — vendored / pure, no python-gnupg dependency",
        rationale=("Every shipped piece (friction_floor, agent_registry, session_binder, "
                   "tier_policy, announce) is stdlib-only. willow-gate's PGP-encrypted ledger "
                   "is left as a pluggable announce.set_sink(), so the agent-neutral base never "
                   "takes on python-gnupg."),
        evidence=["docs/design/willow-gate-seam.md D5", "announce.py set_sink", "friction_floor.py"],
        tags=["auth", "vendoring", "d5"],
        derived_from=["willow-gate-seam"],
    ),
    dict(
        id="read-universal-policy",
        title="Read-universal does NOT survive the seam",
        rationale=("willow-gate grants read to everyone (even Exiled); willow-mcp fail-closes "
                   "an unmanifested/unscoped app_id and store_scope confines. Bringing in "
                   "willow-gate does NOT make willow-mcp reads universal — this was chosen, not "
                   "inherited, so a downstream binder never guesses the read semantics."),
        evidence=["docs/design/willow-gate-seam.md (Policy hole)", "gate.store_scope"],
        tags=["auth", "read", "policy"],
        derived_from=["willow-gate-seam"],
    ),
    # ── the phases ───────────────────────────────────────────────────────────
    dict(
        id="phase1-friction-floor",
        title="Phase 1 — friction-floor relationship watcher",
        rationale=("A model-free, deterministic detector: it flags when agent turns sit below "
                   "a friction floor WHILE the user escalates (sycophantic mirroring). A SIGNAL "
                   "not a verdict; it never blocks, never egresses, and must run OUTSIDE the "
                   "model it watches — a mirror cannot audit itself."),
        evidence=["CHANGELOG 2.0.0", "friction.py", "commit 58a4dcc"],
        tags=["friction", "relationship", "phase1"],
        derived_from=["willow-gate-seam"],
    ),
    dict(
        id="phase2-observe-binding",
        title="Phase 2 — observe-only identity binding",
        rationale=("Ship the binding mechanism (register + check_in + verify_call) wired to "
                   "LOG the bound tier, not enforce — so the binding can be watched in receipts "
                   "before it can lock anyone out. Observe-first, on purpose."),
        evidence=["commit 8cb4f5a", "agent_registry.py", "session_binder.py"],
        tags=["auth", "identity", "phase2"],
        derived_from=["h1-per-call-signed"],
    ),
    dict(
        id="phase3-tier-enforcement",
        title="Phase 3 — tier ceiling enforced",
        rationale=("Flip the observed binding into a control: _enforce_binding_gate inside "
                   "_gate applies the D1 ceiling, fail-closed, for a registered agent presenting "
                   "a valid per-call credential. Off by default (D3)."),
        evidence=["commit 53ca669", "tier_policy.py", "server._enforce_binding_gate"],
        tags=["auth", "tier", "phase3"],
        derived_from=["h2-authorize-in-gate", "d1-tier-group-map"],
    ),
    dict(
        id="phase4-reconciliation",
        title="Phase 4 — session reconciliation (check-out)",
        rationale=("A declare-vs-did diff at check-out, tools_used sourced from the receipt "
                   "log; only a PRIVILEGED discrepancy makes a session unclean (read is "
                   "ambient). It records, never blocks the handoff."),
        evidence=["commit 604f7be", "session_binder.reconcile"],
        tags=["auth", "reconcile", "phase4"],
        derived_from=["h3-reconcile-from-receipts"],
    ),
    dict(
        id="phase5-announcement",
        title="Phase 5 — graduated announcement volume",
        rationale=("A policy OVER the receipt log, not a second log: how loudly each decision "
                   "is surfaced, graduated by bound tier (louder for the less trusted; every "
                   "denial escalated). Pure; the PGP ledger is a pluggable sink."),
        evidence=["commit a29344c", "announce.py"],
        tags=["audit", "announcement", "phase5"],
        derived_from=["d5-vendor-pure"],
    ),
    # ── review, fixes, proof, upstream ───────────────────────────────────────
    dict(
        id="review-hardening",
        title="Adversarial review hardening",
        rationale=("A four-reviewer audit found real defects: three fail-opens (a broken-"
                   "keystore downgrade, an unreadable nonce store, check-in), an announcement "
                   "secret-leak, and a cross-agent check-out (session-destroy + audit-forgery). "
                   "All fixed fail-closed. The lesson: an auth path must be ATTACKED, not just "
                   "tested."),
        origin="four parallel adversarial reviewers over the seam diff",
        evidence=["commit 5a07399"],
        tags=["auth", "review", "security"],
        motivated_by=["phase3-tier-enforcement"],
    ),
    dict(
        id="whoami-identity-fix",
        title="whoami / diagnostic_summary cross-identity disclosure closed",
        rationale=("whoami and diagnostic_summary are ungated (they must answer with an empty "
                   "manifest), so in stdio a caller could read ANY app_id's config. Under "
                   "enforcement they now require the caller to prove it owns the app_id "
                   "(_own_identity_denial) — consistent with how _gate treats every tool."),
        evidence=["commit b741c45", "server._own_identity_denial"],
        tags=["auth", "disclosure", "review"],
        motivated_by=["review-hardening"],
    ),
    dict(
        id="signing-harness",
        title="Client signing harness + end-to-end proof",
        rationale=("The client half (SigningClientSession) holds the secret and signs every "
                   "call; the model never sees it. Proven against a REAL server — a signed call "
                   "passes, an unsigned one is denied, an over-tier tool is denied, and check-out "
                   "reconciles clean — closing the 'never run end to end' gap the review named."),
        evidence=["PR #102", "signing.py", "examples/signing_client.py", "tests/test_signing_e2e.py"],
        tags=["auth", "identity", "harness", "h1"],
        derived_from=["h1-per-call-signed", "phase3-tier-enforcement"],
    ),
    dict(
        id="entry-allowed-fix",
        title="willow-gate entry_allowed enforced upstream (#12)",
        rationale=("entry_allowed was dead code, leaving Exiled and Rookie behaviorally "
                   "identical. Fixed upstream: entry_allowed gates session CREATION, so Exiled "
                   "(level 0) is refused at check-in — matching willow-mcp's binder, which "
                   "already denied Exiled. Read-universal for a true outsider is simply not "
                   "gate-mediated."),
        origin="found while prototyping the seam; filed as willow-gate#12",
        evidence=["willow-gate PR #13", "willow-gate issue #12"],
        tags=["auth", "willow-gate", "upstream", "exiled"],
        motivated_by=["h1-per-call-signed"],
    ),
    dict(
        id="lineage-atoms",
        title="Lineage / provenance atoms (this store's own story engine)",
        rationale=("Agents dropped into a running willow keep asking where things came from. A "
                   "knowledge record answers 'what is true'; a lineage atom answers PROVENANCE "
                   "— disciplined nodes (rationale + evidence, cite-or-refuse) plus typed edges "
                   "(supersedes / derived_from / motivated_by). This atom is itself an example, "
                   "and this seed pack is its first real content."),
        evidence=["lineage.py", "PR #101", "seed/lineage_willow.py"],
        tags=["lineage", "provenance", "memory"],
        derived_from=["willow-gate-seam"],
    ),
]


def seed(dry_run: bool = False) -> int:
    store = Store()   # WILLOW_STORE_ROOT — the live willow-mcp store
    lin = Lineage(store)
    print(f"target store root : {store.root}")
    print(f"collections       : {lin.collection!r} (nodes), {lin.edges!r} (edges)")
    print(f"atoms to seed     : {len(ATOMS)}")
    if dry_run:
        for a in ATOMS:
            print(f"  would record  {a['id']}")
        return 0

    recorded, edges = 0, 0
    for atom in ATOMS:
        out = lin.record(**atom)
        if out.get("error"):
            print(f"  REFUSED {atom['id']}: {out['error']} — {out.get('detail')}")
            continue
        recorded += 1
        edges += len(out.get("edges", []))
    print(f"\nrecorded {recorded}/{len(ATOMS)} atoms, {edges} edges "
          f"(idempotent — re-running writes the same rows).")

    # Show it working: a `why` with a real supersedes chain + tag-siblings.
    demo = lin.why("h1-per-call-signed")
    print("\n── why 'h1-per-call-signed' ──")
    print(demo["answer"])
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Seed willow's build-provenance lineage atoms.")
    p.add_argument("--dry-run", action="store_true", help="list atoms without writing")
    raise SystemExit(seed(dry_run=p.parse_args().__dict__["dry_run"]))
