---
name: human-required
description: Human attention queue — enqueue blocked work, list open items, resolve with durable notes
---

@markdownai v1.0

# /human-required — Attention queue

Use when automation must **pause until a human acts** (consent, review, overload,
onboarding) or when you need a durable queue the operator can scan.

## Tools

| Tool | Permission | Purpose |
|------|------------|---------|
| `human_required_enqueue` | `human_loop_write` | Add item (`kind`: consent \| attestation \| review \| overload \| onboarding) |
| `human_required_list` | `human_loop_read` | List open items + stats |
| `human_required_resolve` | `human_loop_write` | Resolve / dismiss / acknowledge in place |

Rows are **updated, never deleted** — resolution records who/when/note.

`human_attestation_create` / `human_attestation_list` are the durable attestation
ledger (subject + statement). The attester is always the **calling** `app_id`; there
is no `attested_by` parameter — agents cannot forge operator signatures (sudo invariant).

## enqueue → resolve

```
human_required_enqueue(kind="review", title="…", summary="…", priority="high")
human_required_list(status="open")
human_required_resolve(item_id=…, status="resolved", note="…")
```

For knowledge atoms, pair with `human_attestation_create` when a human vouch is needed.

## Constraints

@constraint severity=critical
Never pass `app_id=willow` expecting `by_human` attestation unless the call is on the attested human-orchestrator seat — privilege comes from `human_session`, not a string the caller chooses.
