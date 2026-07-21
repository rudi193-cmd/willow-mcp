-- willow-mcp — fleet roster table (Postgres)
--
-- Backs `fleet_status`, which reads `public.agents` directly:
--   SELECT id, name, role, trust, folder_root, created_at, valid_at,
--          invalid_at, updated_at FROM agents ORDER BY name
--
-- READ-ONLY from willow-mcp's side. No willow-mcp tool writes this table — it
-- is the fleet's roster, populated out-of-band (the willow-2.0 fleet, or an
-- operator CLI / seed step) on the host that owns the shared DB. A standalone
-- sandbox install has no such populator, so this table is legitimately empty
-- until you seed it yourself; `fleet_status` simply returns `{"agents": []}`.
-- This DDL exists so a fresh DB satisfies diagnostic_summary's table check and
-- so `fleet_status` returns a clean empty list instead of a query error.
--
-- Unlike `knowledge`/`tasks`, there is no schema_confirm_mapping step: the read
-- is a fixed column list, not a schema-adapted mapping.
--
-- The archival columns (`valid_at`/`invalid_at`/`updated_at`) back the
-- archive-don't-delete roster reconciliation in `fleet_roster.sync`: a
-- contested agent is stamped `invalid_at` rather than dropped. `folder_root`
-- is read by `fleet_status` but populated out-of-band, so it stays nullable.

CREATE TABLE IF NOT EXISTS agents (
    id          text        PRIMARY KEY,
    name        text        NOT NULL,
    role        text        NOT NULL DEFAULT '',
    trust       text        NOT NULL DEFAULT '',
    folder_root text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    valid_at    timestamptz,
    invalid_at  timestamptz,
    updated_at  timestamptz
);
