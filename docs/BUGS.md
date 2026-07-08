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
| B-14 | P0 | **Open** | Kart sandbox / trust root | Kart bwrap has R+W to `$WILLOW_HOME/mcp_apps` (manifests + identity bindings) — untrusted runtime can rewrite the ACLs that gate it | FRANK `baf2f63a`, `293b2130`; willow-2.0#777 |
| B-15 | P3 | Open | knowledge / kb | `kb_startup_continuity` silently returns empty — keyed off a `tags`/continuity-domain shape the adopted DB doesn't have | issue #20 |
| B-16 | P3 | Open | server pipeline | `_sanitize` fires before the permission gate on `store_put` — a denied caller can still trip sanitizer errors first (ordering nit) | FRANK `90960b8b` |
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

### B-14 · P0 · Kart bwrap sandbox has R+W to willow-mcp's on-disk trust root
**Component:** Kart sandbox mount config (willow-2.0) × willow-mcp `gate.py` trust root
**Found:** 2026-07-08 (sessions `6386031b`, `c700ed9d`), live-testing operator-granted `confirm-binding`.
**Ref:** FRANK `baf2f63a` (+ corroboration `293b2130`), GitHub **willow-2.0#777**, memory `project_willow_mcp_confirm_binding_cross_runtime_leak`.

The host stdio willow-mcp server and the Kart bwrap sandbox share
`$WILLOW_HOME=/home/sean-campbell/github/.willow`. willow-mcp's entire on-disk
trust root — `mcp_apps/` (per-app `manifest.json` ACLs **and** `_identity_bindings/`
confirmed OAuth bindings) — sits inside the sandbox's read-write mount. Verified
from inside a Kart task (`W_OK` stat only, no writes): `mcp_apps/`,
`mcp_apps/willow/manifest.json`, `_identity_bindings/`, and the confirmed
binding file are all writable; the confirmed binding (identity + email) is
readable.

**Impact:** the untrusted execution runtime can (a) rewrite its own manifest to
`full_access` and self-escalate stdio permissions past `gate.py`; (b) mint/flip
a `confirmed:true` identity binding for any `(issuer, subject) → any app_id`,
which the host serve process honors via `resolve_app_id` — defeating the
"confirmation is stdio/host-only, never an MCP tool" control (L-AUTH-02); (c)
read bound identity + email. Not a logic bug in `confirm_binding`/`_gate` (those
are correct) — the sandbox boundary and the ACL boundary are not separated.

**Fix (owner: willow-2.0):** Kart bwrap must not mount `$WILLOW_HOME/mcp_apps`
read-write into the sandbox — at minimum `_identity_bindings/` and every
`*/manifest.json` read-only, ideally not mounted at all. Alternatively move
willow-mcp's trust root outside any sandbox-writable path. Load-bearing for the
fetch-scope gating layer: a scope gate is worthless if the sandboxed fetcher can
rewrite the scope file that gates it.

### B-15 · P3 · `kb_startup_continuity` silently returns empty
**Component:** knowledge / kb
**Found:** 2026-07-08, stdio live test.
**Ref:** issue #20 (comment 4914394048).

Against the adopted `willow_20` DB, `kb_startup_continuity` keys off a `tags`
column and a continuity domain that don't exist in that schema (tags live inside
a `content` JSONB blob; no continuity-domain rows). It returns empty with no
error — a silent no-op that looks like "nothing to continue" rather than "query
shape doesn't match this DB." Recommended issue #20 stay open for this residual.

### B-16 · P3 · `_sanitize` runs before the permission gate on `store_put`
**Component:** `server.py` `_guarded` pipeline
**Found:** 2026-07-08, stdio live test.
**Ref:** FRANK `90960b8b` (evidence.minor).

On `store_put`, input sanitization fires before `_gate()`, so a caller who lacks
permission can still surface a sanitizer error instead of a clean permission
denial. Minor ordering nit, not a security hole (the gate still denies dispatch);
worth aligning so denial is the first signal. Note L-DOS-01's fix already
reordered rate-check after gate for a different reason — same spirit.

## Fixed

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
