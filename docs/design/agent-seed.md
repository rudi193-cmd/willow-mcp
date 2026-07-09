# Agent seed — universal participant model (DRAFT)

*Status: **DRAFT** — 2026-07-09*  
*Companion: `agent-seed-template.json` · `specialist-registry.md` · `pgp-and-persona.md` · `session-lifecycle.md` · `product-layout.md`*

**Principle:** Every agent in the fleet — human operator, orchestrator seat, specialist persona — validates against **one cognitive shape**. No duck is different. Machine authorization (permissions, manifests, envelopes) stays **orthogonal**.

Governance decisions (charter seat, 2026-07-09):

- `dec-agent-seed-three-store-2026-07-09` — home / SOIL / KB placement
- `dec-exposure-picker-ui-2026-07-09` — per-action slice + standing exposure defaults

---

## 1. Purpose

`agent_seed_v1` is the **participant document**: how to work with this agent across cold boots, dispatches, and cross-channel propagation.

| Layer | Schema | Question it answers |
|-------|--------|---------------------|
| **Agent seed** | `agent_seed_v1` | Who is this voice? How do they think, correct, and ratify? What is unknown? |
| **Specialist registry** | `specialist_registry_v1` | What tools, namespace, and routing does this `agent_id` get? |
| **Manifest / envelope** | `mcp_apps/*/manifest.json` | What may this session call? |

Seed shapes **human context**. Registry shapes **machine permission**. Neither replaces the other.

### What this subsumes (voice / continuity lane)

- Fylgja `personas/*.md` (compile target or source)
- Operator learnable record (`sean.md` → `sean.json`)
- Persona picker labels (charter seat)
- `meta.json` `persona_voice` one-liner
- Cold-boot instruction fragments
- Interaction contracts (`signoffs`, `correction_pattern`)
- `corpus/preferences` compile target (pillars, voice rules)
- Exposure-picker field map (paths = schema paths)

### What this does **not** replace

- KB atoms for world facts (commits, architecture, file index)
- SOIL event streams (`turns`, `sessions`, `pa/commitments`)
- `specialist_registry` permissions
- `envelopes/pre-approved.json` authority grants
- Dispatch `assignment.md` (task-specific work orders)
- Structured `handoff.json` evidence

---

## 2. Schema (`agent_seed_v1`)

Template: [`agent-seed-template.json`](agent-seed-template.json).  
Worked example (operator): Nest `sean_seed.json` (home-only; not shipped in wheel).

### Top-level

| Field | Purpose |
|-------|---------|
| `format` | Always `agent_seed_v1` — loader discriminator |
| `identity` | Machine hook to registry without duplicating permissions |
| `seed` | Provenance, boot instruction, ratification |
| `persona` | Voice fidelity — rules, anti-patterns, calibration |
| `context` | Cognitive + situational model |
| `membrane` | Dual Commit instance (thin; points to fleet law) |
| `gaps` | Honesty log — unknowns, conflicts, propagation status |

Leave unused leaf fields **empty** (not deleted) so the loader stays uniform.

### `identity`

| Field | Values | Notes |
|-------|--------|-------|
| `agent_id` | `sean`, `hanuman`, `willow`, … | Stable id |
| `kind` | `operator` \| `specialist` \| `orchestrator_seat` | Routing + sensitivity |
| `display_name` | Human label | Picker / desk |
| `registry_ref` | `specialists.json#hanuman` or `orchestrator_seat` | Null for operator (`sean`) — not dispatchable |

| `kind` | Example | Registry row? |
|--------|---------|---------------|
| `operator` | `sean` | No — ratifier, not dispatch target |
| `specialist` | `hanuman`, `jeles` | Yes — `specialists[]` |
| `orchestrator_seat` | `willow` | Yes — `orchestrator_seat` |

### `seed.ratification`

Structured gate for Dual Commit + PGP (replaces prose `"PENDING — …"` string):

```json
{
  "status": "pending",
  "ratifier_agent_id": "sean",
  "ratified_at": null,
  "canon_entry_id": null,
  "sig_path": "seeds/sean.json.sig"
}
```

| `status` | Meaning |
|----------|---------|
| `pending` | May load for boot; surfaces `gaps`; does not promote to KB canon |
| `ratified` | Operator signed; eligible for KB excerpt ingest |

### Volatile vs durable fields

