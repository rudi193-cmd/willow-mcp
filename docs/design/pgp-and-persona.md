---
kind: doc
name: pgp-persona-locked-decisions
description: "Locked decisions (draft 1.0, 2026-07-09) on PGP as willow-mcp's sole operator trust root and persona as a voice-only overlay that never touches app_id, Grove sender, or SOIL namespace."
---

@markdownai v1.0

# PGP + persona (LOCKED decisions)

*Status: **LOCKED** draft 1.0 — 2026-07-09*  
*Companion: `human-orchestrator.md` · `product-layout.md` · `session-lifecycle.md`*

---

@phase 1-pgp-operator-trust-root
## 1. PGP — operator trust root

### No product dev-bypass

willow-mcp ships **one mode: verify or deny**. There is no `dev_bypass`, no
`pgp_enforced` toggle, no "openable" escape hatch in product code that agents
or misconfiguration can stumble into.

The operator (you) may set **explicit env vars on the MCP host** you control.
That is outside the product's policy surface — not a code path agents invoke.

| Env (operator-set only) | Purpose |
|-------------------------|---------|
| `WILLOW_PGP_FINGERPRINT` | Required primary fingerprint — **one key for everything** |
| `WILLOW_HUMAN_ORCHESTRATOR` | Seat marker: this MCP host is the charter orchestrator workspace |

If `WILLOW_PGP_FINGERPRINT` is unset → PGP checks **fail closed** (deny signed operations).
If set → every signature must match that fingerprint or **it doesn't land**.

### One fingerprint, all artifacts

Same operator key signs:

| Artifact | Path |
|----------|------|
| App manifest | `mcp_apps/{app_id}/manifest.json` + `.sig` |
| Human session attestation | `sessions/willow-{session_id}.json` (canonical blob + `.sig`) |
| Dispatch packet (phase P3) | `dispatch/{id}/meta.json` + `.sig` |
| Optional persona roster changes | `config/persona_roster.json` + `.sig` |
| Agent seed (ratified) | `$WILLOW_HOME/seeds/{agent_id}.json` + `.sig` — see `agent-seed.md` |

**Rule:** `gpg --verify` → parse `VALIDSIG` primary fingerprint → compare to
`WILLOW_PGP_FINGERPRINT`. Mismatch = deny. No alternate trusted keys in product.

Port verification logic from `willow-2.0/sap/core/gate.py::_verify_pgp` — do not
port `dev_bypass` / `_DEV_SAFE_ROOT`.

### Orchestrator write gate (layered)

`dispatch_send`, `verify_handoff`, `agent_clear` require **all**:

1. `app_id=willow`
2. `WILLOW_HUMAN_ORCHESTRATOR=1` on MCP host (charter seat config)
3. Valid PGP attestation on `sessions/willow-{session_id}.json` (when PGP enabled)
4. Manifest `.sig` verifies (when PGP enabled)

Env-only (slice shipped today) is **interim** until P2 attestation lands.

### Signing stays host-side

`willow-mcp sign-manifest`, `willow-mcp attest-session` — operator terminal only.
Kart bwrap cannot reach gpg-agent (fleet lesson). Agents **request**; operator **signs**.

---

@phase 2-persona-new-shape-stays-forks
## 2. Persona — new shape (stays, forks)

Persona is **voice only** — never changes `app_id`, Grove sender, or SOIL namespace.

### Where picker lives

| Seat | Interactive picker? | Implementation home |
|------|---------------------|---------------------|
| **Charter orchestrator** (`~/github/willow`) | **Yes** | Host hook (fylgja / Cursor SessionStart) — **not** willow-mcp product core |
| **Specialist dispatch** | **No** — silent | `meta.json` `persona` / `role` → context injection via `session_enter` |
| **Specialist human entry** | **No** — default from manifest | `mcp_apps/{app_id}/manifest.json` `role` |

willow-mcp documents the contract; it does not ship the orchestrator menu UI.

### Specialist silent persona (packet)

