-- willow-mcp — FRANK governance ledger (Postgres)
--
-- Backs `frank_append`, `frank_read`, `frank_verify` and every
-- `envelope_citation` written by `voice/frank_bridge.py`. Read/write path:
-- `src/willow_mcp/governance_ledger.py` (TABLE = "frank_ledger").
--
-- Why this file exists. `frank-ledger-prevent-fork.sql` says the table itself
-- "is defined in the shared willow-2.0 governance schema" — true on a shared
-- fleet database, and false on every fresh install. This package ships three
-- MCP tools and a citation path against a table it never created, so a fresh
-- `sandbox-bootstrap.sh` produced a server whose FRANK tools returned
-- `frank_unavailable: relation "frank_ledger" does not exist` with nothing in
-- the repo to apply. That is a stand-up hole, not a schema-ownership claim:
-- on a shared fleet DB the table already exists and `IF NOT EXISTS` makes this
-- a no-op, exactly like `routing_decisions`.
--
-- Column shapes are taken from the queries that use them, not invented:
--   id          str(uuid.uuid4()) from GovernanceLedger.append          → text PK
--   project     filtered on by frank_read, hashed into the v2 digest    → text
--   event_type  hashed into both the v1 and v2 digests                  → text
--   content     inserted with psycopg2.extras.Json and queried with the
--               `->>` operator by append_citation                       → jsonb
--   prev_hash   NULL on genesis; carries the no-fork partial index      → text
--   hash        the chain digest itself                                 → text
--   created_at  written with clock_timestamp(); the chain is walked and
--               extended by this column's ORDER BY                      → timestamptz
--
-- `content` MUST be jsonb: append_citation meters grants with
-- `content->>'envelope_id'`, which a text column cannot answer.
--
-- created_at is NOT NULL with no default on purpose — every write supplies
-- clock_timestamp() explicitly, and a row that silently defaulted its position
-- in a chain that is ordered by this column would be a chain the ordering no
-- longer describes.

CREATE TABLE IF NOT EXISTS frank_ledger (
    id         text        PRIMARY KEY,
    project    text        NOT NULL DEFAULT '',
    event_type text        NOT NULL,
    content    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    prev_hash  text,
    hash       text        NOT NULL,
    created_at timestamptz NOT NULL
);

-- The chain is read head-first and walked oldest-first; both orderings are on
-- created_at, and verify() walks the whole table.
CREATE INDEX IF NOT EXISTS frank_ledger_created_at ON frank_ledger (created_at);

-- frank_read filters by project when one is given.
CREATE INDEX IF NOT EXISTS frank_ledger_project_created_at
    ON frank_ledger (project, created_at DESC);

-- Single-headedness, enforced by the database rather than by writer etiquette.
-- Identical to docs/schema/frank-ledger-prevent-fork.sql, repeated here so a
-- fresh install is fork-proof from its first row instead of from whenever an
-- operator remembers to run the migration. Both are `IF NOT EXISTS`, so
-- applying either or both, in any order, converges on the same index.
CREATE UNIQUE INDEX IF NOT EXISTS frank_ledger_no_fork
    ON frank_ledger (prev_hash)
    WHERE prev_hash IS NOT NULL;