| Block / field | Update cadence | Loader |
|---------------|----------------|--------|
| `persona`, `membrane` | Rare; ratified | Every cold boot |
| `context.active_work` | Often | Hint only — verify live |
| `gaps[]` | Every session | Always surfaced |

---

## 3. Coverage map (wide view)

One shape, many roles — fill depth varies by `kind`:

| Role filled | Primary blocks |
|-------------|----------------|
| Cold-instance boot | `seed.instruction`, `gaps` |
| Persona / voice inject | `persona.*` → compile `personas/{id}.md` |
| Operator learnable record | Full document (`kind: operator`) |
| Specialist mandate prose | `persona` + thin `context`; `job`/`not_job` stay in registry |
| Orchestrator desk voice | `persona` + `membrane`; no operator `active_work` |
| Cross-LLM propagation | Ratified home file + `.sig` |
| Exposure picker UI | Field paths under `persona.*`, `context.*` |
| Preference compiler | `corpus/preferences` → `persona.pillars`, `voice_rules` |
| Correction learner | `corpus/corrections` → `gaps`, `correction_pattern` |
| Jeles retrieval (excerpt) | KB atom `content.kind: agent_seed_v1` slice |

---

## 4. Placement — home, SOIL, KB (three-store)

**Canonical source of truth:** filesystem under home — not search index.

```
$WILLOW_HOME/seeds/{agent_id}.json      # full document
$WILLOW_HOME/seeds/{agent_id}.json.sig  # operator PGP (when enabled)
```

### Flow

```
Edit seed (home)
  → Dual Commit ratify (willow-mcp sign-seed — operator terminal)
  → optional SOIL mirror (typed collections)
  → exposure picker chooses slice (per destination)
  → kb_ingest excerpt (if fleet-visible)
  → session_enter loads from home (not KB search)
```

### Store rules

| Store | Role | Content |
|-------|------|---------|
| **Home** `$WILLOW_HOME/seeds/` | Canonical | Full seed + `.sig`. Operator seeds **never** in product wheel. |
| **SOIL** typed collections | Mirror / working copy | Drafts, compile targets. Not event streams. |
| **Postgres KB** | Ratified **slices** only | `source_type: agent_seed`, `content.kind: agent_seed_v1` |

### SOIL collections

| Collection | Use |
|------------|-----|
| `corpus/seed` | Revive — full typed seeds (fleet store has collection; often empty) |
| `agents/seeds` | New — per-`agent_id` mirror with `_mirror_of`, `_slice` |
| `willow/persona` | Pointer or typed body |

**Do not** force agent_seed shape on: `*/atoms`, `turns`, `sessions`, `pa/commitments`, `pm/*`, `governance/decisions`.

### KB atom (slice promotion)

```json
{
  "title": "Agent seed — sean (work-context slice)",
  "summary": "Operator voice rules and correction pattern (ratified excerpt)",
  "tier": "canonical",
  "sensitivity": "sensitive",
  "source_type": "agent_seed",
  "source_id": "seeds/sean.json",
  "content": {
    "kind": "agent_seed_v1",
    "agent_id": "sean",
    "slice": "work_context",
    "body": { "persona": { "register": "...", "voice_rules": [] }, "context": { "correction_pattern": "..." } },
    "ratification": { "status": "ratified", "ratified_at": "2026-07-09T00:00:00Z" }
  }
}
```

**Never** default full operator `cast` / `personal_note` into searchable KB. Exposure picker + `sensitivity` gate outbound slices.

### Universal spine inheritance

Aligns with fleet KB pattern (tier + lifecycle + provenance):

| Spine axis | On seed |
|------------|---------|
| Tier | `frontier` until ratified → `canonical` for KB excerpts |
| Lifecycle | Supersede on re-ratification; archive, do not delete home file |
| Provenance | `seed.session`, `source_id`, `.sig`, `gaps[]` conflict log |

`membrane` and `ratification` are seed-specific — not on every KB atom.

---

## 5. Exposure membrane (UI — future slice)

Cross-ref: charter `dec-exposure-picker-ui-2026-07-09`.

Standing defaults: `$WILLOW_HOME/config/exposure.json` (or extension of `settings.global.json`).

| Preset | Blocks included |
|--------|-----------------|
| `voice_only` | `persona.register`, `persona.voice_rules` |
| `work_context` | + `context.active_work`, `context.session_pattern` |
| `full_seed` | + `persona.cast`, `persona.pillars`, `context.personal_note` |
| `custom` | Per-field checkboxes |

