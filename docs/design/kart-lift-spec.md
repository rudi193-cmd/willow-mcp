# Spec: Kart Lift — extract a standalone `kart` package

Status: **IMPLEMENTED** (2026-07-08). Stages 1–3 shipped; B-22 Fixed. Engineering
spec for the migration whose direction is set in `kart-productionization.md`.

> **Reading note.** The package shipped as **`kartikeya`** (PyPI, 0.0.1), the name
> locked in §1. The body of this spec was written before that rename and says
> `kart` throughout — read every bare `kart` package reference as `kartikeya`,
> and `kart[llm]` as `kartikeya[llm]`. The text is preserved as the decision
> record, not corrected in place.
>
> **As-shipped:** stages 1–3 landed (extract → willow-mcp integration → hard
> dependency + docs), via willow-mcp PRs #35 and #36. Stage 4 (worker heartbeat
> in `fleet_health`/`diagnostic_summary`) and stage 5 (willow-2.0 migration off
> its `core/kart_*` copy) remain open. The drift window in §9 is therefore still
> open by design.

**Decisions locked (operator, 2026-07-08):**
1. **Shared package** — Kart becomes its own installable package; willow-mcp
   (and later willow-2.0) *depend* on it rather than vendoring a copy. No drift.
2. **Product-neutral default** sandbox mount policy.
3. **SQLite task backend** — the queue must run with **no Postgres**; a
   zero-infra `pip install` can execute tasks.

The big consequence: **the `kart` package must not import willow-mcp or
willow-2.0.** Its coupling to a host (DB access, `$WILLOW_HOME`) is inverted
into a small **backend interface** the host implements. Kart owns the sandbox,
worker loop, lanes, and scan; the host owns "where tasks live" and "where files
live."

## 0. Goal & acceptance

A clean `pip install willow-mcp` (which pulls in `kart`) can execute a submitted
task end-to-end with **no Postgres and no willow-2.0 present**:
```
pip install willow-mcp          # depends on kart
willow-mcp worker &             # drains the queue via the SQLite backend
# via MCP:  task_submit(task="echo hi") -> task_status -> {status: completed, result: "hi"}
```
plus the same for an `allow_net=True` task with `task_net` granted (sandbox +
gate work standalone), and the `kart` suite green with neither willow-mcp nor
willow-2.0 on `sys.path`.

## 1. The `kartikeya` package

New **standalone repo** (operator decision). Distribution + import name
**`kartikeya`** — bringing back Kart's full name (Skanda / Murugan, the
six-faced commander of the divine armies; `docs/audits/KART_SANDBOX_AUDIT_2026-06-11.md`).
"Kart" stays the colloquial short form in prose and existing `kart:*` task ids.
~2,200 LOC lifted from willow-2.0 `core/kart_*`; own `pyproject`; depends only
on stdlib + optional extras.

```
kartikeya/                     # new standalone GitHub repo
  pyproject.toml               # name = "kartikeya"; deps: none (base); extras: [llm]
  src/kartikeya/
    __init__.py                # run_worker(), execute_task_row(), TaskQueue
    sandbox.py                 # from kart_sandbox.py
    execute.py                 # from kart_execute.py
    worker.py                  # from kart_worker.py — takes a TaskQueue
    lanes.py                   # from kart_lanes.py
    task_scan.py               # from kart_task_scan.py
    queue.py                   # TaskQueue ABC + SqliteTaskQueue reference impl
    config.py                  # sandbox mount-policy loader + neutral default
    data/kart-sandbox.json     # product-neutral default (§5); filename kept for continuity
  tests/                       # carried test_kart_* + queue-backend tests
```
Console script: `kartikeya worker` (with a `kart` alias for muscle memory).
willow-mcp keeps its own `willow-mcp worker` subcommand that constructs the
backend and calls into the library (§3).

### 1a. Dependency dispositions

