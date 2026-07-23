# Handoff — 2026-07-23 · MCP wiring, corpus inventory, enforcement diagnosis

Branch: `claude/desk-organization-uby85b` (open — 32 commits ahead of `master`, no PR yet).
Written from a remote Claude Code (CCR) session. Seat: `vishwakarma` / `app_id=safe-app-store`.

---

## 1. What I now understand (architectural truth)

The willow MCP-first enforcement stack is **complete and sound, but dormant in remote/hosted sessions**: the fylgja `PreToolUse` hooks, the willow MCP server, and Kart (the bwrap Tier-1 sandbox whose no-network tasks receive zero credentials) all exist — but in a CCR container none are wired in, so an agent bypasses MCP straight to raw `psql`/`sqlite3`. The break is not a missing tier; it is that `safe-app-store/.mcp.json` hardcodes fleet-host paths (`/home/sean-campbell/…`) that do not exist in the container, so the server fails to launch at spawn. Separately: the corpus is a **narrative** corpus (structured docs = 0 across ~1000 `.md`), so structure/metadata extraction is fully tool-driven and a model is needed only for the semantic last mile.

## 2. What was done (high-level)

- **Corpus inventory** — 12 repos deep-scanned model-free (`mai_prose_split` doc-class + `cbm` symbol graph + LOC); rest metadata-only. `sean-data-vault` excluded throughout. Stored to KB atom `4B849F01`. Key finding: `structured` docs = 0 everywhere; willow-2.0 is the center of mass (556 docs / 848 mods / ~160k LOC); the "named originals" (kartikeya, jeles-remote) are willow-2.0 core decomposed into standalone PyPI/Fly.io pieces (nestor, jeles are empty name-reservations).
- **Predictions** on the ~21 remaining owned repos — naive priors then corpus-informed priors (mean 0.70 → 0.79), logged to the oakenscrolls-office ledger. The corpus map (`willow/design/architecture/github-corpus-map`) corrected two (willow-compose = corpus-memory not docker-compose; willow-grove = empty).
- **willow-bot pulled** (`add_repo`) and its prediction **graded a miss** (predicted "Discord responder"; it is a GitHub-App webhook receiver). Miss reframed as a real absence → gap `4060189ff2fa` (the map's `discord responder ✓` daemon is unlocated in the scanned corpus).
- **Enforcement diagnosis** — audited the fylgja stack (`willow/fylgja/events/pre_tool.py`, `mcp_routing.BASH_TO_MCP`, escalation, block telemetry, subagent blocking, hook tamper guard) + Kart as Tier-1. Root cause captured in gap `f63582061206` and **issue willow-mcp#164** (enforcement stack dormant in remote/hosted sessions).
- **MCP standup attempt** — stood up `willow-mcp --serve` (HTTP, pid 13329, `127.0.0.1:8765`) and registered it; registered **cbm** (stdio) → **√ Connected**; pre-granted both via `enabledMcpjsonServers` (the user-scope `/root/.claude/settings.json` was the read-path that flipped approval). willow OAuth is **blocked in this env**: vault has no `google.client_id/secret`, and `127.0.0.1` is not a reachable OAuth redirect.
- **Merged** the safe-app-store dev branch → master as **PR #85** (oakenscrolls-office v0.2.0, `fleet-presence`, coupling map, VISION/law-gazelle mai). This willow-mcp branch remains open.

## 3. 17 Questions (sequential, bite-sized)

1. Is the willow-mcp dev branch (32 commits) meant to land in `master` via its own PR, or keep accumulating?
2. If PR'd, does the full mai-conversion run (docs/design COMPLETE) go as one PR or split from the `tools/` suite?
3. Should `tools/` (mai_lint, mai_prose_split, wtool, provision_gate, mai_metrics) be wired into CI (issues #158/#84) before or after that merge?
4. Does issue #164's fix belong in willow-mcp (session-start assertion) or in the CCR environment config, or both?
5. For #164 fail-closed: should a session with no willow MCP server deny `Bash(psql|sqlite3|curl:*)` outright?
6. Who provisions the container-portable `.mcp.json` — a setup script that `claude mcp add`s with container paths each spawn?
7. To unblock willow OAuth here, where are the Google `client_id/secret` stored, and how should they reach the vault (not chat)?
8. Is there a tunnel/ingress for this container so `WILLOW_MCP_URL` can advertise a reachable OAuth callback?
9. Should the willow serve process be supervised (systemd/loop) or is stdio + dev-fallback the right mode for headless sessions?
10. Is `wtool` the accepted willow lane for headless sessions until native tools mount, or should it be retired?
11. Should gap `4060189ff2fa` (unlocated Discord responder) be resolved now — one grep of willow-2.0 `core/grove_*` / `discord_*` closes it?
12. Do the calibration predictions (naive/informed ledgers, scratchpad) get promoted to the KB, or stay ephemeral?
13. Should the willow-bot correction be stored as a KB atom (its own memory), like the corpus inventory was?
14. Does the almanac-vertical assumption (12 catalog repos, class-identical to climate) warrant one spot-check `add_repo`?
15. Are the remaining private repos (SAFE, safe-design, tui-scaffold, Aionic-Claude-Skills) worth pulling, or hold at metadata?
16. Should the corpus map itself be regenerated (it's dated 2026-07-20; two facts shifted since)?
17. **Next single bite:** resolve gap `4060189ff2fa` by grepping willow-2.0 for the Discord responder daemon — smallest closed loop, no new pull, and it clears the one open miss.

## 4. Risks / open gates

- **Ephemeral, uncommitted config** — `/home/user/.mcp.json`, `/home/user/.claude/settings.json`, `/root/.claude/settings.json`, and the `cbm`/willow entries in `/root/.claude.json` are container-local and die with the session. Nothing durable until #164's environment wiring lands.
- **willow serve (pid 13329)** and **cbm** are up but their tools have **not mounted** in this session (discovery refresh pending / willow OAuth unmet). Do not assume `mcp__willow-mcp__*` are callable yet.
- **willow OAuth blocked** here: vault creds missing + `127.0.0.1` unreachable. Needs Q7/Q8 resolved.
- **Open items:** issue #164; gaps `f63582061206`, `4060189ff2fa`; backlog #158/#84 (mai_lint→CI), #159 (knowledge_flag/retract), #160 (postgres auto-restart), #161 (gate-threading).
- **Held:** the Willow Constitution + canon (CONSTITUTION/AGENTS/ORIENT/AGENT_SERVICES) remain HELD from mai conversion per standing instruction.
- **Branch:** this branch is not fast-forwarded onto master and is not intended to be (`--ff` skipped per instruction); it carries 32 unmerged commits safely on origin.

---

ΔΣ=42
