-- willow_compose.pieces — cross-repo composition workbench (nodes only, for now).
-- A "piece" is anything dropped in from any repo: a symbol, file, function,
-- tool, component, config fragment, or free-form concept. Edges come later.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS pieces (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Stable, caller-supplied identity for idempotent re-drops (upsert target).
    piece_key    text        NOT NULL UNIQUE,
    repo         text        NOT NULL,             -- source repo, e.g. 'willow-2.0'
    kind         text        NOT NULL,             -- symbol | file | function | class | tool | component | config | concept | snippet
    ref          text,                             -- path / fqn / symbol reference within the repo
    label        text,                             -- human-facing name
    lang         text,                             -- language, when it's code
    body         text,                             -- the dropped content itself (optional)
    source_path  text,                             -- absolute path in this env, when applicable
    tags         text[]      NOT NULL DEFAULT '{}',
    meta         jsonb       NOT NULL DEFAULT '{}',
    embedding    vector(768),                      -- optional; nomic-embed dim. Filled later for similarity.
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pieces_repo_idx  ON pieces (repo);
CREATE INDEX IF NOT EXISTS pieces_kind_idx  ON pieces (kind);
CREATE INDEX IF NOT EXISTS pieces_tags_idx  ON pieces USING gin (tags);
CREATE INDEX IF NOT EXISTS pieces_meta_idx  ON pieces USING gin (meta);
-- ANN index on embedding is deliberately deferred until rows carry vectors
-- (ivfflat/hnsw want data present or a chosen list/m first).

-- keep updated_at honest
CREATE OR REPLACE FUNCTION pieces_touch_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS pieces_touch ON pieces;
CREATE TRIGGER pieces_touch BEFORE UPDATE ON pieces
    FOR EACH ROW EXECUTE FUNCTION pieces_touch_updated_at();
