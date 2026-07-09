# ARCHITECT.md

How the maintainer of this repo builds, and what to honor when you build in
it. Written by an agent from working sessions — a living document, grown one
honest ring at a time, never assumed. If something here is wrong, correct it;
a wrong parts diagram gets you the wrong part.

This is a *method* profile, not a personnel file. It exists so an agent
picking up the fleet works *with* the grain instead of against it.

## The one thing that ties it together

**Parts book, not service manual.** A service manual gives you the procedure —
step 1, step 2, torque to spec, trust the sequence. A parts book gives you the
*structure* — every component, exploded, and how they fit. This maintainer
works from the parts book. He learns a system by taking it apart, comparing it
against how it's actually composed, and reassembling it with the whole model in
his head — not by following anyone's prescribed steps.

Everything below is a consequence of that one instinct. Roots are in hardware
and mechanical restoration (machines built to be *owned and repaired*, kept
running long after the vendor stopped caring), and it shows: the code has a
craftsman's structural sense, and a deep suspicion of any diagram that lies
about the machine.

## Working principles (honor these)

1. **Introspect, don't assume.** Open the thing up and look. `record_lessons()`
   reads an unfamiliar table by introspecting it — "a 2004 schema owes the
   present nothing." Don't hardcode what you can discover. Don't trust the
   label over the contents.

2. **Extract to clean parts.** The fleet is one machine deliberately exploded
   into orderable components — auth (`openclaw-sap-gate`), memory
   (`willow-mcp`), the executor (`kartikeya`), design tokens (`safe-design`).
   The rule that produced them: *a shared concern trapped inside something
   heavy gets lifted into a stdlib-minimal core that everything can depend on
   cleanly.* "Tokens do not import render engines. Render engines import
   tokens." When you see that shape, preserve it; when you add, ask what the
   clean part is.

3. **Fail closed.** Gates deny on missing/ambiguous/broken input, never permit.
   The anti-pattern to hunt and kill is the quiet fail-*open* — a default that
   resolves to "yes" when something breaks. If a safety check can't run,
   the answer is no.

4. **Archive, don't delete.** Soft-delete over hard-delete. Bug-ledger rows are
   never removed, only re-statused. Stale and withdrawn findings are *kept* as
   lessons. The grove's lesson store is unbounded on purpose: vocabulary can be
   pruned cheaply, lessons cannot. Nothing worth remembering gets dropped
   without explicit instruction.

5. **Never overclaim.** Docs, docstrings, and schemas must not claim behavior
   the code doesn't have — this is the founding rule and the one most worth
   guarding, because it's the easiest to let drift. A whole PR once existed
   only to stop a docstring from advertising a kill switch that wasn't there.
   Prefer to *verify live* (drive the real flow, watch it work) over asserting
   it works.

6. **One implementation, no drift.** Two front ends share one tested dispatch
   module. One token resolves through one converter so backends can't disagree.
   Aliases resolve at lookup, never at definition. If a fact can live in two
   places, it will eventually contradict itself — so it lives in one.

7. **Authority is never minted from a tool (the sudo invariant).** Actions that
   grant power — leases, permission toggles, identity bindings — are
   local-CLI-only, never MCP tools. The human ratifies; the machine proposes.
   Dual-commit is the oldest rule in the lineage and it still holds.

## Texture worth matching

- **Local-first, consent-first, sovereign by default.** No ports, no mandatory
  accounts, data stays on hardware the operator controls. Design as if the
  vendor will vanish and the machine must keep running anyway.
- **The poetry is load-bearing — and so are the tests.** Modules carry
  narrative (rings, canopy, personas, Norse/arboreal naming). It's not
  ornament; it's how this builder thinks in structure. Match the register when
  it's there, but never let it substitute for a passing suite. Hundreds of
  tests sit under the story.
- **Long-haul maintainer.** Stays with things. Builds for the *next* gardener,
  not just today — "the tree does not require you to remember planting it."
  Favor legibility and succession over cleverness.
- **Plain-spoken collaboration.** States the task plainly, hands you the wheel,
  expects you to figure out the rest and report honestly — including when
  something failed or was skipped.

## Provenance

Started 2026-07-09 by Claude Code, distilled from working sessions. Method and
light background only — by design it carries no contact details or personal
history. Expect gaps; correct freely. First ring.
