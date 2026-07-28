---
kind: doc
name: stateless-session-state
description: "What MCP 2026-07-28's removal of protocol-level sessions actually costs willow-mcp: the inventory of load-bearing in-process state, which pieces must become durable, which may stay per-process, and why the first move is a declared single-instance guard plus a process-safe receipt chain rather than a durable session store."
---

@markdownai v1.0

# Stateless MCP vs. willow-mcp's in-process state

Status: **design + first slice landed.** The reproduction, the inventory and the
argument are here; two of the changes described are implemented on this branch
(`instance_lock.py`, the `receipts.py` chain fix). The rest is sequenced, not
built.

Companion to `docs/design/mcp-2026-07-28-diff.md` (currently on
`experiment/github-transport`, not yet on master), which reads SEP-2567 as
unqualified good news for that branch. For the transport it is. For the server it
is a bill coming due, and this doc is the bill.

## The claim, and what is actually true

SEP-2567 removes `Mcp-Session-Id` and protocol-level sessions: *"any server
instance can handle any stateless request."* That is a statement about the
**protocol**. It is not a statement about **us**. What the session ID was
actually buying willow-mcp was not protocol semantics — it was a **routing
affinity side effect**: a load balancer that pins on `Mcp-Session-Id` happens to
send an agent's calls back to the process that holds its state. Nobody designed
that dependency. It was free, so it was never written down, and now the thing
that was quietly providing it is being removed.

The exposure is therefore not "the spec broke us." It is "the spec is about to
remove the accident that was hiding an assumption we never declared." That
distinction matters for the fix: the answer is not necessarily to make the state
shared. It may be to declare the assumption.

## What reproduces

`tests/test_multi_instance_state.py` is the evidence. Two findings, and the
second is the one that changes the plan.

### 1. The agent-binding lockout — real, and worse in the shipped harness

Two `SessionBinder` objects over one `$WILLOW_HOME`, with
`WILLOW_MCP_ENFORCE_BINDING=1`:

1. `session_bind` lands on **A**. The check-in nonce is burned in the **shared**
   file (`$WILLOW_HOME/gate/used_checkin_nonces`); the session is created in
   **A's memory only**.
2. The next tool call lands on **B**. `verify_call` returns
   `{"bound": False, "reason": "no live session for session_id"}`, and
   `server._enforce_binding_gate` turns that into a hard `binding rejected`
   denial — not a downgrade.
3. The obvious retry — re-send the identical signed request — hits the shared
   nonce file on **B** and is refused: `nonce already used — replay refused`.

Half the state shared and half not is what turns a cache miss into a refusal.

**One correction to the folk description of this bug.** The agent is *not*
cryptographically stuck. The check-in nonce is agent-chosen and covered by the
agent's own signature, so it can always mint a **fresh** header and bind on B.
Step 3 only bites the naive retry. The lockout is real anyway, for two reasons
that are worth stating precisely rather than overstating:

* **The shipped harness has no re-bind path.** `signing.SigningClientSession`
  binds once in `bind()` and stores the `session_id`; `call()` then fails
  forever with no recovery. Re-binding is a thing an operator could write, not a
  thing the product does.
* **Even with re-binding it does not settle.** Every call is independently
  routed, so it is a per-call coin flip, not a bootstrap hiccup. With *N*
  replicas a bound call succeeds with probability *1/N*.

And there is a quieter half that no retry fixes: `entry_declared` and the
server-stamped `started_ts` die with the process. `session_reconcile` on any
other instance returns `no_live_session`, so the **H3 declare-vs-did audit
silently stops happening**. An integrity control that stops running is worse
than one that visibly fails.

### 2. The receipt hash-chain forks — silent, permanent, and reachable *today*

This is not in the diff doc's list and it is not on the "four pieces" list, and
it is the most serious thing here.

`ReceiptLog.record` read the chain head and appended in two steps:

```
SELECT entry_hash FROM receipts ORDER BY id DESC LIMIT 1   # head
INSERT INTO receipts (..., prev_hash, entry_hash) VALUES (...)
```

guarded by a `threading.Lock`. A `threading.Lock` says nothing to another
process, and sqlite3's implicit transaction begins DEFERRED at the first
*write*, so the SELECT sat outside the write lock. Two writers both read the
same head and both append a row claiming it as `prev_hash`. `verify()` then
returns `{"ok": False, "reason": "prev_hash linkage"}` — **forever**, because the
log is append-only and there is nothing to repair it with. And
`server.session_reconcile` calls `verify()` before trusting the log, so from that
moment every session reconciliation returns `receipt_integrity_failed`.