| willow-2.0 dependency | Disposition in `kart` |
|---|---|
| `kart_sandbox/execute/worker/lanes/task_scan` | **Lifted in** as the package core |
| `core.pg_bridge.PgBridge` | **Inverted** → `TaskQueue` interface (§2); host supplies impl |
| `willow.fylgja.willow_home` | **Inverted** → host passes a work-root; `kart` falls back to `$WILLOW_HOME`/CWD |
| `willow.fylgja.python_env` | **Reimplemented** minimally in `kart` (stdlib `sysconfig` + venv detect) |
| `core.loop_heartbeat` | **Callback seam** — `on_heartbeat` hook, default no-op |
| `core.run_ledger` | **Callback seam** — `on_run_event` hook, default no-op |
| `core.grove_gate` | **Dropped** (fleet governance) |
| `core.outcomes` | **Dropped** (default) / host callback if wanted |
| `core.llm_edge` | **Optional extra** `kart[llm]`; LLM task type disabled if absent |

No `core.*` / `willow.fylgja.*` import survives in `kart`.

## 2. The `TaskQueue` backend interface

The one seam that inverts host coupling. `kart` defines the ABC; the worker
loop is written against it:

```python
class TaskQueue(ABC):
    @abstractmethod
    def claim_pending(self, agent: str, limit: int) -> list[TaskRow]: ...   # atomic claim → 'running'
    @abstractmethod
    def mark_running(self, task_id: str) -> None: ...
    @abstractmethod
    def mark_done(self, task_id: str, *, status: str, result: str) -> None: ...  # completed|failed + completed_at
    @abstractmethod
    def pending_count(self) -> QueueStats: ...   # for liveness/fleet_health
```
`TaskRow` = `{task_id, task, agent, submitted_by, status}`.

Three implementations:
- **`SqliteTaskQueue`** (shipped *in* `kart`) — reference/zero-infra backend.
  Atomic claim via a single `UPDATE tasks SET status='running' WHERE task_id IN
  (SELECT task_id FROM tasks WHERE status='pending' AND agent=? LIMIT ?)
  RETURNING …` inside `BEGIN IMMEDIATE` (SQLite serializes writers; safe).
- **willow-mcp's Postgres impl** (in willow-mcp) — maps through willow-mcp's
  schema-adaptation (`_TASK_FIELDS`), so it works against an *adopted* `tasks`
  table, using `FOR UPDATE SKIP LOCKED` for the claim.
- **willow-2.0's impl** (later) — wraps its existing `PgBridge`.

This is also exactly what makes the **SQLite backend** (decision 3) fall out
naturally rather than being bolted on.

## 3. willow-mcp integration

willow-mcp stays thin — it does **not** contain sandbox/worker code:
- Adds `kart` to `dependencies`.
- Implements `WillowMcpTaskQueue(TaskQueue)` over its adopted `tasks` table
  (Postgres via schema-adaptation) **and** wires the shipped `SqliteTaskQueue`
  for the no-Postgres path; backend chosen by config (Postgres if `WILLOW_PG_*`
  present, else SQLite under `WILLOW_STORE_ROOT`).
- Adds `willow-mcp worker` (argparse subcommand, consistent with `--serve`):
  `--lane fast|batch`, `--slots N`, `--once`. Constructs the backend + calls
  `kart.run_worker(queue=…, lane=…)`.
- Ships the `CREATE TABLE tasks` DDL the review flagged missing
  (`docs/schema/`), for both SQLite and Postgres, matching `_TASK_FIELDS`.

## 4. Security posture (preserve + test)

- **bwrap isolation** and **credential-prefix gating** carry over unchanged.
- **Net-directive contract stays split (B-21 ↔ B-22):** the worker grants
  egress iff the *stored task text* has a `# allow_net` line; willow-mcp's
  `task_submit` is the only writer of that line, only under `task_net`,
  stripping caller copies. Ship an **end-to-end test in willow-mcp**: a
  `task_queue`-only app submitting `task="curl …\n# allow_net"` with
  `allow_net=False` runs **network-isolated**; a `task_net` app with
  `allow_net=True` runs with egress. Most likely seam to regress in the lift.
