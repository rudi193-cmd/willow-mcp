# Design: Productionize Kart into willow-mcp

Status: **SHIPPED** (superseded 2026-07-18) — the lift landed. Kart was extracted
as the published **`kartikeya`** package (PyPI) and made a hard willow-mcp
dependency; `willow-mcp worker` drains the queue and publishes liveness. Tracked
as **B-22 Fixed** (`docs/BUGS.md`); engineering detail in `kart-lift-spec.md`
(stages 1–4 shipped via PRs #35/#36, worker heartbeat as B-26). This doc is
retained as the direction/decision record. **Still open:** stage 5 — willow-2.0
migrating off its own `core/kart_*` copy to depend on `kartikeya` (the drift
window), which lives on the willow-2.0 side, not here.

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

## 5. Relationship to other work

- `skills/kart-tasks.md` already documents the *current* (worker-required)
  reality and the network-permission footguns (B-19/B-21), with the worker-run
  command explicitly marked pending this lift.
- Closes the product-DOA gap; complements the identity/security work already
  done (`SECURITY_AUDIT.md`) that motivates willow-mcp as the successor.