Reproduced 3/3 across two real OS processes, 20 receipts each:

```
two concurrent PROCESSES, 20 receipts each: {'ok': False, 'broken_at': 21, 'reason': 'prev_hash linkage'}
```

**This needs no multi-replica deploy.** A desktop client and a terminal each
spawn their own willow-mcp stdio process over the same `~/.willow` today. The
2026-07-28 spec did not create this; it only guaranteed we would meet it.

## The inventory

Everything load-bearing that is not already durable-and-safe. "Blast radius" is
what happens on the request that lands on the wrong process.

| State | Where | Today | Blast radius on a miss | Verdict |
|---|---|---|---|---|
| `SessionBinder._sessions` | `session_binder.py:125` | process memory | agent denied every gated call; reconciliation never runs | **must become durable** — but not first (below) |
| check-in nonces | `session_binder.py:126` | **shared file** | — (this half already works) | keep; it is the pattern to copy |
| receipt hash chain | `receipts.py` | shared SQLite, **unsafe read-modify-write** | audit chain forks unrepairably; all reconciliation fails permanently | **fixed on this branch** |
| `GroveOAuthProvider._pending` | `oauth.py:67` | process memory | *"Authorization failed — invalid state."* — human cannot log in | must become durable *if* serve mode ever goes multi-replica |
| `_codes` / `_code_identity` | `oauth.py:68-74` | process memory | token exchange fails; worse, `_code_identity` carries the **verified IdP identity** — losing it must never silently issue an unattributed token | same, and higher care |
| `server._buckets` | `server.py:725` | process memory | rate limit becomes *N×* the configured rate — fails **open**, quietly | may stay per-process, with the limit divided or declared |
| `web_search._BREAKERS`, query cache | `web_search.py:496` + query-cache section | process memory | duplicate upstream calls, slower breaker trip | may stay per-process — degradation only |
| `soil_heartbeat._last_mono` | `soil_heartbeat.py:29` | process memory | duplicate heartbeats | may stay per-process |

Two things fall out of reading that table together.

**The OAuth flow is worse than one miss.** After `authorize()` sets `_pending`,
*three* further requests — `/mcp-approve`, `/oauth/google/start`,
`/oauth/google/callback` — each read or pop that same in-memory key, and each is
independently routed. A login survives *N* replicas with probability *1/N³*.

**The rate limiter is the only one that fails open.** Everything else fails
closed and is loud. `_buckets` silently multiplies the limit by the replica
count. That makes it low-severity to *leave* and dangerous to *forget*, which is
an argument for declaring it, not for building a Redis backend.

## The decision: declare single-instance — and mean it in only one place

**Yes.** willow-mcp should declare itself single-instance rather than start a
migration, and this branch implements that declaration. The reasoning is not
"multi-replica is hard"; it is that **a partial migration is worse than none.**

Making `SessionBinder._sessions` durable is the tempting first move — the nonce
file proves the pattern, and it is the piece that turns a degradation into a
lockout. That is exactly why it is the *wrong* first move. The binding lockout is
**loud, immediate, and recoverable**: the operator finds out in seconds and
nothing is destroyed. The receipt fork is **silent, permanent, and destroys the
tamper-evidence the whole trust architecture rests on**. Fixing sessions first
removes the alarm that stops anyone from running two replicas long enough to
break the audit chain. It buys a system that *looks* multi-replica-safe and is
not — and it does not even finish the job, because the OAuth flow, the rate
limiter, the `Store` and the `Vault` would all still be unmigrated.

So the declaration has to be honest about its own scope:

> **willow-mcp serve mode is single-instance per `$WILLOW_HOME`. Multiple stdio
> processes over one `$WILLOW_HOME` are normal and supported.**

That second sentence is the part that is easy to get wrong. A blanket "one
process per home" lock would break the ordinary desktop-client-plus-terminal
case in order to guard a deployment shape stdio cannot even be in. Multiple
stdio processes are separate *agents*, not replicas of one server, and the right
response to them is to make the shared on-disk state process-safe — which is
what the receipt fix begins.

### Where the declaration lives, and what enforces it

* **Written:** `src/willow_mcp/instance_lock.py` — the module docstring *is* the
  declaration, next to the code that enforces it, naming each piece of state and
  how it fails. An assumption that lives only in a design doc is how this one got
  lost the first time.
