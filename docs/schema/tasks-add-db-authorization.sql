-- B2 reviewed migration for an existing adopted tasks table.
--
-- Mirrors tasks-add-network-authorization.sql: it adds the column that carries
-- the operator-signed per-task envelope for gated local Postgres access
-- (allow_db, scope "database"). Only needed once WILLOW_MCP_ENFORCE_DB_PERIMETER
-- is turned on; task_submit refuses gated db work if the column is absent.
--
-- Do not apply as a side effect of server startup. The shared-table operator
-- applies this deliberately, then reconfirms the `tasks` schema mapping.
ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS db_authorization text NOT NULL DEFAULT '';
