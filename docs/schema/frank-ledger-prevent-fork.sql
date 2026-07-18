-- Governance continuity remediation — Loki B5FB7E2B §4.1
--
-- Make a forked FRANK chain a hard database error rather than a silent second
-- head. The GovernanceLedger append path serializes cooperating writers with a
-- session advisory lock, but "compatible with all writers" requires a guarantee
-- the database enforces regardless of whether a writer cooperates: no two rows
-- may chain off the same predecessor. A partial UNIQUE index on prev_hash gives
-- exactly that — each non-genesis hash can be referenced as a parent at most
-- once, so a concurrent append that read a stale head is rejected (the code
-- re-reads and retries) instead of forking.
--
-- Genesis rows carry prev_hash IS NULL and are excluded from the constraint, so
-- an empty chain can still be seeded. The frank_ledger table itself is defined
-- in the shared willow-2.0 governance schema; this migration only adds the
-- index and is idempotent.
--
-- APPLY: operator-run, once, against the shared governance database. Not applied
-- automatically by any tool (per the remediation scope: no migrations applied).
--   psql "$WILLOW_PG_DSN" -f docs/schema/frank-ledger-prevent-fork.sql

CREATE UNIQUE INDEX IF NOT EXISTS frank_ledger_no_fork
    ON frank_ledger (prev_hash)
    WHERE prev_hash IS NOT NULL;
