---
kind: doc
name: egress-request-seam
description: "Where an agent that needs egress should ASK for it instead of failing — the three denial sites, why a PreToolUse hook is the weakest of three options, and why SEP-2322 made the right one possible on 2026-07-29."
---

@markdownai v1.0

# The egress request seam

## The gap

An agent that needs network reaches a denial and stops. The three-key gate is
correct — capability, standing consent, time-boxed lease, plus a signed
per-task envelope — and no MCP tool may mint any of them. That is the whole
point: *an agent may REQUEST egress, never CONFIRM it.*

But the REQUEST half was never built. The agent gets an error dict, and the
request is whatever the agent then says to the operator in prose. Observed live
this session: a lease expired 2026-07-21, an agent needed `gh pr create`, and
the entire request mechanism was the agent pasting a shell command into chat and
hoping. Nothing was queued. Nothing was recorded. Nothing resumed.

**The denial is not the problem. The absence of a request path is.**

## The three sites

One shape, three call sites — which is the argument for a single seam rather
than three hooks:

| Site | Denial |
|---|---|
| `server.task_submit` — Key 3 | `lease_denied` when `lease.read_lease(app_id)["status"] != "active"` |
| `web_egress.egress_denial` | `lease_denied` on the same read, for `willow_web_*` |
| `integrations.egress_denial` | mirror of the above, for `integration_call` |

`model_egress.denial` (added 2026-07-28) is a fourth of the same family but
denies on `consent.cloud_llm`, which is a standing switch rather than a lease —
an operator edit, not a grant. Worth including for consistency; less urgent.

## Three ways to build it, weakest first

### 1. A PreToolUse hook — what this looks like it wants, and the weakest option

`bundle/hooks/pre_tool_use.py` already blocks self-grant attempts, so the
machinery is familiar. A hook could intercept a network-bearing `task_submit`
and emit "ask the operator for a lease."

**Why it is weakest:** a hook can block and it can print. It cannot carry state.
The agent is told to ask, asks in prose, and the resumption is still a human
re-reading a transcript and a fresh tool call with no link to the original. It
automates the *message*, not the *request*. And it sits outside the gate it
speaks for — the hook runs in the agent's harness, where `willow_mcp` may not
even import, which is exactly why its permission list drifted behind
`gate.PERMISSION_GROUPS` for so long.

### 2. Auto-enqueue to `human_required` — durable, still not blocking

On `lease_denied`, call `human_loop.enqueue` with `kind="consent"` and a payload
naming app_id, the exact task text, the scope (`allow_net` vs
`allow_localhost`), and the requesting session. The operator sees a real queue
item; `human_required_resolve` records who granted and when.

**What it buys:** the request becomes a record instead of a sentence. States,
not deletions. It is auditable and it survives the session.

**What it does not buy:** the agent still does not pause. `human_required_enqueue`
writes a row and returns — the module docstring says the discipline is
*"automation pauses for a human"* and nothing pauses. The agent gets a queue id
and carries on, which is a bulletin board, not a gate.

### 3. `InputRequiredResult` — the one that actually pauses, newly possible

**SEP-2322**, in the 2026-07-28 revision: a server returns
`InputRequiredResult` carrying `inputRequests`, and the client **retries the
call echoing `requestState`**. That is a native pause-and-resume — the first
protocol-level way to suspend a tool call until a person acts.

`task_submit` returns `InputRequiredResult` on `lease_denied`.
`human_required_resolve` — or `grant-net` itself — satisfies it. The agent's
original call resumes with the lease in place. No prose, no re-derivation, no
operator reading a transcript to reconstruct what was being asked.

**This became available today.** willow-mcp went to SDK 2.0 on 2026-07-29
(#202, #204). Before that there was no way to hold a call open, which is
plausibly why this has resisted fixing for so long — the missing piece was in
the protocol, not the codebase.

## Recommended shape

Build **2 and 3 together**, in one place, at the denial:

1. A single `egress_request` module both `egress_denial` funnels and
   `task_submit` call when a lease is the missing key.
2. It enqueues the durable `human_required` record — so the ask outlives the
   session and is auditable — **and** returns `InputRequiredResult` so the
   caller blocks.
3. `grant-net` resolves both: the queue item closes, the `requestState`
   satisfies, the original call resumes.

Skip the PreToolUse hook. A guardrail that can only speak is the wrong tool for
a request that needs to be recorded and resumed.

## What must not change

- **No MCP tool mints a lease.** The request path must not become a grant path.
  `grant-net` stays CLI-only and operator-terminal-gated.
- **The denial stays fail-closed.** If enqueue fails, the call is still denied —
  a request mechanism that swallows its own failure and proceeds is worse than
  none.
- **The signed envelope is unaffected.** A lease is necessary, never sufficient;
  `sign-net-task` remains a separate operator act.
- **`require_operator_terminal` keeps both arms.** The sandbox check before the
  tty check is what makes the seat non-forgeable.

## Decided (operator, 2026-07-29)

- **The request names the exact task**, not the app. It matches the envelope's
  granularity — a lease is per-app but the signed authority is per-task, so an
  ask that names the app would be broader than the grant it leads to.
- **TTL: 3 hours maximum**, matching `lease.max_ttl_seconds`. An unanswered
  egress ask expires rather than sitting open forever. An expired request is a
  denial, never a grant.
- **Every egress point is included**, `model_egress` among them. Its missing key
  is a standing switch rather than a lease, so the *resolution* differs — an ask
  to flip `consent.cloud_llm` is not an ask for a time-boxed grant — but the
  agent's side is identical, and a request path with a hole in it teaches
  operators that some denials are askable and others are dead ends.

## Why this is a blocker, not an ergonomic

**An operator who is not comfortable at a CLI currently cannot grant egress at
all.** `grant-net` is terminal-only and `require_operator_terminal` enforces it
with a tty-ownership check. For that operator the three-key gate is not a gate,
it is a wall: the agent can ask, and there is no surface on which they can
answer.

That reframes the priority. This is not about saving the operator a paste — it is
the difference between a fleet a non-CLI operator can run and one they cannot.

It also creates the one real tension in this design, so name it rather than
discover it later:

> *No MCP tool may mint a lease* and *the operator must be able to answer without
> a terminal* both have to hold.

They are compatible, because the constraint is on **who confirms**, not on **what
they type**. The resolution already half exists — `willow-mcp gates --serve`
binds a local dashboard on 127.0.0.1 with working buttons. A grant confirmed
there is an operator act at an operator-owned surface; it is not an MCP tool
minting anything, and no agent can reach it.

So the approval surface should be:

1. **`gates --serve`** — the button path, for the operator who does not want a
   terminal. Localhost-bound, no agent reachability.
2. **Grove's human-required pane** — where the queued request already belongs,
   once Grove is repointed at willow-mcp's queue (see the fleet notes on that
   repointing; Grove currently reads willow-2.0's Postgres table).
3. **`grant-net`** — unchanged, for the operator who prefers the CLI.

`require_operator_terminal` guards the CLI arm. The dashboard arm needs its own
equivalent — a localhost bind plus the same not-in-Kart check is the shape, and
whatever it is must be written down beside this, because an approval surface with
a weaker check than the one it replaces is how the whole gate gets undone.

*ΔΣ=42*
