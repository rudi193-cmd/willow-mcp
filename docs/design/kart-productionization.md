# Design: Productionize Kart into willow-mcp

Status: **SHIPPED** (superseded 2026-07-18) — the lift landed. Kart was extracted
as the published **`kartikeya`** package (PyPI) and made a hard willow-mcp
dependency; `willow-mcp worker` drains the queue and publishes liveness. Tracked
as **B-22 Fixed** (`docs/BUGS.md`); engineering detail in `kart-lift-spec.md`
(stages 1–4 shipped via PRs #35/#36, worker heartbeat as B-26). This doc is
retained as the direction/decision record. **Still open:** stage 5 — willow-2.0
migrating off its own `core/kart_*` copy to depend on `kartikeya` (the drift
window), which lives on the willow-2.0 side, not here. The drift window is now
**measured** — see §5 for the 22-piece worklist.

Original status (2026-07-08): DIRECTION SET — staged migration, not yet started.

## 1. Why

willow-mcp is the intended **production replacement** for the `willow` fleet
service — it has better security and identity handling and fewer leaks (see
`SECURITY_AUDIT.md`). For it to stand on its own as a product, the task-queue
half has to actually work on a clean install.

Today it does not. `pyproject.toml` advertises a "Kart task queue" and the
server ships `task_submit` / `task_status` / `task_list` / `fleet_health`, but
**no Kart executor ships in the package** — `find -iname '*kart*'` in the repo
is empty, and `[project.scripts]` exposes only the MCP server. A clean
`pip install willow-mcp` therefore yields a queue *writer* with nothing to
drain it: every submitted task sits `pending` forever. The tools have only ever
executed because an out-of-repo (and often stale) willow-2.0 Kart happened to be
present on the operator's own machines. This is tracked as **B-22 (P1)** in
`docs/BUGS.md` and is the finding that makes the product DOA out of the box.

## 2. What ships

The Kart the operator hardened in willow-2.0 over many months — not a throwaway
reference worker. Core pieces, all currently under `willow-2.0/core/`:

- `kart_sandbox.py` — the bubblewrap sandbox (mount policy, network directives
  `# allow_net` / `# allow_localhost`, credential-prefix gating).
- `kart_execute.py` — single-task execution (daemon + poll fallback).
- `kart_worker.py` — the queue consumer: polls `public.tasks`, claims
  `agent=kart` rows, runs them via `kart_execute`, with fast/batch lanes.
- `kart_lanes.py` — lane/worker-mode helpers.
- Its test suite (`tests/test_kart_*.py`) travels with it.

## 3. The hard part: decoupling from the fleet

This is a **migration, not a copy**. The willow-2.0 Kart is wired into fleet
internals that must not become willow-mcp dependencies:

- `core.loop_heartbeat` / SOIL watchmen heartbeats — fleet liveness telemetry.
- Worktree discovery + `willow/fylgja/config/kart-sandbox.json` mount policy.
- `.kart-scripts/` staging, fleet env-file credential loading.

These must be made **optional or removed** so the worker runs standalone with
only what willow-mcp already owns (the `tasks` table via the schema-adaptation
layer, a config file, bwrap). Where willow-mcp already has an equivalent (its
own receipts, its own diagnostics), the worker should use that rather than the
fleet's.

## 4. Staged plan

1. **Decouple** — fork the four core files into a branch, strip/guard the
   fleet-only imports behind optional shims; get the Kart test suite passing
   with no willow-2.0 on the path.
2. **Vendor** — land the decoupled worker as `src/willow_mcp/kart/` inside the
   package, carrying its tests into `tests/`.
3. **Entry point** — add a `willow-mcp worker` console script
   (`[project.scripts]`) that drains the queue; document lanes/config.
4. **Honesty in metadata** — until step 3 lands, `pyproject`/README must not
   imply execution ships; after it lands, README gets a real quickstart
   (submit → worker runs → poll).
5. **Skill worker-run section** — fill in the deferred worker-run instructions
   in `skills/kart-tasks.md` §0 once the console script exists.
6. **Liveness** — surface worker last-heartbeat in `fleet_health` /
   `diagnostic_summary` so "queued, unattended" is distinguishable from
   "queued, about to run" (the external review's §1).

## 5. The drift window — measured worklist (2026-07-18)

Stage 5 is willow-2.0 retiring its own `core/kart_*` copy in favour of the
shipped `kartikeya`. How big is that drift? A read-only pass over the indexed
corpus (both trees, compared by content-SHA, then true-fork vs. label-collision
separated by line-set Jaccard ≥ 0.2) puts a number on it: **22 pieces have
genuinely diverged** between `kartikeya` (canonical) and `willow-2.0/core/kart_*`.
An earlier count of "33" was inflated by same-name collisions across unrelated
files (`__init__`, `mark_done`, `stats`, a `kart_timeout` that is a full rewrite,
not a fork) — those are excluded here.

**Dominant pattern:** kartikeya strips the `willow.fylgja` fleet dependency from
the sandbox while preserving the logic. The large isolation primitives are
near-identical (Jaccard > 0.9) apart from the removed `fylgja` import — this §3
decoupling is *done*, and the diff proves it was surgical, not a rewrite.

Retirement risk falls into three tiers:

**Tier 1 — clean fleet-strip (Jaccard > 0.85; logic intact, only `fylgja`/`core`
import removed). Safe for willow-2.0 to drop its copy and depend on kartikeya:**

| piece | file | lines | jac |
|-------|------|------:|----:|
| `build_bwrap_argv` | sandbox | 146 | .97 |
| `collect_bind_mounts` | sandbox | 73 | .97 |
| `kart_env` | sandbox | 110 | .96 |
| `collect_mcp_trust_ro_overlays` | sandbox | 27 | .92 |
| `run_shell` | sandbox | 129 | .91 |
| `scan_bash` | security_scan | 13 | .92 |
| `_run_one_shell` | execute | 19 | .89 |
| `venv_candidates`, `willow_python` | pyenv | 27, 12 | .85, .82 |

**Tier 2 — reimplementation (Jaccard < 0.4; size changed because the fleet had
been *providing* something kartikeya now rebuilds standalone). Verify behaviour
before willow-2.0 switches:**

| piece | file | lines kart→w2.0 | jac | note |
|-------|------|:---------------:|----:|------|
| `execute_task_row` | execute | 70 → 30 | .27 | inlined what `core` provided (doubled) |
| `load_sandbox_config` | sandbox | 25 → 9 | .29 | fleet loaded config; now standalone |
| `drain_claimed_tasks` | execute | 31 → 28 | .35 | queue drainer rewritten |
| `reaper_alignment_warning` | lanes | 12 → 19 | .29 | fleet-liveness reaper reworked |

**Tier 3 — moderate (Jaccard 0.4–0.85; review, tractable):** `run_shell_task`
(67→94, .65), `check_hook_tamper` (.50), `_parse_task_network_directives` (.50),
`trim_task_result` (.75), `_hook_tamper_fragment` (.60), `_kart_logs_root` (.50),
`willow_home` / `willow_home_alias` (.20, .50), `venv_bin_dirs` (.78).

**Security read.** The diverged set is concentrated in the sandbox/isolation core
(bwrap argv, bind mounts, trust-ro overlays, hook-tamper, network-directive
parsing) — but those are almost all Tier 1, decoupled by surgical `fylgja`
removal with logic preserved. The isolation guarantees were unplugged from the
fleet, not rewritten. The **one** Tier-2 piece with isolation blast-radius is
`load_sandbox_config` (it feeds the sandbox): confirm the standalone config load
enforces the same mount/network policy before relying on it.

**Verdict for stage 5:** `kartikeya` is canonical. Tier 1 → willow-2.0 drops its
copy as-is. Tier 2/3 → merge-with-review, not a blind swap; each reimplemented
piece must be shown to preserve the guarantee it replaced (especially
`load_sandbox_config`). Method caveat: line-set Jaccard is coarse — treat this as
the review *worklist*, not the review itself; witness each piece at merge time.
Provenance: `willow_compose` store record `kart_migration/f9cdc57f`.

### Tier 1 — SHIPPED (2026-07-20)

willow-2.0 PR #817 delegated `collect_bind_mounts`, `collect_mcp_trust_ro_overlays`,
and `kart_env` to `kartikeya`; equivalence proven byte-identical, gated on
`test_kart_*` staying green. `build_bwrap_argv` was deliberately kept as willow-2.0's
own thin assembly over the delegated producers (per-root config + test monkeypatch
seams depend on it) — see the PR for the full account. `scan_bash` / `run_shell` stay
un-delegated (kartikeya's versions are real behaviour changes: fork-bomb detection,
default-on resource caps).

### Tier 2 — reviewed, verdict: no delegation (2026-07-20)

Each piece witnessed individually, per the plan. None delegate — for four distinct,
concrete reasons, not one blanket "too risky":

- **`load_sandbox_config`** — kartikeya's resolver is env/`$WILLOW_HOME`-global, not
  per-root; willow-2.0's callers (worktree scenarios, and the test suite's synthetic
  repos in `test_kart_symlink_binds.py`) depend on an explicit `root` overriding
  everything else. Delegating would silently break per-root resolution exactly the
  way `build_bwrap_argv` would have in Tier 1. **Action taken instead:** closed the
  config split-brain Tier 1 introduced — `KART_SANDBOX_CONFIG` was being set (for
  kartikeya's benefit) but willow-2.0's own `load_sandbox_config` never consulted it,
  so an operator override would silently apply to the three delegated functions and
  *not* to `run_shell`/`build_bwrap_argv`'s own config reads. Root-less callers now
  fall back to `$KART_SANDBOX_CONFIG`; an explicit `root` still always wins.
- **`execute_task_row` / `drain_claimed_tasks`** — willow-2.0's version is fleet
  business logic, not sandbox isolation: it dispatches `workflow_phase` and
  goal-based agent tasks, and gates network access through
  `core.egress_authority.net_authorized` (B-37, the fleet's credential/consent
  control). kartikeya's version is deliberately generic — non-shell task types need
  a caller-registered `handlers` dict, and network authorization is an optional
  `network_authorizer` callback seam it doesn't wire up itself. Adopting it would
  mean threading willow-2.0's egress-authority check through that seam and
  registering handlers for `workflow_phase`/`goal` — a real architectural change
  touching a security control, not an equivalence swap. Left as willow-2.0's own
  implementation; a future migration is possible but needs its own dedicated,
  security-reviewed PR.
- **`reaper_alignment_warning`** — kartikeya's version only checks the daemon-lane
  timeout; willow-2.0's covers both the daemon *and* fast-lane timeouts (`max()` of
  the two). kartikeya has no fast-lane concept at all yet, so delegating here would
  be a straight regression, not a lateral move. Left as-is.

Net effect: Tier 2 is closed as **reviewed, not delegated**, plus one small
Tier-1-hygiene fix (`load_sandbox_config`'s env fallback) that Tier 1's own change
made necessary. `tests/test_kart_*` + `tests/test_audit_verify.py` stay green
throughout.

## 6. Relationship to other work

- `skills/kart-tasks.md` already documents the *current* (worker-required)
  reality and the network-permission footguns (B-19/B-21), with the worker-run
  command explicitly marked pending this lift.
- Closes the product-DOA gap; complements the identity/security work already
  done (`SECURITY_AUDIT.md`) that motivates willow-mcp as the successor.