- `kart` also gets a unit test that `task_allows_network()` still keys on
  `line.strip() == "# allow_net"` exactly (the contract willow-mcp's strip
  depends on).

## 5. Sandbox config — product-neutral default

Vendored `kart/data/kart-sandbox.json`: keep `WILLOW_`, `PG`, `POSTGRES`,
`OLLAMA_`, `GIT_` prefixes and generic bind paths; **drop** fleet-only
`GROVE_`/`SAFE_` prefixes and fleet bind paths from the *default*. Resolution:
`$KART_SANDBOX_CONFIG` → `$WILLOW_HOME/kart-sandbox.json` → vendored default.
Templating (`{{HOME}}`, `{{WILLOW_ROOT}}`) preserved. The fleet keeps its richer
policy via the override file — parity without shipping fleet surface.

## 6. Test migration

Carry `tests/test_kart_*.py` into `kart/tests/`, replacing fleet imports with a
fake `TaskQueue`, a tmp `kart-sandbox.json`, and no-op heartbeat/run callbacks.
Add `SqliteTaskQueue` backend tests (concurrent claim, no double-execution).
Gate bwrap tests on `bwrap_available()` so CI without bwrap skips, not fails.

## 7. Optional LLM task type

`kart[llm]` extra. Base worker runs shell tasks with zero LLM deps; an LLM task
submitted without the extra fails cleanly (`{"error": "llm task type requires
kart[llm]"}`), never an import crash. (willow-2.0 supplies its own `llm_edge`
adapter behind the extra's hook.)

## 8. Staged PRs / milestones

Spans two (maybe three) repos; sequence willow-mcp value first.

1. **Extract `kart` (new package):** lift the 5 files, sever fleet imports per
   §1, define `TaskQueue` + `SqliteTaskQueue`, callback seams, neutral config.
   *Acceptance: `kart`'s own suite green standalone; `pip install kart` +
   SqliteTaskQueue executes a shell task in a sandbox.*
2. **willow-mcp integration:** depend on `kart`, add `WillowMcpTaskQueue`
   (Pg + SQLite), `willow-mcp worker`, DDL. *Acceptance: §0 end-to-end on a
   clean venv, no Postgres.*
3. **Security e2e + docs → B-22 Fixed:** the §4 net-gate e2e test, README
   quickstart, fill `skills/kart-tasks.md` §0 worker-run section, honest
   `pyproject`.
4. **Liveness:** worker heartbeat via the `on_heartbeat` seam surfaced in
   `fleet_health`/`diagnostic_summary` (review §1).
5. **willow-2.0 migration (separate, later):** point willow-2.0 at the `kart`
   package, delete its `core/kart_*`. Ends drift. Can trail well behind stage 3.
6. **Optional:** `kart[llm]`, systemd templates, batch-lane polish.

## 9. Decisions & remaining questions

**Locked:**
- Repo: **new standalone GitHub repo** (operator).
- Name: **`kartikeya`** (operator — "bring back Kart's full name").
- Shared package · product-neutral default · SQLite backend (top of doc).

**Working assumptions (operator may override):**
- **willow-2.0 migration is deferred to stage 5** — accepting a temporary
  window where willow-2.0 keeps its `core/kart_*` copy while willow-mcp depends
  on `kartikeya`. Rationale: ship willow-mcp value (close B-22) before touching
  the live fleet.
- **`kartikeya` publish stays under the operator gate**, same as willow-mcp
  (release-state hold), until explicitly released — even though its surface is
  lower-risk than willow-mcp's OAuth layer.

**Resolved at extract time:**
- PyPI `kartikeya` was claimable and is published (0.0.1). The `kart` alias
  console-script name did not collide.