Pipeline:

```
agent_seed_v1 (home)
  → exposure_profile (standing defaults)
  → exposure_slice (per-action picker, audited)
  → outbound_envelope (dispatch / cloud LLM / Grove)
```

Schema field paths are the checkbox IDs. Orthogonal to registry **tool** permissions.

---

## 6. PGP + ratification

Cross-ref: `pgp-and-persona.md`.

| Artifact | Path |
|----------|------|
| Agent seed (ratified) | `$WILLOW_HOME/seeds/{agent_id}.json` + `.sig` |

- Unratified: loader may read; inject `gaps` banner; no KB canon promotion.
- Ratified: `gpg --verify` against `WILLOW_PGP_FINGERPRINT`; mismatch = deny signed operations.
- `willow-mcp sign-seed` — operator terminal only (host-side; not Kart).

---

## 7. Session boot order

```
session_enter(app_id, session_id, dispatch_id?)
  1. specialist_registry row (permissions — when S-R7 lands)
  2. load agent_seed from $WILLOW_HOME/seeds/{agent_id}.json
  3. verify .sig if WILLOW_PGP_FINGERPRINT set
  4. if ratification.status == pending → surface gaps[]
  5. apply exposure_profile + per-action slice (future)
  6. load persona_path (.md) — compiled from seed or bundle fallback
  7. dispatch path: inject assignment.md
```

Specialists: **no persona picker** — silent inject from registry + seed.  
Charter orchestrator: picker reads project roster; Willow seat may be `locked`.

---

## 8. Relation to specialist registry

| Registry field | Seed relationship |
|----------------|-------------------|
| `agent_id` | `identity.agent_id` |
| `job` / `not_job` | May compile **from** seed or **to** seed — pick one direction at implement time |
| `persona_path` | Compile target: `persona` block → `personas/{id}.md` |
| `permissions` | **Not in seed** — stays registry-only |

Registry slice **S-R*** for permissions remains blocked until operator ratifies permission matrix. Agent seed is **not** blocked on that decision.

---

## 9. Bundled seeds (product wheel)

| Ship in wheel | Do not ship |
|---------------|-------------|
| `docs/design/agent-seed-template.json` | Operator `sean.json` |
| `bundle/seeds/_template.json` (copy of template) | Full cast / personal_note examples |
| Redacted `bundle/seeds/examples/hanuman.min.json` | Any home path contents |

`home_init` / `willow-mcp-init`: `mkdir seeds/` only; never overwrite operator files.

`paths.py`: add `seeds_dir()` → `$WILLOW_HOME/seeds`.

---

## 10. Implementation slices

| Slice | Deliverable | Blocked on |
|-------|-------------|------------|
| AS-1 | This doc + `agent-seed-template.json` | — |
| AS-2 | `paths.seeds_dir()`; init creates `seeds/` | — |
| AS-3 | `session_enter` reads seed (advisory if unratified) | **done** |
| AS-4 | `sign-seed` CLI + `.sig` verify in loader | **done** |
| AS-5 | SOIL `agents/seeds` mirror tool | **done** (`willow_agents_seeds` + `agent_seed_mirror`) |
| AS-6 | `kb_ingest` slice promotion (`source_type: agent_seed`) | **done** |
| AS-7 | `compile-persona` seed → `.md` | — |
| AS-8 | Exposure picker + `exposure.json` | UI slice |

---

## 11. Open decisions (operator)

1. **Registry ↔ seed compile direction** — `job`/`not_job` source of truth?
2. **SOIL primary vs home primary** — mirror always, or home-only for operator?
3. **KB slices default** — which presets auto-promote on ratification?
4. **Operator `sean` in fleet KB at all** — or home-only forever with Jeles blocked from cast?
5. **Propagation test** — cold instance boots from seed alone (Oakenscroll symmetry)?

---

## 12. Deprecations (target)

| Current | Future |
|---------|--------|
| Prose-only `personas/*.md` | Compiled from seed or co-maintained |
| Scattered `corpus/preferences` voice fragments | Compile into seed |
| `sean_campbell_context.json` | Operational threads separate; identity in seed |
| Unstructured operator notes | `kind: operator` seed at home |

---

*Draft lineage: 0.1 (2026-07-09) — from Nest `agent_seed_template.json` + `sean_seed.json`; three-store and exposure decisions from charter governance session.*