* **Enforced:** `flock(LOCK_EX | LOCK_NB)` on `$WILLOW_HOME/serve.lock`, taken in
  `server._main()` on the serve branch only. A second serve process on the same
  home exits 1 with the reason, not a traceback.
* **Why `flock` and not a PID file:** the kernel releases it when the holder dies
  — SIGKILL, OOM, power loss, container eviction included. No stale lock to reap,
  no "is PID 4211 still the server or is it now someone's editor" guess.
* **Escape hatch:** `WILLOW_MCP_UNSAFE_MULTI_INSTANCE=1`, which downgrades the
  refusal to a warning that names the breakages. It is named "unsafe" because it
  does not make a second instance work; it only stops the guard saying no. It
  exists so the guard is not deleted in a panic at 03:00, which is the failure
  mode of a hard block with no override.
* **What it deliberately does not catch:** two serve processes on two *different*
  homes (correct — two installs), and CLI invocations (they never take the lock,
  so `willow-mcp register-agent` still works against a running server).

## Migration order, if the declaration is ever lifted

Ordered by *severity of silent failure*, not by ease.

1. **Receipt chain process-safety** — done on this branch. `BEGIN IMMEDIATE`
   takes SQLite's RESERVED write lock *before* the head read, so the
   read-then-append is one atomic unit across processes. Prerequisite for
   everything else: without it, every later step just increases the number of
   writers racing the chain.
2. **Audit the rest of the shared-disk layer for the same shape.** `Store`, the
   `Vault`, and `governance_ledger` (also hash-chained) have not been checked for
   cross-process read-modify-write. Do this before anything is made durable,
   because durable state means *more* concurrent writers, not fewer.
3. **`SessionBinder._sessions`.** Sketch: same directory as the nonce file, one
   JSON file per session, `flock` around the read-modify-write of
   `used_call_nonces` — which is the hard part, not the session record. Losing a
   call-nonce mark reopens the per-call replay window that `verify_call` exists
   to close, so this must be *correct*, not merely shared. Needs an expiry sweep
   too: sessions currently die with the process, and a durable store inherits the
   job of not accumulating them forever.
4. **OAuth `_pending` / `_codes` / `_code_identity`.** Short TTLs (`_CODE_TTL` is
   300s) make these the cheapest to store and the most dangerous to get wrong:
   `_code_identity` carries the verified `(issuer, subject)`, and a miss must
   fail closed, never issue a token with no attributed identity.
5. **`_buckets`.** Last, and possibly never. The honest cheap fix is to divide
   the configured rate by the declared replica count and say so; a shared backend
   is only worth it when the limit is a real control rather than a courtesy.

## Tradeoffs, stated plainly

* **The guard can annoy.** A serve process killed with its home on a network
  filesystem where `flock` is unreliable could refuse a legitimate restart. NFS
  `flock` is the known weak spot. Mitigation is the override, and the fact that
  the lock is only taken in serve mode.
* **`BEGIN IMMEDIATE` serialises receipt writes across processes.** Two busy
  processes now queue on the audit write. A receipt write is milliseconds and the
  busy timeout is 30s (up from sqlite3's 5s default, which is thin for a home on
  network storage). The alternative is an audit trail that cannot be verified,
  which is not an alternative.
* **`isolation_level=None`** puts `receipts.py` in charge of its own
  transactions. That is the point, but it means any future write path in that
  module must go through `_write_txn` or it will silently autocommit.
* **Declaring single-instance closes a door.** If willow-mcp is later meant to
  run behind a load balancer, all of step 3-5 comes due at once. That is the
  right time to pay it: with a declared assumption, a deliberate decision, and
  the audit chain already safe underneath.

## What is not done

* `SessionBinder._sessions`, `_pending`/`_codes`/`_code_identity`, and `_buckets`
  are all **unchanged**. The lockout in §1 still reproduces, on purpose, and
  `tests/test_multi_instance_state.py` characterises it so it stays visible.
* `Store`, `Vault` and `governance_ledger` are **unaudited** for the
  read-modify-write shape that broke the receipt chain. `governance_ledger` is
  hash-chained the same way and is the obvious next place to look.
* No load-balancer or deployment-manifest change enforces the declaration
  outside the process. The lock catches a second instance; it does not stop
  someone writing `replicas: 2`.
