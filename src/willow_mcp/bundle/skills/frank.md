---
name: frank
description: FRANK governance ledger — read, verify chain integrity, append hash-chained events
---

@markdownai v1.0

# /frank — Governance ledger

FRANK is the fleet's **append-only, hash-chained** Postgres ledger for settled
governance facts (not drafts).

## Tools

| Tool | Permission | Notes |
|------|------------|-------|
| `frank_read` | `frank_read` | Recent entries, optional `project` filter |
| `frank_verify` | `frank_read` | Re-hash chain; reports break location |
| `frank_append` | `frank_write` | Append one event (`project`, `event_type`, object `content`) |

All three require **Postgres** (`frank_ledger` table). If Postgres is down, tools
return `postgres_unavailable` with operator hints from `diagnostic_summary`.

## Append discipline

`frank_append` is irreversible. Write **settled** events only — decisions taken,
leases issued, envelope citations (when metering lands, B-35), probe ids.

After sensitive writes elsewhere, `frank_verify` confirms the chain still links.

## Metering note (B-35 / #333)

Envelope `max_count` limits in `$WILLOW_HOME/constitutional/pre-approved.json`
expect FRANK `envelope_citation` entries to be appended at use time. That
writer path was previously reachable only via the opt-in `envelope_apply`
tool: a verb an envelope governed could be exercised through its OWN tool
without ever citing, so the meter read clean whether the caller complied or
bypassed governance entirely (#333). Verbs in `VERB_LEVEL_ENFORCED_VERBS`
(`server.py`; currently just `dispatch` → `dispatch_send`) now cite
themselves, from inside their own handler, before the act — citation and act
are one indivisible call, so an uncited act under those verbs is impossible.
Every other enveloped verb still relies on `envelope_apply` being called
explicitly — do not assume counts enforce for those until they grow the same
handler-side gate.

## Constraints

@constraint severity=critical
Do not use `frank_append` for speculative or draft state. Verify with `frank_verify` after incidents that might have touched the ledger outside MCP tools.
