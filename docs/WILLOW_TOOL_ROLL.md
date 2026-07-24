# The Willow Tool Roll

*What this monolith of a session produced, curated the way you'd roll a tool bag:
grouped in the order you reach for it, weighted toward what this build actually
needs, split by stage, structural joints respected — not ground down for
convenience.*

Built from session `evening-chat-i5i6tr` (2026-07-24). Excludes the DBs and KBs
themselves — those ride in the vault. This is the **tooling**, not the cargo.

---

## The build, stated plainly

Three eras of hardware in one machine — Windows-era `willow_knowledge.db` →
`willow-2.0` → `willow-mcp` / vault — exactly like a VBB frame wearing a PX fork
and a P200 motor. That's why the roll has to be comprehensive: the fasteners
come from different decades. And it's a *tuned* build — sealed memory, lineage,
ratification — so the roll is weighted toward the seal/verify kit the way a
reed-valve motor's roll is weighted toward plugs and jets.

---

## ROLL A — the bench roll (cold start: rebuild the box from the vault)

*Reach for this when the container's been reclaimed and you're rebuilding the KB
layer from `sean-data-vault`. The heavy, era-spanning sockets.*

**Reconstruction recipe** — the missing half of the vault's `restore-and-wire.sh`
(which only rebuilds the SOIL store; these rebuild the Postgres KB layer):
- `load_willow19.sh` — 229k corpus load (pgvector, part-file concat, `\restrict` strip, `ON_ERROR_STOP=0`)
- `load_0723.sh` — curated 48-atom KB load
- `complete_0723.sh` — aux-table schema completion (give a bare KB the full willow-mcp table set)
- `build_both.sh` — **the union-VIEW DDL**: the canonical normalization that folds corpus columns into `id/content/domain/source/tags`. This is a *schema decision*, not a script.
- `fix_view.sh`

**Schema probes** — the mixed 13/22/24 mm sockets for reading legacy hardware:
- `inv.py` — table inventory across every vault DB (Windows-era → 2.0 → mcp)
- `schema.py` — schema fingerprint of the legacy stores
- The confirmed canonical field-map (`id/content/domain/source/tags`) as documented DDL

---

## ROLL B — the ride roll (live session: seal, verify, lineage)

*The plug-and-jet kit you reach for every session doing memory work.*

**Ratification tooling** — the seal-and-verify workflow:
- `dump_seals.py` — pull `verification_status=verified` findings out of a SOIL store
- `verify_seal.sh` / `verify_batch.sh` — confirm a seal landed in the writable head
- `snapshot_edge.py` — date-stamp a lineage snapshot from the live store
- `pick_and_check.py` — spot-check a sealed atom against source

**The ratification record template** — the most valuable single item, because it's
the *structure* everything else clamps to:
- atom shape: `kind / statement / source / sealed / ratified_by / ratified / round / topic`
- lineage-edge convention (typed edge, cited evidence, points *into* the substrate)
- gap-record shape (`topic / question / asked_count`, resolve with reopen-conditions)

**Diagnostics** — read-only, the "check the plug color" tools:
- `kb_stats.sh`, `soil_gaps.py`, `corpus_map.sh`

---

## The structural joints — route around, don't grind

*The welded fork taught this: a load-bearing joint is not a place to cut a
shortcut, no matter how much easier the routing would be.*

- **The seat model (manifest ACL) is structural.** When the willow seat was denied
  `gap_read` tonight, the right move was to *route around it* — ask the operator,
  respect the wall — not grind it down.
- `registry_grant.py` is the grinder. It self-grants `store_write / knowledge_write /
  lineage_write / schema_admin` straight into the seat — the exact anti-pattern the
  new `pre_tool_use` seat-escalation guard now blocks. **It is deliberately NOT in
  the roll.** Persisting it would be archiving the thing we just outlawed.
- `subject_consent` and the byte-identical hook copies are welded joints too:
  shared cores, load-bearing, not to be forked casually.

## Inspect the welds

*The custom fork earns a periodic crack-check. So do the custom joints here.*

- `test_authority_surface.py` — the byte-parity check between the repo hook and the
  bundled hook **is** the weld inspection. It's what caught tonight's CI red. Run it
  every time the hook changes.
- Guarantee-as-adversarial-test: every promise mapped to a test that goes red when
  the promise breaks. That's the crack you *want* to find on the bench, not the road.

## Mock before you commit

*Bend a welding rod to the path before you buy the braided line.*

- Reproduce CI locally before pushing (`lesson-reproduce-ci`): run the guard's own
  tests before shipping the hook. Tonight's CI red was a parity miss a local
  full-suite run would have caught — the pattern the mock-up prevents.

## Clamp static / loop at the moving ends

*Anchor hard where the fork is rigid; leave service slack where it travels.*

- Seal and pin the stable (ratified atoms — clamped, durable).
- Leave slack where things still move (candidates and open gaps — the service loops).

---

## Consumables / the shop manual that rides with the roll

- `session_handoff-2026-07-24-89a34091` — the vault-load / 12-node lineage / calibration closeout (8.2 KB)
- `session_handoff-2026-07-24-359073d7` — tonight's hook + seal closeout (3 KB)
- `nestor-lineage-breakdown.md` — the dated project genealogy, atom-cited (5.9 KB)
- `SESSION_RECAP` 2026-07-17 / 18 / 20 — the source docs the atoms were distilled from

---

## Where the roll hangs

- **Bench roll** (reconstruction + schema DDL) → `sean-data-vault/scripts/`, next to `restore-and-wire.sh`
- **Ride roll** (seal tooling + record template) → `willow-mcp` (`scripts/` + `docs/`)
- **Shop manual** (narrative) → either

*Left out on purpose: stale runtime seeds, one-off exploration scripts, logs,
`.bak` files, the self-grant grinder, and everything DB/KB — that's cargo, not
tools.*
