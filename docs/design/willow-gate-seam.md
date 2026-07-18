# willow-gate ↔ willow-mcp: the seam

Status: **proposal / mapping only** (no code yet). This pins how
[`willow-gate`](https://github.com/rudi193-cmd/willow-gate) composes with
willow-mcp's existing authorization stack *before* any of the invasive wiring is
written, so we can prototype one slice at a time without guessing the shape.

## The gap it fills

willow-mcp's entire ACL — `gate.permitted(app_id, tool)`, the sudo invariant,
`store_scope` confinement — trusts that the **`app_id` argument is honest**. In
stdio/agent mode it is just a string passed on every tool call. There is already
an identity binder for *humans* — `identity_binding.py` maps a verified OAuth
`(issuer, subject)` to an `app_id` in serve mode, confirmed only via the local
`willow-mcp confirm-binding` CLI — but **agents don't OAuth**, so the agent path
has no binding at all.

willow-gate is the missing **agent-side** binder: an HMAC over a 13-field header,
keyed by a per-agent secret the gate holds, with the claimed `trust_level` capped
at a registered ceiling. *"Elder is not a text field anyone can type."* It does
not replace `identity_binding.py`; it sits beside it, and both feed the same
resolution point.

## The two systems at a glance

| Concern | willow-mcp today | willow-gate | Seam |
|---|---|---|---|
| Human identity | OAuth → `identity_binding.resolve_app_id` (serve mode), CLI-confirmed | — | keep |
| Agent identity | `app_id` string, **unbound** | HMAC-signed header, secret held by gate, trust capped at registered ceiling | **new binder** |
| Authorization | `PERMISSION_GROUPS` per manifest (fine-grained tool sets), fail-closed, `deny_tools` | trust ladder 0–4 → coarse classes {read, write, query, execute, admin} + export gate | **tier as ceiling over groups** |
| Enforcement | `_guarded` → `_gate` → `permitted` → receipt; PreToolUse tripwire | `authorize_tool(session, tool, export=)` (hook) / `bind_tools` (in-proc) | `authorize_tool` **inside `_gate`** |
| Session | `session_enter` / `session_handoff_write` | `check_in` / `check_out` with 13-field declare-vs-did diff | check_in ↔ session_enter |
| Audit | `ReceiptLog` | PGP-encrypted ledger + graduated announcement volume | receipts carry tier/announce policy |
| Relationship drift | *(nothing)* | `friction_floor` — model-free sycophancy smoke detector | **orthogonal**, separate wiring |

## Layer-by-layer seam

### 1. Identity — two binders, one resolution point
- **Humans / serve mode:** unchanged — `identity_binding` maps OAuth `(issuer,
  subject) → app_id`, CLI-confirmed.
- **Agents / stdio+dispatch:** willow-gate `register_agent(agent_id, secret,
  max_trust)` (operator-side, like `confirm-binding` is CLI-only) provisions a
  per-agent secret + trust ceiling. `check_in(header)` HMAC-verifies the caller
  and yields a bound session carrying `agent_id` + verified `trust_level`.
- `_gate` becomes the single resolver: it accepts **either** a confirmed OAuth
  binding **or** a valid willow-gate session, and produces `(bound_app_id,
  trust_level)`. An authenticated-but-unbound / signature-invalid caller is
  denied — same fail-closed rule `identity_binding` already uses.
- **Opt-in per deployment.** HMAC binding must not be forced on a local
  single-operator box (no ceremony wanted there). Rule: if an `app_id` is
  *registered with a secret*, its calls **must** be signed; unregistered local
  app_ids fall back to today's manifest-only, trusted-host behavior. Same shape
  as `WILLOW_VAULT_RESTORE` being opt-in.

### 2. Trust tier vs permission groups — tier is a *ceiling*, not a replacement
willow-gate's `allowed_tools` are **coarse classes** (`read, write, query,
execute, admin`); willow-mcp's `PERMISSION_GROUPS` are **fine-grained**
(`store_read`, `knowledge_write`, `task_queue`, `full_access`, …). Do **not**
collapse one into the other. Compose them:

```
effective_tools = expand(manifest.permissions)     # what this app may hold
                  ∩ tier_ceiling(trust_level)       # what this tier may hold
gated further by:
  - read_only / write_export_allowed  → write & export tools
  - announcement_volume + audit_level → receipt loudness (§5)
```

A first-cut class→group map (to be refined):

| willow-gate class | willow-mcp groups it unlocks |
|---|---|
| read | `store_read`, `knowledge_read`, `gap_read`, `dispatch_read`, `fleet_read`, `audit`, `lineage_read` |
| write | `store_write`, `knowledge_write`, `gap_write`, `context`, `lineage_write` |
| query | search-heavy reads (`store_search_all`, …) |
| execute | `task_queue`, and — export-gated — `integration_call` / `task_net` |
| admin | `schema_admin`, `gap_purge`, manifest/registry ops |

Note the natural alignment: willow-gate's **export gate** ↔ willow-mcp's
egress lines (`integration_call` / `task_net`) that are *deliberately excluded
from `full_access`* and granted on their own line. Export tools stay export-only
at every tier below `write_export_allowed`.

### 3. Enforcement seam — `authorize_tool` inside `_gate`
`_gate` is already the "authorize before dispatch, then receipt" point.
willow-gate's `authorize_tool(session, tool, export=)` slots **inside** it: after
`permitted()` says the manifest allows the tool, `authorize_tool` applies the
tier ceiling, export gate, drift/fail budgets, and announcement. The PreToolUse
hook remains the *external* mirror of the same check (defense-in-depth).
`bind_tools`/`GatedSession` is **N/A for the MCP surface** — MCP tools are
framework-dispatched, not a passed callable list — so the funnel is
`authorize_tool`-in-`_gate`, never `bind_tools`.

### 4. Session lifecycle — reconciliation on top of session_enter/handoff
- `check_in` ↔ `session_enter`: `session_enter` performs the willow-gate check-in
  (HMAC-verify, establish the bound tiered session subsequent `_gate` calls
  consult). Its existing `entry_mode`/assignment return is unchanged.
- `check_out` (13-field **declare-vs-did diff**) ↔ `session_handoff_write`: what
  the agent declared on entry (`tools`, `pass_count`, `fail_count`, `drift`,
  `state_hash`) is reconciled against what it actually did — and because only
  authorized calls are recorded, that reconciliation is true for free.
- Defining willow-mcp's 13-field entry/exit declaration is its own schema task;
  can be a later phase.

### 5. Audit — receipts gain tier + announcement policy
Keep `ReceiptLog` as the record of every gated call; layer willow-gate's
**graduated announcement volume** (louder for the *less* trusted) and
`audit_level` (`full` vs `minimal`) as a policy over it, and optionally its
PGP-encrypted ledger for the announcement channel. Receipts already log every
`_gate` decision — this adds *how loudly*, not a second log.

### 6. friction_floor — orthogonal, not part of the gate seam
`friction_floor` watches the agent→**user relationship** (sycophantic mirroring
during a user escalation), not access. It runs *outside* the model it watches,
flags loud for a human, never blocks. It wires to session **transcripts**, not
`_gate` — a separate monitor. In scope for "bring in willow-gate," out of scope
for the authorization seam. (Cleanest standalone slice to prototype first if we
want a quick, low-risk win.)

## Invariants that must survive the merge
1. **Sudo invariant.** `admin`/Elder trust is *not* sudo. Authority (minting
   manifests, secrets, trust ceilings) stays CLI/operator-side —
   `register_agent` is operator-only, matching `confirm-binding`. No MCP tool
   may raise its own tier or write its own secret.
2. **Fail-closed everywhere.** Invalid signature, unknown agent, unbound caller,
   tier-below-tool → deny, same as an unmanifested `app_id` today.
3. **Agent-neutral base stays usable locally.** Binding is opt-in; a plain local
   clone keeps working with manifest-only auth and no HMAC ceremony.
4. **Secrets are never MCP-writable.** Per-agent secrets live beside manifests
   under `$WILLOW_HOME/mcp_apps/…`, on the PreToolUse guard's owned-marker side —
   provisioned by the operator, never reachable from a tool.
5. **The two ledgers stay distinct.** willow-gate's ledger is a *custody* story
   (who did what, at what trust); `lineage` is a *decision* story (why things
   are). Complementary, not merged.

## Holes found (spike)

A runnable spike composed the *intended* bridge above and attacked it. willow-gate's
crypto core held through the bridge — trust-ceiling cap, forged signature, nonce
replay, and the `reserved` trap were all rejected — and the intended composition
closed the obvious over-grants (a read-only-manifest agent could **not** write by
passing `app_id=operator`; egress needed *both* manifest and tier). Two "holes"
the spike shows are really *build-it-right constraints*: a bridge that trusts the
`app_id` argument, or leans on the tier without the manifest ∩, over-grants — the
intended bridge already denies both. Three genuine holes remain for the full
build, plus one policy call and one upstream bug:

- **H1 — session↔app_id binding is the whole ballgame (BLOCKER).** Every
  willow-mcp tool takes `app_id` as a plaintext string. The HMAC binds a
  *session*, but nothing ties a given MCP call to that session — a caller passing
  `app_id=operator` rides operator's live session with no auth of its own. **The
  full build must carry a per-call credential on every gated call; `app_id` alone
  cannot bind.** Largest change; touches every tool signature. *Prototyped — see
  "H1 prototype" below: a per-call HMAC signature (SIGNED) is the fix; a bearer
  session token closes the ride but not replay.*
- **H2 — willow-gate must BE `_gate`, not sit beside it.** `_gate` today
  authorizes via `permitted()` alone. Unless `authorize_tool` runs *inside*
  `_gate` as the sole funnel, willow-gate is a ledger, not a gate: a call that
  reaches a tool any other way is neither prevented nor recorded. *Prototyped —
  the funnel already exists (see "H2/H3 prototype"): `@_guarded` is the sole
  wrapper on every tool, `_gate` already returns an `effective_app_id` distinct
  from the raw arg, so H2 is inserting willow-gate's authorize at that existing
  point, not building a funnel.*
- **H3 — reconciliation needs a real `tools_used` feed.** `check_out`'s
  declare-vs-did diff only sees tools that passed through `authorize_tool`. It
  must be fed from `ReceiptLog`, or reconciliation silently passes on out-of-band
  use. *Prototyped — `ReceiptLog` already records every `ok`/`denied` decision at
  the funnel; sourcing `tools_used` from `ReceiptLog.tail` reconciles correctly
  AND flags an exit that claims a tool no receipt ever authorized.*
- **Policy — read-universal does NOT survive the seam.** willow-gate grants read
  to everyone (even Exiled); willow-mcp fail-closes an unmanifested/unscoped
  `app_id`, and in the bridge that WINS. Bringing in willow-gate does **not** make
  willow-mcp reads universal — `store_scope` still confines. State it; don't
  inherit it by accident.
- **Upstream bug — `entry_allowed` unenforced in willow-gate.** Level 0 (Exiled)
  is defined `entry_allowed=False`, but `check_in` never checks it, so an Exiled
  agent still gets a (read-only) session. Fix upstream in willow-gate.

## H1 prototype — how a call binds to a session (resolved)

A second spike prototyped the missing binder — what each call carries *besides*
`app_id` — across three modes, attacking each with ride / replay / tamper:

| mode | what the call carries | ride | replay | tamper |
|---|---|---|---|---|
| APPID_ONLY (today) | `app_id` only | **HOLE** | — | — |
| BEARER | + a session token minted at check-in | closed | **HOLE** (token reusable for any later call) | HOLE |
| SIGNED | + `(session_id, call_nonce, HMAC(secret, session_id\|app_id\|tool\|call_nonce))` | closed | closed (nonce single-use) | closed (sig binds app_id+tool) |

**Decision: SIGNED per-call HMAC.** It is the only mode that closes all three —
it extends check-in's exact HMAC model to every call. Bearer stops the ride (a
real gain over today) but a captured token replays for any call for the session's
lifetime, so it is acceptable *only* where the transport itself is the trust
boundary.

Practical shape:
- **The MCP client signs, not the LLM.** The harness wrapping the agent holds the
  per-agent secret and signs each call; the model never sees the secret and
  cannot fabricate or omit a signature. This is client-side signing middleware —
  a real integration cost, and the point: an un-instrumented client cannot call
  gated tools.
- **The credential rides out-of-band** (a transport/metadata field on the MCP
  request), *not* as a tool parameter — tool schemas stay clean and the model
  can't touch it. `_gate` reads it from the request context.
- `_gate` becomes: read `(session_id, call_nonce, sig)` → resolve to `(agent_id,
  trust)` → **require `agent_id == app_id`** → then today's `permitted()` + tier.
- **Mode by deployment:** SIGNED is required for serve-mode / multi-agent. For a
  single-agent stdio deployment where the private pipe already authenticates the
  peer, BEARER (or a session handle) is an acceptable lighter choice.

Residual limits to carry into the build: per-agent secret provisioning (D2); a
per-session used-nonce set that is dropped at check-out (bounded growth); and the
hard truth that any client not instrumented to sign simply cannot reach a gated
tool.

## H2/H3 prototype — the funnel already exists (resolved)

Reading `_guarded`/`_gate` changed H2/H3 from "build" to "insert":

- `@_guarded` wraps **every** `@mcp.tool` — the sole funnel is already structural;
  the raw tool body has no un-gated handle.
- `_gate` already returns an `effective_app_id` distinct from the caller-supplied
  `app_id` (built for serve-mode OAuth binding) — the exact point the H1 SIGNED
  binder + `authorize_tool` slot into.
- `_guarded` already receipts every decision (`ok` / `denied` / `rate_limited` /
  `error`) via `ReceiptLog`.

A prototype composed `_gate_v2 = SIGNED binder → authorize_tool → permitted()`
behind a `@guarded` wrapper over the **real** `ReceiptLog`, and showed:
- an authorized call runs its body; a denied call's body **never** runs;
- `check_out` reconciliation sourced from `ReceiptLog.tail` matches what actually
  ran, and **flags** an exit that declares a tool no receipt authorized
  (out-of-band claim caught).

So H2 = swap the `app_id`-verbatim step in `_gate` for `_gate_v2`; H3 = compute
`tools_used` from `ReceiptLog` at `check_out`. Neither needs new plumbing.

## Open decisions (the forks to settle before wiring)
- **D1 — tier↔group map:** ratify the class→group table in §2, especially where
  `execute`/`admin` land relative to `task_queue`, `integration_call`,
  `schema_admin`, `gap_purge`.
- **D2 — secret store & rotation:** exact on-disk layout and rotation story for
  per-agent secrets; how `register_agent` is exposed on the CLI.
- **D3 — stdio default:** confirm "unregistered ⇒ manifest-only, registered ⇒
  must-sign" is the right opt-in trigger (vs. an explicit env flag).
- **D4 — 13-field declaration schema:** what willow-mcp agents declare at
  `session_enter` so `check_out` reconciliation has something to diff.
- **D5 — vendoring:** willow-gate as a pip dependency (`python-gnupg` pulls in)
  vs. vendored subset; whether the base takes on the PGP dep at all or gates it
  behind `require_pgp=False`-style dev mode.

## A phased path (each phase is independently shippable)
1. **friction_floor watcher** — orthogonal, no auth-path risk; net-new signal.
   Unblocked by every hole below — the safe first slice.
2. **Session credential + identity binding (read-only)** — add the per-call
   session token (**H1**), `register_agent` + `check_in` HMAC-verify feeding
   `_gate`, *observed only* (log the bound tier, don't enforce). Nothing after
   this works without H1, so it leads.
3. **Tier ceiling enforced** — `authorize_tool` *inside* `_gate` as the sole
   funnel (**H2**), applying §2 once D1 is ratified.
4. **Session reconciliation** — `check_out` declare-vs-did on top of
   `session_handoff_write`, with `tools_used` fed from `ReceiptLog` (**H3**);
   needs D4.
5. **Announcement/ledger policy** — graduated loudness + optional encrypted
   channel over `ReceiptLog`.

Before any of this, upstream a fix (or a tracked issue) for willow-gate's
unenforced `entry_allowed`, and write the read-universal policy call into the
gate's docs so the seam's read semantics are chosen, not inherited.
