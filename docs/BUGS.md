# willow-mcp — Bug Log

A single running log of bugs found in willow-mcp, across all sessions. One row
per bug. This is the durable record; FRANK ledger entries, GitHub issues, and
`SECURITY_AUDIT.md` are the source material it's backfilled from and links to.

**Keep this current.** When a bug is found, add a row (Open). When it's fixed,
flip Status to Fixed and fill the Fix + Ref. Don't delete rows — a Fixed/Stale
row is the history. Security findings live in full in `SECURITY_AUDIT.md`; this
log carries a one-line entry and points there rather than duplicating.

**Conventions**
- **ID** — sequential `B-NN`, assigned in rough order of discovery. Stable; never reused.
- **Sev** — P0 (auth/data defeat) · P1 (integration/blocking) · P2 (reliability/correctness) · P3 (completeness/DX/test).
- **Status** — `Open` · `Fixed` · `Documented` (known, worked-around in docs, no code fix) · `Stale` (never real in current code) · `Wontfix`.
- **Ref** — canonical pointer: `L-*` = SECURITY_AUDIT finding · `PR #n` · `issue #n` · `FRANK <id>`.

## Summary

| ID | Sev | Status | Component | One-line | Ref |
|----|-----|--------|-----------|----------|-----|
| B-14 | P0 | Fixed | Kart sandbox / trust root | Kart bwrap had R+W to `$WILLOW_HOME/mcp_apps` (manifests + identity bindings) — untrusted runtime could rewrite the ACLs that gate it. Fixed: `mcp_apps` now `bound_ro` in bwrap | FRANK `baf2f63a`, `293b2130`; willow-2.0#777; probe `MAGSU06N` |
| B-15 | P3 | Fixed | knowledge / kb | `kb_startup_continuity` silently returned empty — filtered on a `tags`/`domain='continuity'` shape the adopted DB lacks. Fixed: read tags from the jsonb `content->'tags'` blob + always emit `_continuity_filter` | issue #20; probe `707E561A` |
| B-16 | P3 | Fixed | server pipeline | `_sanitize` fired before the permission gate — a denied caller could trip sanitizer errors first. Fixed: `_guarded` now runs gate → sanitize → rate | FRANK `90960b8b`; probe `4D9139B8` |
| B-17 | P2 | Fixed | schema / tasks | `task_status` never surfaced completion time — the adopted `tasks` table had no `completed_at` column. Fixed: added the column + a self-populating trigger on the shared DB, and mapped it; `steps` stays unmapped (still no such column) | this session; probe `R2BSZ9FZ` |
| B-18 | P3 | Fixed | diagnostics | `diagnostic_summary` returned verdict `degraded` when the caller merely omitted `app_id`. Fixed: missing `app_id` is a `caller_input` warn (surfaced in `problems` + manifest sub-check) that no longer degrades the verdict | this session; probe `E3265B66` |
| B-19 | P2 | Fixed | task interface / Kart | `task_submit` had no `allow_net`. Fixed: `allow_net=True` gated by a new `task_net` manifest permission (not in full_access) appends the worker's `# allow_net` directive | this session; probe `5H1M355V` |
| B-20 | P3 | Fixed | repo metadata / docs | GitHub "About" description read "Superseded by Willow 2.0 … now live in the monorepo" — stale, contradicting the active 2.0.0 repo; visible to anyone (surfaced in an external review). Fixed via `gh repo edit --description`; repo confirmed not archived | this session; DeepSeek review |
| B-21 | P0 | Fixed | task interface / Kart | `task_net` gate bypassable via task text — the worker reads egress policy from a `# allow_net` line in the stored task, but `task_submit` gated & appended that line only behind `if allow_net:`, so a `task_queue`-only caller could embed the directive with `allow_net=False` and get ungated egress (also `# allow_localhost`). Fixed: strip caller-supplied directive lines unconditionally before the gated append | this session; L-NET-01; PR #31 review §2a |
| B-01 | P0 | Fixed | oauth / gate | Serve-mode OAuth identity never bound to `app_id`; `app_id` taken from caller args, not the authenticated session | L-AUTH-02 |
| B-02 | P1 | Fixed | integration | No `safe_integration.py` — server invisible to Willow orchestration | L-INT-01 |
| B-03 | P2 | Fixed | server / rate limit | Unbounded `_buckets` dict keyed on raw caller `app_id` before validation | L-DOS-01 |
| B-04 | P2 | Fixed | db / knowledge | Empty/whitespace search query builds malformed SQL, unhandled crash | L-BUG-01 |
| B-05 | P2 | Fixed | db / Store | `Store._conn()` lock doesn't cover `execute`/`commit` — concurrent calls can interleave | L-CONC-01 |
| B-06 | P2 | Fixed | tests | Coverage was 1 of 7 source files — auth/gate/rate paths untested | L-TEST-01 |
| B-07 | P3 | Fixed | cli | `willow-mcp setup` referenced in docs/HTML but never implemented | L-DOC-01 |
| B-10 | P2 | Fixed | schema / knowledge | Confirmed `knowledge` mapping selected the `content` provenance blob as canonical text; real title/summary never surfaced; `domain` null | FRANK `90960b8b`/`88d13197`, issue #20, PR #21 |
| B-11 | P2 | Fixed | schema confirm | `schema_confirm_mapping` confirmed on name-match alone (assertion, not evidence) — no rendered sample shown | PR #21 |
| B-12 | P3 | Documented | serve / deploy | systemd `--user` serve unit doesn't inherit shell `WILLOW_PG_DB`/`WILLOW_STORE_ROOT`/`WILLOW_HOME` → serve reads `table_not_found` on data stdio sees | PR #18 |
| B-13 | P3 | Fixed | tests | Rate-limit tests shared one `app_id`, exhausting the token bucket → cross-test failures | (in-tree; `_buckets` reset in fixtures) |
| B-08 | P2 | Stale | packaging | `requirements.txt` unpinned — never existed in current `pyproject.toml` layout | L-REQ-01 |
| B-09 | P2 | Stale | gate | Silent fallback on missing SAP gate — `openclaw_sap_gate` gone in rewritten `gate.py` | L-AUTH-01 |

