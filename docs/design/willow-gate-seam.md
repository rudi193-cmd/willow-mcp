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
2. **Identity binding (read-only)** — `register_agent` + `check_in` HMAC-verify
   feeding `_gate`, *observed only* (log bound tier, don't enforce yet).
3. **Tier ceiling enforced** — `authorize_tool` in `_gate` applies §2 once D1 is
   ratified.
4. **Session reconciliation** — `check_out` declare-vs-did on top of
   `session_handoff_write` (needs D4).
5. **Announcement/ledger policy** — graduated loudness + optional encrypted
   channel over `ReceiptLog`.
