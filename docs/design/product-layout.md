---
kind: doc
name: product-layout-willow-mcp-locked
description: "Locked v1.0 spec for the willow-mcp product layout: repo structure, the $WILLOW_HOME runtime tree, repo-to-home init mapping, bundled seeds, environment variables, CLI, and the implementation checklist."
---

@markdownai v1.0

# Product layout — willow-mcp (LOCKED)

*Status: **LOCKED** draft 1.0 — 2026-07-09*  
*Supersedes: Nest single-repo tree as implementation spec; aligns with `session-lifecycle.md`.*

**willow-mcp is a standalone product.** `pip install willow-mcp` + `willow-mcp-init` materializes
`$WILLOW_HOME`. No clone of willow-2.0 or the charter repo is required.

Charter (`~/github/willow`) and fleet (`willow-2.0`) are **optional overlays** on the same home.

All runtime paths resolve through `src/willow_mcp/paths.py`. Do not hardcode `$WILLOW_HOME` subtrees elsewhere.

---

@phase 1-repository-layout-willow-mcp
## 1. Repository layout (`willow-mcp/`)

What ships in the package and repo:

```
willow-mcp/
├── pyproject.toml              # wheel: src/willow_mcp + bundled seeds (see §4)
├── README.md
├── CHANGELOG.md
├── LICENSE
│
├── src/willow_mcp/             # Python package (MCP server, gate, dispatch, …)
│   ├── server.py
│   ├── paths.py                # canonical $WILLOW_HOME path API
│   ├── home_init.py            # `willow-mcp-init` — scaffold runtime tree
│   ├── dispatch.py
│   ├── handoff.py
│   ├── roles.py
│   ├── gate.py
│   ├── consent.py
│   ├── store.py / db.py / …
│   └── bundle/                 # copied into wheel at build (seeds for init)
│       ├── skills/
│       ├── hooks/
│       └── templates/
│
├── skills/                     # source of truth (synced → bundle/ on release)
├── hooks/
├── docs/
│   ├── design/
│   │   ├── product-layout.md   # this file
│   │   ├── session-lifecycle.md
│   │   └── …
│   ├── SESSION_FLOW.md
│   └── templates/              # ASSIGNMENT, CLOSEOUT, …
│
├── tests/
└── .claude-plugin/             # optional Claude Code plugin manifest
    └── plugin.json
```

**Rule:** product code lives under `src/willow_mcp/`. Operator-facing guides live under `docs/`.
Skills/hooks exist at repo root for editing; **runtime** copies live under `$WILLOW_HOME` after init.

**Not in this repo:** `CONSTITUTION.md`, charter `ORIENT.md`, fylgja, Grove, FRANK (fleet).

---

@phase 2-runtime-layout-willow-home
## 2. Runtime layout (`$WILLOW_HOME`)

Default: `~/.willow`. Override with env `WILLOW_HOME`.

```
$WILLOW_HOME/
├── config/                         # operator config (product-owned)
│   ├── settings.global.json        # consent.internet, cloud_llm, …
│   ├── consent.json                # mirror / legacy (see consent.py)
│   ├── agent_roster.json           # named agents + default app_id
│   ├── persona_envelopes.json      # role → tool allow/deny (NOT charter grants)
│   └── rotation.json               # optional free-API key pool (ops)
│
├── dispatch/{dispatch_id}/           # work packets (packet = boot)
│   ├── meta.json
│   ├── assignment.md
│   ├── status.json
│   ├── handoff.json                # on complete
│   └── closeout.md                 # on complete
│
├── handoffs/{app_id}/              # human-entry closeouts (no dispatch_id)
│   └── session_handoff-{date}-{id}_{app_id}.md
│
├── sessions/
│   └── {app_id}-{session_id}.json  # thin session state
│
├── projects/
│   └── {project_id}.json           # DAG definitions (S6 — scaffold empty until built)
│
├── knowledge/                      # optional FS atom mirror (Postgres canonical when wired)
│   └── {atom_id}.json
│
├── templates/                      # seeded from package; operator may edit
├── skills/                         # seeded from package; operator + packages may extend
├── hooks/                          # seeded from package; optional client wiring
│
├── packages/{package_name}/        # installable extensions (future)
│   ├── manifest.json
│   ├── hooks/
│   ├── skills/
│   └── tools/
│
├── mcp_apps/{app_id}/
│   ├── manifest.json               # tool ACL for this app_id
│   ├── schema_maps/                # per-table mapping artifacts
│   ├── _identity_bindings/         # OAuth subject → app_id (sibling dir under mcp_apps/)
│   └── _net_leases/                # egress lease artifacts
│
├── store/                          # SOIL SQLite (WILLOW_STORE_ROOT may override path)
├── ledgers/
│   └── entries/{hash}.json         # lightweight receipt chain (product; not full FRANK)
│
├── resources/                      # operator uploads, attachments
├── constitutional/
│   └── review_queue.json           # Article XI queue (optional charter mount)
├── logs/
│   └── {YYYY-MM-DD}.log
│
├── worker_heartbeat/               # Kart worker liveness (internal)
├── vault.db                        # secrets vault (internal)
└── mcp_token.json                  # OAuth serve mode (internal)
```