## Open

_None — all tracked bugs are Fixed, Documented, or Stale._

## Fixed

- **B-21 · P0 (this session)** — `task_net` capability gate was bypassable via
  the task text itself, defeating the separation B-19 established. The Kart
  worker (`willow-2.0/core/kart_sandbox.py`) decides network policy purely by
  scanning the *stored task text* for a directive line — egress on any
  `line.strip() == "# allow_net"`, loopback on `"# allow_localhost"`. In
  `task_submit`, both the `task_net` permission check **and** the `# allow_net`
  append lived behind the same `if allow_net:` guard, and nothing inspected
  caller-supplied `task` text. So a caller holding only `task_queue` could
  submit `task="curl …\n# allow_net"` with the default `allow_net=False`: the
  gate never fired (it's keyed off the *argument*, not the *text*), the
  directive was stored verbatim, and the worker granted egress. `# allow_localhost`
  was never gated at all. **Fix:** strip any caller-supplied line matching
  either directive (worker's exact `line.strip() ==` semantics) from `task`
  **unconditionally**, before the permission-gated append — so `# allow_net` can
  only ever enter through the path that already checked `task_net`, and
  `# allow_localhost` can never be self-granted. Full detail in
  `SECURITY_AUDIT.md` (L-NET-01). Regression tests in `tests/test_server.py`
  (`…strips_caller_supplied_net_directive_when_denied`,
  `…strips_caller_supplied_localhost_directive`,
  `…permitted_net_survives_caller_directive_dedup`); full suite 205→208.
- **B-20 · P3 (this session)** — the GitHub repo "About" description read
  *"Superseded by Willow 2.0 — MCP, SOIL, Postgres KB, and Kart now live in the
  monorepo."* That was true when willow-mcp was being folded in, but is now
  stale and contradicts reality: this repo is the active 2.0.0 home (README
  presents it as a live standalone tool, PRs landing). It lives in GitHub repo
  metadata, not the git tree, so a file grep misses it — it surfaced only via an
  external review (DeepSeek) reading the repo page. Fixed with
  `gh repo edit --description "Agent-neutral MCP server with persistent memory
  (SOIL + Postgres KB) and a sandboxed task queue. Manifest-based ACL; works
  with any stdio MCP client."` Repo confirmed **not archived** (`isArchived=false`).
  Note: the published PyPI 1.2.0 description is separate (release held) and does
  not carry this note.
- **B-17 · P2 (this session)** — `task_status` now surfaces task completion
  time. Root cause: the adopted `tasks` table genuinely had **no**
  `completed_at` column (the null was not an unmapped-but-present column — the
  data wasn't there). Fix (operator chose the upstream option): added the column
  and a self-populating trigger on the shared fleet DB, then mapped the field.
  ```sql
  ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at timestamptz;
  CREATE OR REPLACE FUNCTION set_task_completed_at() RETURNS trigger AS $$
  BEGIN
    IF NEW.status = 'completed' AND NEW.completed_at IS NULL
       AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'completed') THEN
      NEW.completed_at := now();
    END IF;
    RETURN NEW;
  END; $$ LANGUAGE plpgsql;
  CREATE TRIGGER trg_task_completed_at BEFORE INSERT OR UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION set_task_completed_at();
  ```
  willow-mcp itself needed no code change (`completed_at` was already a canonical
  `_TASK_FIELDS` entry); the confirmed tasks mapping artifact was updated to map
  it. `steps` stays unmapped — that column still doesn't exist, which is correct.
  Forward-only: pre-existing completed rows keep `completed_at` null (their true
  completion time is unknown; no backfill from `updated_at`, which fires on any
  update). **Verified**: probe `R2BSZ9FZ` completed with
  `completed_at: 2026-07-08T12:12:41`, and `_unmapped` is now just `["steps"]`.
- **B-19 · P2 (this session)** — `task_submit` can now run network-bearing
  tasks. It gained an `allow_net` parameter gated by a new `task_net` capability
  permission in `gate.py` — deliberately **not** part of `task_queue` or
  `full_access`, so a broad grant never silently carries sandbox network egress
  (same separation spirit as B-14). When granted, `task_submit` appends the Kart
  worker's `# allow_net` directive (`core/kart_sandbox.py task_allows_network`)
  to the task text, so the willow-2.0 worker builds the sandbox with egress
  enabled. Without the permission, `allow_net=True` returns `net_denied` before
  any write. **Verified** end-to-end: probe `5H1M355V` (task_net app,
  `allow_net=True`) ran with `network_mode: full`; control `TNH4B9FQ`
  (`allow_net=False`) ran `isolated`; a `full_access`-only app was denied.
  Operator note: grant `task_net` host-side only, never via the sandbox (B-14).
- **B-18 · P3 (this session)** — `diagnostic_summary` no longer returns verdict
  `degraded` just because the caller omitted `app_id`. That case was a caller
  omission, not an install defect (store/Postgres/schema/bindings all `ok`), yet
  it folded into the one field meant to answer "is this install wired
  correctly." Fix: the missing-`app_id` manifest warn is tagged `caller_input`;
  it still surfaces in `problems` and the `manifest` sub-check (`status: warn`,
  `reason: no_app_id`), but `_derive_verdict` ignores caller-input warns, so the
  verdict stays `ok` when every probed subsystem is healthy. A real manifest
  warn (empty permissions → every call denied) is not `caller_input` and still
  degrades. **Verified** via probe `E3265B66`: `diagnostic_summary(app_id="")` →
  `verdict: ok`, `manifest.status: warn`, `problems: [(manifest, warn, caller_input=True)]`.
- **B-15 · P3 (issue #20)** — `kb_startup_continuity` no longer silently
  returns empty on the adopted `willow_20` DB. The old filter keyed off a
  `domain='continuity'` value (the `domain`/`project` column is ~all-null — no
  such value) and a top-level `tags` column that doesn't exist; tags actually
  live inside the jsonb `content` blob (physically the `content` column, which
  is unmapped as a canonical field because canonical `content` maps to
  `summary` — B-10). Fix: when there's no top-level `tags` column but a jsonb
  `content` column is present (discovered by introspection, not assumed), read
  continuity atoms from `content->'tags' @> '["continuity"]'`. The result now
  always carries a `_continuity_filter` listing exactly what was searched, so an
  empty result reads as "genuinely nothing to continue" rather than "the query
  couldn't target this schema" (fail-loud). **Verified** via probe `707E561A`:
  returns the 9 continuity-tagged atoms that the old path missed. Tests added in
  `test_server.py` (jsonb path, top-level-tags preference, fail-closed).
- **B-16 · P3 (FRANK `90960b8b`)** — `_sanitize` no longer runs before the
  permission gate. `_guarded` now runs **gate → sanitize → rate → dispatch →
  receipt**: an unpermitted caller gets a clean permission denial as the first
  signal instead of a sanitizer error for a call it was never allowed to make.
  Gate still validates the app_id shape and precedes the rate check, so
  L-DOS-01 is preserved. **Verified** via probe `4D9139B8`: unpermitted app +
  illegal collection → gate denial (was sanitize error); permitted app + illegal
  collection still hits the sanitizer. Ordering + control tests in
  `test_server.py`.
- **B-14 · P0 (FRANK `baf2f63a`/`293b2130`, willow-2.0#777)** — Kart bwrap
  sandbox no longer has R+W to willow-mcp's on-disk trust root. The host stdio
  server and the Kart sandbox share `$WILLOW_HOME`, and `mcp_apps/` (per-app
  `manifest.json` ACLs **and** `_identity_bindings/` confirmed OAuth bindings)
  used to sit inside the sandbox's read-write mount — so an untrusted runtime
  could rewrite its own manifest to self-escalate past `gate.py`, or mint/flip a
  `confirmed:true` identity binding the host serve process would honor
  (defeating L-AUTH-02's "confirmation is stdio/host-only" control). Fixed on
  the willow-2.0 side: `$WILLOW_HOME/mcp_apps` is now an explicit `bound_ro`
  mount nested inside the `bound_rw` `.willow` parent, so the trust root is
  read-only even though its parent is writable. **Verified** 2026-07-08 via Kart
  probe `MAGSU06N`: `touch mcp_apps/_b14_probe` → `Read-only file system`;
  sandbox manifest shows `mcp_apps` under `bound_ro`. Load-bearing for the
  fetch-scope gating layer (a scope gate is worthless if the sandboxed fetcher
  can rewrite the scope file). Never author manifests/bindings via the sandbox —
  host-side only.
- **B-01 · L-AUTH-02 (P0)** — serve-mode identity binding implemented
  (`identity_binding.py` + `oauth.py`/`gate.py`/`server.py` wiring +
  `willow-mcp confirm-binding` CLI); `app_id` now resolved from the confirmed
  binding, never caller args. See SECURITY_AUDIT.
- **B-02 · L-INT-01 (P1)** — `safe_integration.py` with `status()` added.
- **B-03 · L-DOS-01 (P2)** — `_guarded` pipeline reordered to
  sanitize→gate→rate→dispatch→receipt; invalid `app_id` denied before it can
  become a `_buckets` key.
- **B-04 · L-BUG-01 (P2)** — early `if not tokens` guard in `Store.search` and
  `knowledge_search`; regression tests added.
- **B-05 · L-CONC-01 (P2)** — `Store` lock widened to an `RLock` covering
  `execute`/`commit`; 8×20 concurrent-write regression test added.
- **B-06 · L-TEST-01 (P2)** — suite grew 12→44 (then further); gate/vault/
  identity/server pipelines now covered.
- **B-07 · L-DOC-01 (P3)** — `willow-mcp setup` (+ `confirm-binding`) CLI
  subcommands implemented; secrets prompted via `getpass`/stdin.
- **B-10 (P2, FRANK `90960b8b`/`88d13197`, issue #20, PR #21)** — knowledge
  mapping re-confirmed with `{content: summary, domain: project}` after review;
  root class fixed by requiring rendered-sample evidence at confirm (B-11).
  Verified `kb_at` returns full title/summary matching the main server.
- **B-11 (P2, PR #21)** — `schema_confirm_mapping` gained `preview=True` +
  `render_sample`: confirm now shows real projected rows before writing, so a
  name-match is checked against actual data. Skill `schema-confirm.md` updated.
- **B-13 (P3, in-tree)** — test fixtures reset `server._buckets` so shared
  `app_id` across `_guarded` calls no longer exhausts the rate limiter.

## Documented (no code fix)

- **B-12 (P3, PR #18)** — serve mode env gap. The systemd `--user` unit is
  started by systemd, not the shell, so `WILLOW_PG_DB`/`WILLOW_STORE_ROOT`/
  `WILLOW_HOME` exported in `.bashrc` don't reach it; serve reads then
  `table_not_found` on data stdio can see. This is expected for an
  externally-configured DB (willow-mcp adapts to a foreign DB by design), not a
  code defect. Documented in README ("Turning serve mode on and off") and
  `skills/willow-serve.md`; fix is `systemctl --user import-environment ...` or
  an `environment.d` file. Candidate future polish: install-time env-freeze into
  the unit.

## Stale (never real in current code)

- **B-08 · L-REQ-01** — predates the `pyproject.toml` layout; no `requirements.txt` exists.
- **B-09 · L-AUTH-01** — `openclaw_sap_gate` removed in the manifest-ACL rewrite of `gate.py`.
