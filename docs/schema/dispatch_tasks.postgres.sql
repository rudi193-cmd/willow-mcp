-- willow-mcp — dispatch packet mirror (Postgres)
--
-- Dispatch packets are filesystem-canonical: a standalone willow-mcp install
-- writes them under `$WILLOW_HOME/dispatch/<id>/` and never needs a database.
-- This table is an OPT-IN, best-effort MIRROR for fleet visibility: when an
-- operator runs willow-mcp as a fleet host (`WILLOW_MCP_DISPATCH_MIRROR` truthy)
-- and a host Postgres is reachable, `dispatch.dispatch_send` /
-- `dispatch.dispatch_set_status` upsert each packet's routing + status here, so
-- the fleet — which already reads store/knowledge/tasks/agents from shared
-- Postgres — can see willow-mcp's dispatches too.
--
-- WRITE-only from willow-mcp's side, and never load-bearing: the filesystem
-- packet is the source of truth. Every mirror write is wrapped best-effort, so a
-- missing or broken table cannot affect a dispatch that already wrote to disk.
-- A fresh DB does not need this table until mirroring is enabled; the mirror
-- creates it on first write (`CREATE TABLE IF NOT EXISTS`), and this file is the
-- canonical shape for anyone provisioning it ahead of time.
--
-- Unlike `knowledge`/`tasks`, there is no schema_confirm_mapping step: the write
-- is a fixed column list, not a schema-adapted mapping.

CREATE TABLE IF NOT EXISTS dispatch_tasks (
    dispatch_id text        PRIMARY KEY,
    from_app    text        NOT NULL DEFAULT '',
    to_app      text        NOT NULL DEFAULT '',
    role        text        NOT NULL DEFAULT '',
    phase       text        NOT NULL DEFAULT '',
    priority    text        NOT NULL DEFAULT 'normal',
    reply_to    text        NOT NULL DEFAULT '',
    summary     text        NOT NULL DEFAULT '',
    status      text        NOT NULL DEFAULT 'pending',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