### Layout version

`$WILLOW_HOME/.layout-version` contains `1`. `willow-mcp-init` creates or upgrades scaffold;
never deletes operator data.

### Backward compatibility

| Legacy path | Canonical path | Policy |
|-------------|----------------|--------|
| `$WILLOW_HOME/settings.global.json` | `config/settings.global.json` | Read both; init writes canonical; migrate when missing |
| `$WILLOW_HOME/consent.json` | `config/consent.json` | `consent.py` reads both |

---

@phase 3-repo-home-mapping-init
## 3. Repo → home mapping (init)

| Repo source | Runtime destination | Init behavior |
|-------------|---------------------|---------------|
| `src/willow_mcp/bundle/templates/` | `templates/` | Copy if missing |
| `src/willow_mcp/bundle/skills/` | `skills/` | Copy if missing |
| `src/willow_mcp/bundle/hooks/` | `hooks/` | Copy if missing |
| — | `config/*.json` | Write defaults if missing |
| — | all other dirs | `mkdir` only |

**Never overwrite** existing operator files on init or upgrade.

---

@phase 4-bundled-seeds-src-willow-mcp-bundle
## 4. Bundled seeds (`src/willow_mcp/bundle/`)

Wheel includes `bundle/` so init works offline after `pip install`.

| Bundle path | Minimum seeds |
|-------------|---------------|
| `templates/` | `ASSIGNMENT.template.md`, `CLOSEOUT.template.md` |
| `skills/` | `session-start.md`, `handoff-write.md`, `kart-tasks.md` |
| `hooks/` | `pre_tool_use.py` (optional client guard) |

Release maintainer syncs from repo root `skills/`, `hooks/`, `docs/templates/` into
`bundle/` before publish (or CI check).

---

@phase 5-three-repos-product-centric
## 5. Three repos (product-centric)

| Repo | Relationship to willow-mcp |
|------|----------------------------|
| **willow-mcp** | **The product.** Owns layout, init, MCP tools, Kart worker. |
| **willow** (charter) | Optional. Mount or symlink `CONSTITUTION.md` / grants into `constitutional/`; not required. |
| **willow-2.0** (fleet) | Optional host. Shares `$WILLOW_HOME`; adds Grove, FRANK, fylgja, unified MCP. |

---

@phase 6-filename-collisions-do-not-import-blindly
## 6. Filename collisions (do not import blindly)

| Nest / charter name | Product location |
|---------------------|------------------|
| Charter `ORIENT.md` | **Spike** — stays in charter repo; do not overwrite with product copy |
| Charter `AGENTS.md` | `docs/AGENTS.md` (participant-neutral; seat sections) |
| Charter `envelopes/pre-approved.json` | **Not** `config/persona_envelopes.json` — different semantics |

---

@phase 7-environment-variables
## 7. Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `WILLOW_HOME` | `~/.willow` | Runtime root (this layout) |
| `WILLOW_STORE_ROOT` | `$WILLOW_HOME/store` | SOIL SQLite directory |
| `WILLOW_PG_DB` | — | Postgres KB (optional) |
| `WILLOW_MCP_APPS_ROOT` | `$WILLOW_HOME/mcp_apps` | Manifest ACL root |

---

@phase 8-cli
## 8. CLI

```bash
pip install willow-mcp
willow-mcp-init              # scaffold $WILLOW_HOME (idempotent)
willow-mcp                   # start MCP server (stdio)
willow-mcp worker            # Kart queue drainer
```

---

@phase 9-implementation-checklist
## 9. Implementation checklist

| Item | Status |
|------|--------|
| `paths.py` — all subtrees | **done** |
| `home_init.py` + `willow-mcp-init` | **done** |
| `bundle/` seeds | **done** (minimal) |
| Specialist registry schema + seed | **done** — `specialist-registry.md`, `bundle/config/specialists.json` |
| Agent seed schema (`agent_seed_v1`) | **draft** — `agent-seed.md`, `agent-seed-template.json`; `$WILLOW_HOME/seeds/` |
| Registry → manifest compile + gate deny_tools | **done** — `registry.py`, `willow-mcp compile-agents` |
| `projects/` + DAG tools | S6 |
| `packages/` loader | future |
| `ledgers/` writer | future |
| Init migration root → `config/` | **done** (read both) |

---

*Locked by product design session 2026-07-09. Changes require bumping `.layout-version` and a note in CHANGELOG.*

@phase constraints
## Constraints

@constraint severity="critical"
**Never overwrite** existing operator files on init or upgrade.
