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
| B-21 | P0 | Fixed | task interface / Kart | `task_net` gate bypassable via task text — the worker reads egress policy from a `# allow_net` line in the stored task, but `task_submit` gated & appended that line only behind `if allow_net:`, so a `task_queue`-only caller could embed the directive with `allow_net=False` and get ungated egress (also `# allow_localhost`). Fixed: strip caller-supplied directive lines unconditionally before the gated append | this session; L-NET-01; PR #32; PR #31 review §2a |
| B-22 | P1 | Fixed | packaging / Kart | Product shipped **no task executor** — `pyproject` advertised a "Kart task queue" but no worker/sandbox was in the package; a clean `pip install` left every task `pending`. Fixed: Kart extracted as the published **`kartikeya`** package (PyPI) and made a hard dependency; `willow-mcp worker` + `WillowMcpTaskQueue` (Pg/SQLite) drain the queue | this session; `docs/design/kart-lift-spec.md`; PRs #35, #36; kartikeya 0.0.1 |
| B-23 | P3 | Fixed | process / skills+hooks | Task-queue surface (`task_submit`/`task_net`, B-19; `# allow_net` footgun, B-21) shipped with no skill or hook, violating the "hooks/skills ship with the tool" rule (`docs/design/hooks-and-skills.md` §2). Fixed: added `skills/kart-tasks.md` + a `task_submit` matcher on `pre_tool_use.py` warning on hand-embedded net directives | this session; operator-caught |
| B-24 | P0 | Fixed | db / store | `store_*` tools (put/get/list/update/search/delete/search_all) had no cross-app isolation — `app_id` was discarded after the permission gate, `db.py` never scoped by it, so any app with `store_read`/`store_write`/`full_access` could read/write/delete every other app's SOIL data. Fixed: opt-in `store_scope` manifest field (exact/prefix-wildcard collection allowlist), checked by all six single-collection tools + `store_search_all`; unscoped apps keep the shared-fleet-store default | L-ISO-01; PR #31 review §2b; this session |
| B-25 | P1 | Fixed | gate / store | `gate.store_scope()` **failed open**: an invalid `app_id`, a missing/unparseable manifest, or a malformed `store_scope` all returned `None` — *unrestricted* — with only a log warning. `"store_scope": "myapp_*"` (a string, the obvious typo for this field) silently granted full store access to an operator who believed the app was confined, inverting `gate.py`'s own header contract ("Fail-closed: missing app_id, missing manifest … → deny"). Fixed: all three paths return `[]` (deny-all); explicit `null` still means "no policy declared". Malformed scope logs at `ERROR` | follow-up to B-24; this session |
| B-26 | P2 | Fixed | task interface / worker | Task queue had **no liveness signal** — `task_submit` returned `{"status":"pending"}` identically whether a worker was about to run it or none existed, so a stranded queue was indistinguishable from a busy one. Fixed: `willow-mcp worker` publishes a heartbeat via kartikeya's `on_heartbeat` seam; `fleet_health` gains `workers`/`stranded`, `diagnostic_summary` gains a `worker` check | Kart lift stage 4; this session |
| B-27 | P3 | Fixed | packaging / docs | Three code paths told operators to `pip install willow-mcp[worker]` — an extra that **does not exist**; `kartikeya` has been a hard dependency since B-22, so the advice was unrunnable | found during B-26; this session |
| B-28 | P3 | Open | schema / tasks | `completed_at` stays null on **failed** tasks. B-17's `set_task_completed_at()` trigger fires only on `NEW.status = 'completed'`, so a failed task never records when it finished (willow-mcp's own `mark_done` sets it correctly; the shared-DB trigger is the gap). Fix requires an `ALTER`/`CREATE OR REPLACE` on the shared fleet Postgres — **operator-gated**, not applied unilaterally | observed live, probe `1T8G5WG5`; follow-up to B-17 |
| B-29 | P0 | Fixed | gate / consent | `allow_net` egress was gated **only** by the `task_net` manifest capability — the operator's standing `consent.internet` gated nothing. The fleet flag `consent_internet_gates_allow_net` was declared `implemented: false, status: deferred`, so the switch existed and was wired to nothing. Fixed: two-key gate (`task_net` **and** `consent.internet`), read fail-closed | egress-membrane design; FRANK `cc553729`; this session |
| B-30 | P1 | Fixed | consent / config | The two consent files **disagreed** and the one an operator would naturally edit appeared inert. `consent.json` said `internet: false, lan: false`; `settings.global.json` said `true, true`. **First diagnosis was wrong:** `consent.json` is not a legacy leftover but a **write-only mirror** — `save_global_settings(sync_legacy=True)` (the default) and Grove's consent toggle both rewrite it on every save, while it is *read* only when the canonical file is absent. So it drifts silently and a delete does not stick. Resolved by re-syncing the mirror from canonical; the misleading "delete the legacy file" advice is gone from `diagnostic_summary` and `consent.py` | observed live; corrected 2026-07-09 |
| B-31 | P1 | Open | consent / willow-2.0 | `global_settings.py` **fails open**: `DEFAULT_CONSENT` is all-`True`, and `_normalize_consent()` returns those defaults for any non-dict — a missing, truncated, or malformed consent block resolves to *all permitted*. Same inversion as B-25. willow-mcp now reads fail-closed independently; the writer is unfixed and out of this repo | cross-repo (willow-2.0); this session |
| B-32 | P1 | Open | gate / sudo invariant | A **host-side agent can self-grant `task_net`** by writing the manifest with its own file tools, then use it. B-14 made `mcp_apps/` `bound_ro` to the *sandbox*; nothing constrains the host-side agent. This violates the sudo invariant (FRANK `90e52ab7`): *a model may REQUEST egress, never CONFIRM it — request and confirm are separate authorities*. **Mitigated, not closed:** egress is now a time-boxed operator-issued lease (`willow-mcp grant-net`, ≤3h, no MCP tool can mint one), the sandbox lane is closed outright, and `diagnostic_summary` names every key the process could forge. The host lane needs `chown` + `WILLOW_MCP_STRICT_TRUST_ROOT=1` — a deployment step, operator-gated | FRANK `90e52ab7`; §0.1/§0.3; L-NET-02; this session |
| B-33 | P1 | Open | consent / Kart sandbox | The documented fleet-wide egress off switch is **writable from inside bwrap**. B-14 bound `$WILLOW_HOME/mcp_apps` `ro`; nobody protected the consent file beside it. Measured from inside the sandbox: `settings.global.json` **writable**, `consent.json` **writable**, `mcp_apps/willow/manifest.json` read-only, `_net_leases` protected. `$WILLOW_HOME` is `bound_rw` for *every* task, network-isolated or not. **Scoped honestly:** this raises **key 2 only** — an attacker still needs `task_net` (manifest, ro) and a live lease (protected). But the one control documented as the kill switch is the one the untrusted runtime can write. Falsifies "Flipping `consent.internet` to `false` stops egress fleet-wide, instantly" in `README.md`, `SECURITY_AUDIT.md` (L-NET-02 + B-29 close-out), and `skills/kart-tasks.md`. **Fix:** bind both files `bound_ro`, exactly as B-14 did for `mcp_apps/`; correct the three docs. Pairs with B-31 (`global_settings.py` fails open) — same file, same review. **Corollary:** `flag_enabled()` has zero call sites, so `consent_internet_gates_allow_net` is a record, not a gate; if anyone wires it into the egress path they add a fourth key living in a sandbox-writable file — don't | probed from inside bwrap 2026-07-09; filed 2026-07-09; follow-up to B-14/B-29/B-32 |
| B-34 | ~~P0~~ | Stale | gate / orchestrator seat | ~~`human_only` is a dead field and `WILLOW_HUMAN_ORCHESTRATOR` is read by no code. Any agent holding `app_id=willow` can dispatch, verify, and clear.~~ **FALSE. The gate exists, is wired, and fires.** `human_session.py:41` reads `WILLOW_HUMAN_ORCHESTRATOR`; `server.py:201` calls `orchestrator_write_denial(effective, tool_name, serve_mode=…)` and `:202` returns it; the denial string `orchestrator_human_required` is at `human_session.py:60`, not absent. Two layers, conflated in the original: `gate.py` is the **manifest ACL** (it does contain the three tools), `human_session.py` is the **host attestation** applied after it. Observed firing on a live `dispatch_send` by the willow seat, 2026-07-09T12:26Z (FRANK `66bfd8b3`). **Root cause of the false alarm:** the probe called `diagnostic_summary()` with no `app_id`, so `is_orchestrator_app(None)` short-circuited `orchestrator_write_denial` to `None` — the gate was tested by not being the identity it guards. Withdrawn by root before any patch; had it been actioned, a working trust boundary would have been rewritten or deleted. Moved to *Stale* | filed 2026-07-09 (willow seat); refuted and withdrawn same day — FRANK `c4f7bec5`, `e4759e8b` |
| B-35 | P1 | Open | governance / envelope registry | **Metered envelopes are unmetered; the citation the meter derives from is never written.** `envelopes/pre-approved.json` mandates `use_count_source: "frank"` — a count *derived* by tallying `envelope_citation` ledger entries, deliberately not stored ("a stored counter is mutable state an agent could touch"). The strings `envelope_citation` and `envelope_id` have **zero** matches across all of willow-2.0. `ledger_read()` (`core/pg_bridge.py:3214`) filters by project + limit only. So `max_count: 20` (`env-pr.merge-willow2-master`) and `max_count: 40` (`env-dispatch-fleet-sessions`) enforce nothing, `EDQUOT` can never fire, and verb 13 `envelope.apply` — the act that licenses the orchestrator seat — is `enforced_by: null`. Cross-repo (willow + willow-2.0); logged here because `gap_log` is gate-denied to `app_id=willow` (B-36) | found 2026-07-09 (willow seat); `syscall-table.json` invariants §13–19 |
| B-36 | P2 | Open | gate / permission groups | `gap_log`/`gap_list`/`gap_resolve` (PR #54) and `kb_startup_continuity` are gate-denied for `app_id=willow`: the `orchestrator` group's 27-tool allow-list carries no `gap_*` verb and no `kb_startup_continuity`. The tool built to record "we don't know this yet" cannot be called by the seat whose job is noticing. **Recommendation: do not widen the group.** The denial is severance working one tool early — willow-mcp's backlog belongs to willow-mcp's participants; the fleet keeps its own in FRANK/KB. But note the cut is illusory: `gaps` is a live SOIL collection **in the fleet store** under `WILLOW_HOME`, so the gate denies the *tool* while the *data* sits in willow's house. Severance-by-ACL over a shared substrate. Resolve the store/DB severance first; this question then dissolves | found 2026-07-09 (willow seat); see `wo-membrane-checkable` Part B/C |
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

- **B-31 · P1** — **willow-2.0's consent reader fails open.**
  ```python
  DEFAULT_CONSENT = {"internet": True, "cloud_llm": True, "lan": True}
  def _normalize_consent(raw):
      if not isinstance(raw, dict):
          return dict(DEFAULT_CONSENT)   # unparseable consent -> permitted
  ```
  A missing, truncated, or malformed consent block resolves to *everything
  permitted*. This is the same inversion as B-25 (`gate.store_scope` returning
  "unrestricted" for an unreadable policy) and the same class as B-24: an
  unparseable policy is not permission. willow-mcp's own reader
  (`src/willow_mcp/consent.py`) deliberately inverts this — anything it cannot
  read as an explicit `true` is `false` — so this repo is safe regardless. The
  **writer** is still permissive, and it lives in willow-2.0. Out of scope here;
  the two-line fix is `DEFAULT_CONSENT` all-`False` plus returning deny-all from
  `_normalize_consent` on a non-dict.

- **B-32 · P1** — **a host-side agent can self-grant `task_net`.** *Mitigated this
  session; the last step is the operator's.* B-14 made `$WILLOW_HOME/mcp_apps`
  `bound_ro` inside the Kart sandbox precisely so an untrusted runtime could not
  rewrite the ACL that gates it. But the *host-side* agent — the one driving the
  session — holds ordinary file tools and can simply write `"task_net"` into its
  own manifest, then call `task_submit(allow_net=True)`. B-14 closed the sandbox
  door; the host door was never closed. This inverts the **sudo invariant** (FRANK
  `90e52ab7`): *the model may REQUEST egress, never CONFIRM it; request and confirm
  are separate authorities.* Under §0.1 the witness may not be the actor; under
  §0.3 nothing may extend its own reach. Demonstrated in a prior session: the agent
  granted itself `task_net`, pushed a branch, and revoked it. The operator did
  approve each step in chat — but the *mechanism* never required that approval, and
  an approval the machine cannot check is not a control.

  The three structural fixes named when this was filed were (a) put the confirm
  authority outside the agent's write reach; (b) make `task_net` a time-boxed
  lease the agent may request but not mint; (c) require the operator-owned
  `consent.internet`. **(c) landed in B-29. (b) landed here. (a) is now
  *supported and checked*, but it is a `chown`, so it remains the operator's.**

  **What landed (B-32, this session):**
  - **`lease.py` — egress is a time-boxed grant.** `task_net` is demoted to a
    capability: *this app may ever ask*. The grant itself is a record at
    `mcp_apps/_net_leases/<app_id>.json` carrying an issuer, a reason, and a
    deadline capped at **3h** (FRANK `cc553729`: turn / session / ≤3h). A
    self-granted lease **expires** and **leaves an attributed record**, where a
    self-granted boolean persisted silently and forever.
  - **No MCP tool can mint one.** Issuance is `willow-mcp grant-net` — local CLI
    only, exactly as `confirm-binding` is (L-AUTH-02). Plus `revoke-net` and
    `net-status`. A regression test asserts the server exports no such tool.
  - **Read fail-closed**, in the spirit of `consent.py`: absent, unparseable,
    expired, `ttl_seconds` above the ceiling, an `expires_at` with **no timezone**
    (a deadline without a zone is a wish), or a record whose `app_id` names a
    *different* app than the file it sits in — every one denies. *A name is not an
    identity:* the filename is where we looked, not what the record claims.
  - **The sandbox lane is now closed outright.** Leases live under `mcp_apps/`, so
    they inherit B-14's `bound_ro` mount. Verified live: `lease.grant()` from
    inside the Kart sandbox raises `OSError(EROFS)` and no file appears.
  - **The residual is measured, not implied away.**
    `diagnostic_summary.checks.net_lease.self_writable` lists exactly which
    authorizing keys the running process could forge — on a single-uid host, all of
    them. `WILLOW_MCP_STRICT_TRUST_ROOT=1` turns that into a refusal
    (`trust_root_denied`). It is **off by default**: enabling it before uid
    separation exists would deny egress on every install that exists today. That
    default is a statement about deployments, not about policy — and it is *not*
    the B-31 inversion, because the policy is read perfectly well; what is absent
    is the OS enforcing who may have authored it.
  - **The PreToolUse hook blocks the crossing** — `grant-net`, a write under
    `_net_leases/`, or an edit adding `task_net` to a manifest. A hook lives in the
    agent's own harness and is a guardrail, never a control; it makes the boundary
    visible at the moment it would be crossed.

  **A bug found in the fix, by running it rather than testing it.** `_leases_root()`
  called `mkdir()` unconditionally, so the *read* path created the trust root too —
  meaning on exactly the hardened, read-only deployment this work argues for,
  `read_lease()` would raise `OSError(EROFS)` instead of denying. A reader that
  mutates the trust root, and dies when it cannot, has the failure mode backwards.
  Only `grant()` creates now; `self_writable_trust_paths()` asks whether the
  *nearest existing ancestor* is writable, since an absent directory this process
  could create is not hardening. Regression tests pin both.

  **Still not closed.** On a single-uid host the agent can write the lease. It must
  now forge a *third* artifact, with a clock, under audit — but the operating
  system is not stopping it. The genuine fix is ownership:

  ```console
  $ sudo chown -R willow-operator ~/.willow/mcp_apps   # a uid the agent is not
  $ export WILLOW_MCP_STRICT_TRUST_ROOT=1
  ```

  That is a deployment step this repo can support and check but must not perform —
  same class as B-28 and B-30. Until it is taken, requesting egress and confirming
  it are separated by convention, not by the kernel. Full writeup: `SECURITY_AUDIT.md`
  L-NET-02.

- **B-28 · P3** — `completed_at` is never set on **failed** tasks. B-17 added the
  column plus a `set_task_completed_at()` trigger to the shared fleet DB, but the
  trigger's guard is `NEW.status = 'completed'`, so a task that ends `failed`
  keeps a null completion time. Observed live: probe `1T8G5WG5` returned
  `status: failed`, `completed_at: null`. willow-mcp's own `WillowMcpTaskQueue.mark_done`
  is not at fault — it sets `completed_at = now()` for both terminal states; the
  trigger simply never fires for `failed`. The fix is one statement:
  ```sql
  -- widen the guard to any terminal status
  IF NEW.status IN ('completed','failed') AND NEW.completed_at IS NULL
     AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM NEW.status) THEN
  ```
  **Not applied.** It mutates a trigger on the *shared fleet Postgres* (`willow_20`),
  which other fleet members read and write. That is an operator decision, not a
  side effect of a willow-mcp feature branch. Forward-only either way — existing
  failed rows have no recoverable completion time.

## Fixed

- **B-30 · P1 (2026-07-09)** — **the two consent files disagreed, and the first
  diagnosis of *why* was wrong.** On this host:
  ```
  consent.json          internet: false,  lan: false
  settings.global.json  internet: true,   lan: true    <- governs
  ```
  **What this bug was originally recorded as:** a legacy flat file, imported by
  `load_global_settings()` only when the canonical file is absent, therefore inert
  — "a file that looks exactly like the off switch, doing nothing." The suggested
  fix was *reconcile the two, or delete the legacy file.*

  **What it actually is.** `consent.json` is a **mirror**, and a live one:
  ```python
  def save_global_settings(data, *, path=None, sync_legacy: bool = True) -> None:
      ...
      if sync_legacy:
          _write_legacy_consent(out["consent"])     # rewritten on EVERY save
  ```
  Every caller in `global_settings.py` passes `sync_legacy=True`, and Grove's
  settings pane (`panes/settings.py`) mirrors it on every consent toggle. So the
  file is continuously **written** and almost never **read** — read only as the
  canonical file's absent-fallback.

  That asymmetry is the hazard, and it is a sharper one than "inert." A write-only
  mirror **drifts silently**: hand-edit it and nothing reads your edit, nothing
  corrects it, and it sits looking authoritative until some unrelated save quietly
  overwrites it. The disagreement observed here was not a dead file — it was a
  **stale mirror**, produced by a hand-edit that no subsequent save had yet clobbered.
  And the advice to "delete the legacy file" was *wrong*: the next
  `save_global_settings()` or Grove toggle recreates it. A delete that looks like a
  fix and silently comes back is worse than no advice.

  **Resolved** by re-syncing the mirror from the canonical block via willow-2.0's own
  writer (`_write_legacy_consent(read_consent())`) — canonical untouched, effective
  policy unchanged, `diagnostic_summary` back to `ok` with `disagreement: null`.
  Note the one real consequence: `consent.json` is willow-mcp's fallback if
  `settings.global.json` ever goes missing, and that fallback went from `false`
  (deny) to `true` (permit). Consistent with the operator's stated intent, and
  academic anyway given B-31 (willow-2.0's `DEFAULT_CONSENT` is all-`True`), but it
  is a permission-raising side effect of a "cosmetic" repair and is recorded as one.

  **Fixed in code, not just on this host:** `consent.py`'s header and `legacy_path()`
  no longer describe the file as a leftover; `diagnostic_summary`'s `consent` problem
  now says *stale mirror*, warns that deleting it will not keep it gone, and gives
  the re-sync one-liner as the fix. The `error` severity stays — a divergence still
  means one of the two files is lying about the operator's intent, and willow-mcp
  still refuses to guess which.

  **Lesson.** "Legacy" was a word in a docstring, believed without reading the
  writer. The read path was checked; the write path was not. Same class as B-27
  (`pip install willow-mcp[worker]` — an extra that never existed, believed because
  it was written down).

- **B-29 · P0 (this session)** — **operator consent gated nothing.** Egress was
  authorized solely by the `task_net` capability in an app's manifest. The
  operator's standing consent — `consent.internet` in
  `$WILLOW_HOME/settings.global.json` — was read by no gate anywhere. The fleet
  settings file has carried the wiring instruction the whole time, as a flag
  declaring its own absence:
  ```json
  "consent_internet_gates_allow_net": {
    "enabled": false, "implemented": false, "status": "deferred",
    "targets": ["kart_worker", "kart_sandbox", "sap_gate"],
    "note": "Wire settings.global.json consent.internet to kart # allow_net ..."
  }
  ```
  and `flag_enabled()` requires both `enabled` and `implemented`, so it was inert
  by construction. The design was settled long before the code: the egress
  membrane (FRANK `05611965 → 90e52ab7 → cc553729 → 0ba6a33f`, mapped in
  `willow/design/egress-membrane-constitutional-map.md`) names consent a
  time-boxed lease, and the sudo invariant separates *requesting* egress from
  *confirming* it.
  **Fix:** `allow_net=True` is now a **two-key** operation. The manifest's
  `task_net` says *this app may ever request egress* (a capability, granted once).
  The operator's `consent.internet` says *egress is permitted right now* (a
  switch). Both must hold or the call returns `consent_denied` before any write.
  Flipping one boolean stops egress fleet-wide without touching a single manifest
  — which is the whole point.
  **Fail-closed, deliberately diverging from the writer** (see B-31): new
  `src/willow_mcp/consent.py` reads the policy and treats *anything* it cannot
  read as an explicit `true` as denial — absent file, unparseable file, non-bool
  value (`"true"`, `1`, `"yes"`). A corrupt canonical file denies and does **not**
  fall back to the older, laxer legacy file. willow-mcp only ever **reads** this
  policy; a gate that authors the policy it is checked against is not a gate.
  **Disagreement is surfaced, never resolved** (B-30): when both files declare the
  same key with different values, `diagnostic_summary` raises an `error`-severity
  `consent` problem naming both. Keys only one file declares are *not* reported as
  conflicts — a file that omits a key is silent on it, not in disagreement about
  it. That distinction was caught by the end-to-end run, not by a unit test, and
  has a regression test now.
  **A false-green test was found and fixed.** `_app_with_perms` set only
  `WILLOW_MCP_APPS_ROOT`, leaving `WILLOW_HOME` pointed at the developer's real
  `~/.willow`. The existing `task_net` success tests therefore passed by reading
  the *operator's live consent file* (`internet: true`) — and would have failed on
  CI, where no such file exists. The fixture now pins `WILLOW_HOME` to `tmp_path`
  and tests state consent explicitly. Verified by running the whole suite with
  `WILLOW_HOME` pointed at an empty directory (the CI shape) as well as the
  developer shape: **301 passing in both**.
  **Verified end-to-end**, not just by unit test: with an app holding `task_net`
  throughout, flipping `consent.internet` false denied egress; deleting the policy
  denied; corrupting it denied; `"true"` as a string denied; a corrupt canonical
  file beside a permissive legacy file denied; and a genuine conflict on a shared
  key was reported while the canonical value still governed.
  **Residual:** this closes the *egress* key only. `consent.lan` and
  `consent.cloud_llm` are read and reported but gate nothing yet — `# allow_localhost`
  is never self-grantable (B-21) and willow-mcp makes no cloud-LLM calls. The
  lease semantics (turn / session / ≤3h, FRANK `cc553729`) are **not** implemented:
  consent here is a standing boolean, not a leased grant that expires. See B-32
  for why a boolean the agent can also write is a mitigation rather than a fix.

- **B-26 · P2 (this session)** — the task queue had no way to answer "is anything
  going to run this?". `task_submit` returned `{"status": "pending"}` whether a
  worker was one poll away from claiming the row or no worker existed anywhere,
  and `fleet_health` reported only queue depth — a `pending: 40` could mean a
  healthy backlog or a dead fleet. `skills/kart-tasks.md` had to warn about this
  in prose because there was no signal to check. Stage 4 of the Kart lift spec
  (`docs/design/kart-lift-spec.md` §8) called for exactly this and was left open
  when B-22 closed. **Fix:** `kartikeya`'s worker loop already calls an
  `on_heartbeat(lane=…, tick_ok=…)` seam every tick and willow-mcp passed nothing;
  new `heartbeat.py` implements it as an atomic per-process JSON write under
  `$WILLOW_HOME/worker_heartbeat/`, wired into `_cmd_worker` (with `reap()` on
  start and `close()` on exit). `read_workers()` classifies each record `alive` /
  `stale` (process up, loop wedged) / `dead` (pid gone). `fleet_health` gains
  `workers` and a `stranded` boolean (**pending work + zero live workers**);
  `diagnostic_summary` gains a `worker` check and raises a named `worker` problem
  with the `willow-mcp worker` command as its fix.
  **Deliberate:** the problem fires only on `alive == 0 AND pending > 0`. Warning
  on "no worker" alone would make `degraded` the resting verdict for every
  store/knowledge-only install — the same false-positive class B-18 removed.
  **Security posture:** heartbeats are advisory telemetry, never authorization. No
  gate reads them. `$WILLOW_HOME` is `bound_rw` to the Kart sandbox, so a sandboxed
  task *can* forge a heartbeat file; reads therefore verify the recorded pid is a
  live process on the recording host, so a forged file naming a dead pid reads
  `dead`. The trust root remains `mcp_apps/`, which is `bound_ro` (B-14).
  **Verified** end-to-end against a real `kartikeya` worker draining a real
  SqliteTaskQueue: heartbeat `alive` while running → task `completed` → clean
  `close()` removes the file (absent, not stale) → a forged fresh record with a
  dead pid reads `dead`, `alive: 0`, and is reaped. 22 new tests
  (`tests/test_heartbeat.py`, plus `fleet_health` stranded/not-stranded cases in
  `test_server.py`); suite 257 → 279, all passing.

- **B-27 · P3 (this session)** — `pip install willow-mcp[worker]` appeared in three
  places (`task_queue.py`'s module docstring and `_require_kartikeya`'s error,
  `server.py`'s `_cmd_worker` error and the `worker` subcommand help) as the
  remedy for a missing `kartikeya`. **No such extra exists.** `pyproject.toml` has
  no `[project.optional-dependencies]` at all, and B-22's close-out made
  `kartikeya>=0.0.1,<0.1.0` a *hard* dependency precisely so a base install ships a
  drainer. So the one message an operator sees when the worker can't start told
  them to run a command that errors. Residue of the pre-B-22 draft, where the
  extra was the plan. **Fix:** all four sites now say `pip install willow-mcp` (or
  `pip install -e .` from a checkout), and the docstring states the dependency is
  hard, explaining that the lazy import survives only for an uninstalled source
  checkout. Found by checking the docstring against `pyproject.toml` rather than
  trusting it — it read as stale prose and was in fact a broken instruction.

- **B-24 · P0 (this session)** — `store_*` tools had no cross-app isolation.
  Any app granted `store_read`/`store_write`/`store_all`/`full_access` could
  read, write, or delete **every other app's** SOIL store data, not just its
  own — `store_search_all` made this explicit by searching across all
  collections by design. `context_*` solved this correctly (`ctx__<app_id>`
  prefix, `server.py:1047-1048`); `store_*` never got the same treatment.
  First flagged in an external review (`docs/design/mcp-review-2026-07-08.md`
  §2b) as "worth a decision, not asserted as a bug" since it might be
  intentional shared scratch space; re-confirmed on a follow-up pass with no
  README or code comment anywhere stating that's the intent. **Fix:** rather
  than a blanket per-app rename (which would have broken the *documented,
  intentional* fleet-sharing use of `WILLOW_STORE_ROOT` — confirmed live via
  `diagnostic_summary` that collections like `agents`/`hanuman`/`knowledge`/
  `session` are genuinely shared with the wider fleet, not an accident), added
  an **opt-in** `store_scope` manifest field: `db.collection_in_scope()`
  matches exact names or `prefix*` wildcards; `gate.collection_permitted()`
  reads it from the manifest; all six single-collection `store_*` tools check
  it before touching storage; `store_search_all` confines its sweep to the
  scope instead of searching everything. Unscoped apps (no `store_scope` in
  their manifest) are completely unaffected — the shared-fleet-store default
  is preserved, verified by a dedicated regression test. Documented in
  README's Authorization section with a worked example. See `SECURITY_AUDIT.md`
  L-ISO-01 for the full writeup. 24 new tests across `test_gate.py`/
  `test_store.py`/`test_server.py` (252 total, all passing).
  **Residual (not blocking, deliberate):** this closes the *mechanism* gap,
  not the *default* — an app with `full_access` and no `store_scope` still
  sees everything, same as before. Flipping the default to isolate-by-default
  would be a breaking change requiring every existing manifest to be migrated
  and is left as a follow-up decision, not bundled into this fix.

- **B-22 · P1 (this session)** — willow-mcp shipped **no Kart executor**: the
  package advertised a "Kart task queue" and exposed `task_submit`/`task_status`/
  `task_list`/`fleet_health`, but no worker/sandbox/drainer was in the repo, so a
  clean `pip install` left every task `pending` forever (it only ran because an
  out-of-repo, often stale, willow-2.0 Kart was present). **Fixed** by extracting
  the mature willow-2.0 Kart as a standalone, host-agnostic package — **`kartikeya`**
  (github.com/rudi193-cmd/kartikeya, **published to PyPI as 0.0.1**) — with the
  sandbox/worker/execute core decoupled from all fleet imports behind a
  `TaskQueue` backend seam (bundled SQLite reference impl + Postgres). willow-mcp
  now: depends on `kartikeya` (hard dep, `>=0.0.1,<0.1.0`); ships
  `WillowMcpTaskQueue` (Postgres over the adopted `tasks` table, atomic
  `FOR UPDATE SKIP LOCKED`; SQLite fallback when no PG); the `willow-mcp worker`
  subcommand; and `docs/schema/tasks.postgres.sql`. A clean
  `pip install willow-mcp` now ships a working queue drainer. Verified: clean-venv
  `pip install kartikeya` imports + `kart` CLI resolves; kartikeya standalone e2e
  green (submit → worker → completed); willow-mcp integration tests run
  unconditionally. Plan: `docs/design/kart-lift-spec.md`; extraction PRs on the
  kartikeya repo; willow-mcp PRs #35 (integration) + #36 (hard dep / close-out).
  **Residual (not blocking):** the full real-bwrap end-to-end with network egress
  on/off must be validated on a bare host — the dev Kart sandbox can't nest
  bubblewrap, so its tests run with `WILLOW_KART_NO_BWRAP=1`.

- **B-23 · P3 (this session)** — the task-queue tool surface shipped without
  its companion skill/hook, breaking the standing rule that a footgun/workflow
  tool ships its skill+hook in the *same* PR (`docs/design/hooks-and-skills.md`
  §2). `task_submit` + the `task_net` capability (B-19) and the `# allow_net`
  directive footgun (B-21) are exactly that case and had neither. **Fix:** added
  `skills/kart-tasks.md` (submit/poll workflow, the `allow_net`/`task_net`
  permission model, and the worker-liveness caveat that a submission ≠ an
  execution) and extended `hooks/pre_tool_use.py` with a `task_submit` matcher
  that *warns* when a caller hand-embeds a `# allow_net`/`# allow_localhost` line
  (a no-op post-B-21) and points them at the real path. Registered both in
  `.claude-plugin/plugin.json`. Operator-caught, not review-caught.
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
- **B-34 · orchestrator human gate** — filed P0 as "the gate does not exist"; the gate exists and
  works. `human_session.py:41` reads `WILLOW_HUMAN_ORCHESTRATOR`; `server.py:201-202` calls
  `orchestrator_write_denial()` and returns it for `dispatch_send` / `verify_handoff` /
  `agent_clear`; the denial text `orchestrator_human_required` lives at `human_session.py:60`.
  Confirmed empirically: it refused a live `dispatch_send` from the willow seat at
  2026-07-09T12:26Z (FRANK `66bfd8b3`), which the withdrawn entry had claimed "rests on a misread."
  The false alarm came from probing with `diagnostic_summary()` and no `app_id`, so
  `is_orchestrator_app(None)` returned `False` and the check never ran — **the gate was tested by
  not being the identity the gate guards.** `gate.permitted()` reading only `permissions` is true
  and irrelevant: the ACL and the host attestation are separate layers. Withdrawn by root
  2026-07-09 before any patch reached the code. FRANK `c4f7bec5` (adjudication), `e4759e8b`
  (authorization).

  *Kept, not deleted.* A false negative about a live membrane is more dangerous than a false
  positive about a dead one: both of B-34's proposed remedies — "wire the key into `_gate`" or
  "delete the field and the doc claim" — would have edited a boundary that already held. The
  lesson is the probe, not the gate.
