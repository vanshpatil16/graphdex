"""SQLite DDL. FTS5 is content-synced to nodes and maintained by triggers —
never dropped and rebuilt."""

SCHEMA_VERSION = 1

DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    path         TEXT PRIMARY KEY,
    content_hash TEXT,
    language     TEXT NOT NULL,
    indexed_at   REAL NOT NULL,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS nodes (
    id             INTEGER PRIMARY KEY,
    kind           TEXT NOT NULL,
    name           TEXT NOT NULL,
    qualified_name TEXT NOT NULL UNIQUE,
    path           TEXT NOT NULL,
    line_start     INTEGER NOT NULL,
    line_end       INTEGER NOT NULL,
    language       TEXT NOT NULL,
    parent         TEXT,
    signature      TEXT,
    is_test        INTEGER NOT NULL DEFAULT 0,
    subtokens      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS edges (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    src        TEXT NOT NULL,
    dst        TEXT NOT NULL,
    path       TEXT NOT NULL,
    line       INTEGER NOT NULL DEFAULT 0,
    confidence INTEGER NOT NULL DEFAULT 2
);

CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src, kind);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst, kind);
CREATE INDEX IF NOT EXISTS idx_edges_path ON edges(path);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    name, qualified_name, subtokens,
    content='nodes', content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts(rowid, name, qualified_name, subtokens)
    VALUES (new.id, new.name, new.qualified_name, new.subtokens);
END;

CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, name, qualified_name, subtokens)
    VALUES ('delete', old.id, old.name, old.qualified_name, old.subtokens);
END;

CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, name, qualified_name, subtokens)
    VALUES ('delete', old.id, old.name, old.qualified_name, old.subtokens);
    INSERT INTO nodes_fts(rowid, name, qualified_name, subtokens)
    VALUES (new.id, new.name, new.qualified_name, new.subtokens);
END;
"""
