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
5. **Skill worker-run section** — **DONE.** `skills/kart-tasks.md` §0 documents
   `willow-mcp worker --lane/--once` and reads worker liveness off `fleet_health`.
6. **Liveness** — **DONE (B-26).** `fleet_health` reports `workers`/`stranded`
   and `diagnostic_summary` gains a `worker` check, so "queued, unattended" is
   distinguishable from "queued, about to run" (the external review's §1).

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

### Tier 3 — reviewed, verdict: no delegation + one coherence fix (2026-07-20)

All eight Tier-3 pieces witnessed. The tier splits cleanly in two, and neither half
delegates:

**Fleet-coupled — keep (delegating would strip fleet behaviour):**
- **`run_shell_task`** — carries the same B-37 egress gate as the Tier-2 executor:
  `allow_net` from the task text is only honoured when the caller-resolved
  `net_authorized` fact agrees, and a denial is stamped as `net_denied`. kartikeya's
  `run_shell_task` has none of this (it places network authorization one level up, in
  `execute_task_row`'s optional `network_authorizer` seam). Same verdict as Tier-2.
- **`check_hook_tamper` / `_hook_tamper_fragment`** — willow-2.0 hardcodes the fleet
  guard list (`willow/fylgja/events/`, `.cursor/hooks.json`, `.claude/settings.json`,
  …) and must "stay in sync with pre_tool.py". kartikeya's version is a generic seam
  (`HOOK_GUARD_FRAGMENTS` / `$KART_HOOK_GUARD_PATHS`, empty by default) with a
  product-neutral error message ("Protected source" vs "Fylgja hook source").
  Delegating would move the security wording and still leave the fleet fragment list —
  and its `pre_tool.py` sync coupling — in willow-2.0. No net simplification.
- **`_kart_logs_root`** — one line, but it resolves through fylgja's private-config-
  aware home; kartikeya's resolves through the generic one. See the coherence fix below.
- **`willow_home` / `willow_home_alias` / `venv_bin_dirs`** — these live in
  `willow/fylgja/` and are **fleet infrastructure**, not kart-specific: `willow_home`
  feeds store-root, secrets, config-mode across the whole fleet. kartikeya deliberately
  ships a *simplified standalone copy* (its own docstring says so), so canonicality runs
  the other way — fylgja is canonical, kartikeya is the derivative. Delegating would
  repoint the entire fleet's home/venv resolution at kartikeya's narrower version.

**Already byte-identical pure helpers — keep (nothing to gain):**
- **`trim_task_result`** and **`_parse_task_network_directives`** (which wraps
  `parse_task_network`, verified byte-identical across the trees). There is no drift to
  eliminate, and delegating stable ~8-line pure functions only adds a cross-package
  dependency edge. The Jaccard signal on these was import-line noise, not divergence.

**Coherence fix that fell out of the review** (parallel to Tier-2's): fylgja's
`willow_home` and kartikeya's diverge when `$WILLOW_HOME` is unset (fylgja →
`~/github/.willow` or the repo-local generated pack; kartikeya → `~/.willow`). Because
Tier-1 delegated home-derived sandbox paths (mcp_apps trust overlays, the fleet env
file, the nsswitch shim) to kartikeya while `_kart_logs_root`/`write_task_log` still use
fylgja, an unset `WILLOW_HOME` would split the sandbox and its logs across two homes —
Tier-1's proven equivalence had *quietly depended* on `WILLOW_HOME` being exported.
Fixed by pinning `WILLOW_HOME` (via `setdefault`, next to the Tier-1 env seams) to
fylgja's own resolved fleet home: idempotent for every fylgja caller, and it forces
kartikeya to resolve the same home, so all home-derived kart paths are coherent
unconditionally. Verified: with `WILLOW_HOME` unset, fylgja and kartikeya now resolve
the identical home; `test_kart_*` + `test_audit_verify.py` stay green (143/6);
audit-verify reports 0 gated regressions with `WILLOW_HOME` unset (the CI scenario).

**Stage-5 status after Tier 3:** the drift-window worklist is closed. Tier 1 delegated
the three isolation data-producers; Tiers 2–3 reviewed the remaining 21 pieces and found
they are correctly *not* delegatable (fleet-coupled or already identical), landing two
coherence fixes (`KART_SANDBOX_CONFIG`, `WILLOW_HOME`) that Tier 1's delegation had made
latent. The deliberately-deferred behaviour-change swaps (`scan_bash` fork-bomb
detection, `run_shell` resource caps) remain the only open kart items, each its own
opt-in security decision — specced below.

### 5.x — Deferred behaviour-change swaps (NOT equivalence migrations)

Tier 1 kept `scan_bash` and `run_shell` on willow-2.0's own implementations because
kartikeya's versions are strict **behaviour changes**, not byte-equivalent swaps —
each a security *upgrade* that would start rejecting/limiting task workloads that run
today. They are opt-in, and each wants its own reviewed PR with the delta below
witnessed. This is the pick-up-able worklist.

#### A. `scan_bash` — add fork-bomb / resource-exhaustion detection

**Delta (measured):** kartikeya's `scan_bash` runs one extra category willow-2.0's
lacks — `_RESOURCE_EXHAUSTION` (willow-2.0's `willow/fylgja/safety/security_scan.py`
has **zero** such patterns). All `SEV_HIGH`:
- Fork bomb, self-referential: `(?P<fn>[\w:]+)\s*\(\)\s*\{[^{}]*(?P=fn)[^{}]*\|[^{}]*&`
  (the backref keeps a normal `deploy() { build | log & }` from matching).
- Fork-bomb body: `:\s*\|\s*:\s*&` (i.e. `:(){ :|:& };:`).
- Infinite CPU spin: `while\s+(true|:)\s*;?\s*do\s*(:|true)?\s*;?\s*done`.

**Behaviour change:** a task/`script_body` containing any of these runs fine today
(willow-2.0's `check_kart_task` → `scan_bash` returns no issue), but would be
**blocked** after the swap (`SEV_HIGH` ⇒ `check_kart_task` returns an error and the
task never executes). Pure hardening — nothing that legitimately runs *should* match,
but that has to be witnessed, not assumed.

**Mechanism — two options, pick with review:**
1. *Delegate kart's scan* — point `core/kart_task_scan.py`'s `scan_bash` import at
   `kartikeya.security_scan.scan_bash`. Narrow: only kart task-scanning gains the
   patterns.
2. *Upgrade fylgja (preferred)* — add the three `_RESOURCE_EXHAUSTION` patterns to
   willow-2.0's own `willow/fylgja/safety/security_scan.py`. `scan_bash` is
   **fleet infrastructure** (also the IDE-native `PreToolUse` guard via `pre_tool.py`,
   same canonicality direction as `willow_home` in Tier 3), so the fleet-canonical
   home for the upgrade is fylgja — kart then inherits it, and the IDE hook gets the
   fork-bomb block too. Keeps the fleet the single source of truth.

**Verification gate:** `test_kart_*` + `test_audit_verify.py` green; add a positive
test (a fork-bomb string is blocked) and a negative control (`deploy() { build | log & }`
and similar legitimate `()`-functions still pass); grep the corpus / recent task history
for any real task that would newly trip it before enabling.

#### B. `run_shell` — resource caps (memory + PID ceilings)

**Delta (measured):** kartikeya's `run_shell` applies resource limits by default —
`resource_caps_enabled()` is True unless `WILLOW_KART_NO_RLIMIT ∈ {1,true,yes}`. It caps
memory (`KART_MEM_MAX`, default **2G**) and process count (`KART_PIDS_MAX`, default
**512**), preferring a cgroup-v2 leaf under an operator-delegated `KART_CGROUP_PARENT`
and falling back to POSIX rlimits (`RLIMIT_AS` / `RLIMIT_NPROC`) via `preexec_fn`. On
success it adds a `resource_limit` key to the result dict naming the mode used.
willow-2.0's `run_shell` has none of this.

**Behaviour change:** every sandboxed command gains a 2G memory ceiling and a 512-PID
ceiling by default; a task exceeding either is killed by the kernel; the result dict
grows a `resource_limit` key. A legitimate heavy build/test task could newly fail.

**Mechanism — delegate with an explicit caps decision:** swap `core/kart_sandbox.py`'s
`run_shell` to `kartikeya.sandbox.run_shell`, then choose one:
- *Caps-on (recommended, the point of the swap):* leave `WILLOW_KART_NO_RLIMIT` unset;
  tune `KART_MEM_MAX` / `KART_PIDS_MAX` to the fleet's real ceilings first; optionally
  delegate a `KART_CGROUP_PARENT` so caps use cgroups (cleaner kills) instead of rlimits.
- *Staged:* pin `WILLOW_KART_NO_RLIMIT=1` via `setdefault` at first (delegating the code
  but preserving today's no-cap behaviour byte-for-byte), then flip it on in a follow-up
  once the ceilings are validated — mirrors how Tier 1 injected its env seams.

**Verification gate:** `test_kart_*` must handle the new `resource_limit` output key
(check no test asserts an exact result-dict shape that the key would break); exercise a
task near each ceiling to confirm the kill path and the failure surfaces cleanly; confirm
the rlimit fallback works where no delegated cgroup parent exists. `test_kart_*` +
`audit-verify` stay green.

**Order note:** these two are independent of each other and of the closed Tiers 1–3;
either can land first. Both are security *tightenings*, so the safe sequence is
*measure the blast radius (corpus/history grep for `scan_bash`; ceiling probe for
`run_shell`) → land behind the opt-in → then enable*.

## 6. Relationship to other work

- `skills/kart-tasks.md` already documents the *current* (worker-required)
  reality and the network-permission footguns (B-19/B-21), with the worker-run
  command explicitly marked pending this lift.
- Closes the product-DOA gap; complements the identity/security work already
  done (`SECURITY_AUDIT.md`) that motivates willow-mcp as the successor.