```json
{
  "role": "loki",
  "persona": "loki",
  "persona_voice": "One-line cognitive frame for this assignment."
}
```

Injected on dispatch `session_enter` — no blocking, no menu.

---

@phase 3-persona-roster-project-scoped-user-extensions-draft-discuss
## 3. Persona roster — project-scoped + user extensions (DRAFT — discuss)

Two namespaces, merged at picker render time on **charter seat only**:

### A. Project roster (short, scoped)

**Source:** `<project_root>/.willow/personas.json` (or charter repo `personas/roster.json`)

- Curated by project owner — **small list** (e.g. 3–7 entries)
- Entries reference voice keys + optional one-line blurb
- May include `"locked": true` binding for this project (charter seat → Willow only)
- **Signed** when roster changes matter (`persona_roster.json.sig` optional slice)

Example:

```json
{
  "format": "persona_roster_v1",
  "project": "willow",
  "entries": [
    {"key": "willow", "label": "Willow — magistrate voice", "locked": true},
    {"key": "publius", "label": "Publius — deliberate consensus"},
    {"key": "jeles", "label": "Jeles — librarian lens (voice only)"}
  ]
}
```

**Principle:** project folder defines **which voices are in scope** for this desk —
not the full fleet menagerie.

### B. User extensions (operator-owned)

**Source:** `$WILLOW_HOME/personas/{key}.md` + `$WILLOW_HOME/config/user_personas.json`

- Operator creates custom personas (`+ Create new` in picker)
- Stored under **home**, not committed to project repo
- Available across projects unless project roster sets `"allow_user_extensions": false`
- Never grant orchestrator perms — voice overlay only

### Merge rules (picker render)

```
display_list = project_roster.entries
if allow_user_extensions (default true):
    display_list += user_personas not already in project keys
always append: { key: "__create__", label: "+ Create new persona" }
if project binding locked:
    hide picker — inject bound persona only
```

### Open questions (operator)

1. **Default `allow_user_extensions`?** — `true` (fleet today) vs `false` on charter seat?
2. **Jeles on orchestrator roster?** — voice lens yes; role remains librarian for dispatch targets.
3. **Roster in repo vs `.willow/`?** — charter: committed `personas/roster.json`; other projects: `.willow/personas.json` gitignored?
4. **PGP-sign roster changes?** — required on charter repo commits, or only at runtime load?

---

@phase 4-file-map-additions
## 4. File map additions

```
$WILLOW_HOME/
├── config/
│   ├── user_personas.json      # user-created persona registry
│   └── persona_roster.json     # optional home-level override
├── personas/
│   └── {key}.md                # user persona voice prose

<project_root>/
└── .willow/
    └── personas.json           # short project-scoped roster (charter: or personas/roster.json in repo)
```

---

@phase 5-implementation-slices
## 5. Implementation slices

| Slice | Deliverable |
|-------|-------------|
| P1 | `pgp.py` — verify only, fail closed, port from fleet gate |
| P1 | Manifest `.sig` check in `gate.permitted()` when fingerprint env set |
| P2 | `attest_session` CLI + session file `.sig` |
| P2 | Orchestrator write gate checks attestation |
| P3 | `dispatch` meta `.sig` on send |
| Persona | Document contract; charter hook reads project + user rosters |
| Persona | `meta.json` persona fields on `dispatch_send` |

---

@phase 6-what-we-explicitly-reject
## 6. What we explicitly reject

- Product `dev_bypass` / `pgp_enforced` mode switch
- Interactive persona picker in willow-mcp pip package (charter hook only)
- Persona changing `app_id` or manifest permissions
- Multiple trusted PGP fingerprints in product code
- Agents signing anything inside Kart sandbox

---

*Operator decisions locked 2026-07-09: no dev bypass in product; one fingerprint; charter picker only; project roster + user extensions (details §3 open).*

@phase constraints
## Constraints

@constraint severity="critical"
- Operator creates custom personas (`+ Create new` in picker)
