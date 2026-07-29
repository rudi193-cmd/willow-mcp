# `public.tasks` — one owner, and how to get there

## The state this fixes

Three repos each shipped `CREATE TABLE IF NOT EXISTS tasks` for the same
unqualified name, with three different primary keys:

| Repo | Definition | Primary key |
|------|-----------|-------------|
| `willow-2.0` | `core/pg_bridge.py:118` | `id TEXT PRIMARY KEY` |
| `safe-app-willow-grove` | `schema.sql` | `id BIGINT GENERATED ALWAYS AS IDENTITY` |
| `willow-mcp` | `docs/schema/tasks.postgres.sql` | `task_id text PRIMARY KEY` |

All three are unqualified, so all three resolve to `public.tasks`. `IF NOT
EXISTS` means the second and third creators **silently no-op** — the shape a
database ends up with is decided by boot order, and nothing reports it. A column
one repo's reader expects may simply not exist, with no error at create time and
no error at boot; only a failure much later, in a query, on someone else's
machine.

**willow-mcp already tolerates this** by introspecting rather than asserting
(`docs/design/schema-adaptation.md`, `schema_profile.resolve`), and treats its
own DDL as fresh-install-only. The other two assert their shape and get whatever
boot order gave them.

## The decision

**`willow-mcp`'s shape is canonical**, per the settled migration direction — the
good from willow-2.0 moves into willow-mcp, and willow-2.0 was a building block
rather than the destination.

Canonical absorbs two columns from willow-2.0 rather than dropping them:
`submitter_run_id` and `updated_at`. That repo's queue logic writes both, and
carrying them is what makes this a rename instead of data loss.

Grove's `cmd` is **not** absorbed. It is display-only — `panes/tasks.py:104,145`
render it as a truncated "Command" column — and canonical `task` carries the same
content. Grove reads `task` instead.

## Why this cannot be one step

Renaming `id` to `task_id` in a single migration breaks whichever consumer
deploys second. There is no ordering of a single-step rename that keeps a live
fleet working, so this is **expand → migrate → contract**:

| Phase | File | Effect |
|---|---|---|
| **Preflight** | `migrations/tasks-preflight.sql` | Read-only. Reports which of the shapes this database is in. |
| **Expand** | `migrations/2026-07-28-tasks-single-owner-expand.sql` | Additive only. Adds `task_id` populated from `id`, adds every missing canonical column. `id` stays. Both keys work. |
| *(consumers move)* | — | willow-2.0 and Grove change to canonical names. Any order; no coordination window. |
| **Contract** | `migrations/2026-07-28-tasks-single-owner-contract.sql` | Destructive. Preserves `id` as `legacy_id`, drops `id`, promotes `task_id` to PRIMARY KEY, drops `cmd`. |

**Expand is a complete, safe resting state.** If the consumer work stalls, a
database can sit in EXPANDED indefinitely with both keys working. There is no
pressure to run contract.

### Why `legacy_id` survives contract

Expand maps Grove's `BIGINT` to its decimal string, which is reversible only
while the original is present. Anything outside these three repos that recorded a
task id — a log line, a handoff note, an external ticket — refers to the old
value. Dropping `legacy_id` is a separate, later decision that needs its own
evidence.

## Order of work

1. **Preflight every database.** You do not know which shape you have; that is
   the whole problem.
2. **Run expand.** Idempotent, transactional, additive. Safe on a database
   already canonical.
3. **Move the consumers** — two follow-up changes, in either order:
   - `willow-2.0`: delete the `CREATE TABLE tasks` DDL at `core/pg_bridge.py:118`;
     write `task_id` instead of `id`.
   - `safe-app-willow-grove`: delete `public.tasks` from `schema.sql`; read
     `task_id` and `task` instead of `id` and `cmd`
     (`panes/tasks.py:41,49`, `panes/home.py:58,65`).
4. **Run contract**, once, when every reader has moved.

Neither repo should recreate the table afterwards. This is
[`DESIGN_CONSTRAINTS.md` §2](https://github.com/rudi193-cmd/willow-grove/blob/master/DESIGN_CONSTRAINTS.md)
— *do not create schema you do not own* — applied to the one table where the
constraint was actually being violated.

## Verified

Both migrations were run against live PostgreSQL 16, from all three starting
shapes, with data present:

- willow-2.0 shape → `T-abc` preserved as `task_id`
- Grove shape → BIGINT `1` became `'1'`, row intact
- already-canonical → no-op, still reports CANONICAL
- Both migrations idempotent on rerun
- Expand refuses a `tasks` table with neither key, and a missing table, each
  with an actionable message
- End-to-end Grove → expand → contract: both rows intact, `legacy_id` populated,
  PK is `task_id`, `cmd` gone

## What this does *not* fix

`willow.routing_decisions` was previously recorded as the same class of problem.
It is not: Grove's `schema.sql` and willow-2.0's `core/grove_reader.py:606`
define it **identically** — same columns, types, and order, differing only in
whitespace. `IF NOT EXISTS` over identical DDL is harmless and boot order does
not matter. It is duplication that could drift, not a live conflict, and the fix
is a single source of truth rather than a migration.

`frank_ledger` is also not an ownership defect. `docs/schema/frank-ledger-prevent-fork.sql`
states that the table is defined in willow-2.0's governance schema and that the
index migration is operator-run by design.
