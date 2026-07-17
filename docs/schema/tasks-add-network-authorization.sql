-- B-37 reviewed migration for an existing adopted tasks table.
--
-- Do not apply as a side effect of server startup. The shared-table operator
-- applies this deliberately, then reconfirms the `tasks` schema mapping.
ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS network_authorization text NOT NULL DEFAULT '';
