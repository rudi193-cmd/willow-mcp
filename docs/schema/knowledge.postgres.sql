-- willow-mcp — Postgres knowledge base table
--
-- willow-mcp ADAPTS to an existing `knowledge` table when one is present (see
-- docs/design/schema-adaptation.md); this DDL is for a fresh install that has
-- no such table yet. Columns match the canonical _KNOWLEDGE_FIELDS the server
-- maps (server.py: id, content, domain, source, tags). A host table that names
-- these columns differently is fine — the schema profiler resolves aliases and
-- omits anything it can't map; this file just gives a fresh DB the happy path.
--
-- After creating it, confirm the mapping once (writes stay locked until you do):
--   schema_confirm_mapping(app_id=..., table="knowledge")
-- then knowledge_ingest / kb_* / knowledge_search resolve against it.
--
-- Read path: knowledge_search does `content ILIKE %keyword%` (AND across
-- tokens), optionally filtered by `domain`. Write path: knowledge_ingest does
-- INSERT ... ON CONFLICT DO NOTHING, so a colliding id is a silent no-op, not
-- an error. `tags` is written as JSON (server wraps it when the column is
-- jsonb/json), so keep it jsonb here.

CREATE TABLE IF NOT EXISTS knowledge (
    id       text PRIMARY KEY,
    content  text  NOT NULL,
    domain   text  NOT NULL DEFAULT 'general',
    source   text  NOT NULL DEFAULT '',
    tags     jsonb NOT NULL DEFAULT '[]'::jsonb
);

-- knowledge_search filters by domain when one is passed.
CREATE INDEX IF NOT EXISTS idx_knowledge_domain ON knowledge (domain);
