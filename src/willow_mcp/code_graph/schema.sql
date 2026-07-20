-- sap/code_graph/schema.sql
-- Symbol graph schema — mirrors budget-aware-mcp's SQLite layout.

CREATE TABLE IF NOT EXISTS indexed_files (
    path        TEXT PRIMARY KEY,
    language    TEXT DEFAULT 'python',
    byte_size   INTEGER DEFAULT 0,
    line_count  INTEGER DEFAULT 0,
    symbol_count INTEGER DEFAULT 0,
    indexed_at  TEXT
);

CREATE TABLE IF NOT EXISTS symbols (
    fqn         TEXT PRIMARY KEY,   -- module.Class.method
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,      -- module|class|function|method
    file_path   TEXT NOT NULL,
    start_line  INTEGER DEFAULT 0,
    end_line    INTEGER DEFAULT 0,
    signature   TEXT DEFAULT '',
    byte_size   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_fqn  TEXT NOT NULL,
    target_fqn  TEXT NOT NULL,
    edge_type   TEXT NOT NULL,      -- import|inherit
    UNIQUE(source_fqn, target_fqn, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_fqn);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_fqn);
