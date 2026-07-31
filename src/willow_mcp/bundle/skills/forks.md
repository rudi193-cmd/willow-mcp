---
name: forks
description: Parallel work lanes — open a fork, log changes, merge or abandon with fork_delete
---

@markdownai v1.0

# /forks — Work lanes

Use when two agents (or two threads of work) need **isolated change logs** under
one fleet store before merging or abandoning.

## Lifecycle

1. `fork_create(title=…, components=[…])` — snapshot env + open fork.
2. While working: `fork_log` records atom/kb edits against `fork_id`.
3. Before merge: `env_check(fork_id)` — diff env vs fork snapshot.
4. Close **one** way:
   - `fork_merge(fork_id, outcome_note=…)` — work landed.
   - `fork_delete(fork_id, reason=…)` — work abandoned (record kept, state `deleted`).

`fork_status` / `fork_list` are read-only inspection.

## fork_delete vs forget

`fork_delete` is **not** erasure. It closes the fork as DELETED, tallies change-log
entries as archived, and stores `reason`. Closed forks cannot reopen — inspect via
`fork_status` only.

Prefer `fork_delete` over silent abandonment so `fork_list(status="open")` stays honest.

## Permissions

Fork tools are gated under the fork permission groups in `gate.py` (read vs write).
Destructive close tools (`fork_merge`, `fork_delete`) require write grants.

## Constraints

@constraint severity=critical
Do not leave forks open after the work ends — merge or `fork_delete` with a reason. Run `env_check` before `fork_merge` when environment drift could explain a failure.
