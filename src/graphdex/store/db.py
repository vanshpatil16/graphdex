"""SQLite-backed graph store. All writes for one file happen in one
transaction; FTS stays in sync via triggers."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from ..models import ParsedFile
from ..subtokens import subtokenize
from .schema import DDL, SCHEMA_VERSION


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


class Store:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=30)
        self._conn.executescript(DDL)
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    # -- writes ----------------------------------------------------------

    def replace_file(self, parsed: ParsedFile) -> None:
        conn = self._conn
        with conn:
            conn.execute("DELETE FROM nodes WHERE path = ?", (parsed.path,))
            conn.execute("DELETE FROM edges WHERE path = ?", (parsed.path,))
            conn.executemany(
                "INSERT INTO nodes(kind, name, qualified_name, path, line_start,"
                " line_end, language, parent, signature, is_test, subtokens)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (n.kind, n.name, n.qualified_name, n.path, n.line_start,
                     n.line_end, n.language, n.parent, n.signature,
                     int(n.is_test), subtokenize(n.name))
                    for n in parsed.nodes
                ],
            )
            conn.executemany(
                "INSERT INTO edges(kind, src, dst, path, line, confidence)"
                " VALUES (?,?,?,?,?,?)",
                [
                    (e.kind, e.src, e.dst, e.path, e.line, int(e.confidence))
                    for e in parsed.edges
                ],
            )
            conn.execute(
                "INSERT OR REPLACE INTO files(path, content_hash, language,"
                " indexed_at, error) VALUES (?,?,?,?,NULL)",
                (parsed.path, parsed.content_hash, parsed.language, time.time()),
            )

    def remove_file(self, path: str) -> None:
        conn = self._conn
        with conn:
            conn.execute("DELETE FROM nodes WHERE path = ?", (path,))
            conn.execute("DELETE FROM edges WHERE path = ?", (path,))
            conn.execute("DELETE FROM files WHERE path = ?", (path,))

    def quarantine(self, path: str, language: str, error: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO files(path, content_hash, language,"
                " indexed_at, error) VALUES (?,NULL,?,?,?)",
                (path, language, time.time(), error[:500]),
            )

    # -- reads -----------------------------------------------------------

    def file_hashes(self) -> dict[str, str]:
        cur = self._conn.execute(
            "SELECT path, content_hash FROM files WHERE error IS NULL"
        )
        return {path: h for path, h in cur.fetchall()}

    def quarantined(self) -> list[dict[str, Any]]:
        return _rows(self._conn.execute(
            "SELECT path, language, error FROM files WHERE error IS NOT NULL"
        ))

    def stats(self) -> dict[str, Any]:
        conn = self._conn
        nodes = conn.execute("SELECT count(*) FROM nodes").fetchone()[0]
        edges = conn.execute("SELECT count(*) FROM edges").fetchone()[0]
        files = conn.execute(
            "SELECT count(*) FROM files WHERE error IS NULL"
        ).fetchone()[0]
        quarantined = conn.execute(
            "SELECT count(*) FROM files WHERE error IS NOT NULL"
        ).fetchone()[0]
        by_language = dict(conn.execute(
            "SELECT language, count(*) FROM files WHERE error IS NULL"
            " GROUP BY language"
        ).fetchall())
        return {
            "nodes": nodes, "edges": edges, "files": files,
            "quarantined": quarantined, "by_language": by_language,
        }

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        terms = subtokenize(query)
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms.split())
        try:
            cur = self._conn.execute(
                "SELECT n.name, n.qualified_name, n.kind, n.path, n.line_start,"
                " n.line_end, n.signature, -bm25(nodes_fts) AS score"
                " FROM nodes_fts JOIN nodes n ON n.id = nodes_fts.rowid"
                " WHERE nodes_fts MATCH ? ORDER BY bm25(nodes_fts) LIMIT ?",
                (match, limit),
            )
        except sqlite3.OperationalError:
            return []
        return _rows(cur)

    def node(self, qualified_name: str) -> dict[str, Any] | None:
        rows = _rows(self._conn.execute(
            "SELECT * FROM nodes WHERE qualified_name = ?", (qualified_name,)
        ))
        return rows[0] if rows else None

    def nodes_named(self, name: str) -> list[dict[str, Any]]:
        return _rows(self._conn.execute(
            "SELECT * FROM nodes WHERE name = ? OR qualified_name = ?",
            (name, name),
        ))

    def edges_into(self, dsts: list[str], kind: str,
                   min_confidence: int) -> list[dict[str, Any]]:
        if not dsts:
            return []
        marks = ",".join("?" for _ in dsts)
        return _rows(self._conn.execute(
            f"SELECT * FROM edges WHERE dst IN ({marks})"  # noqa: S608
            " AND kind = ? AND confidence >= ?",
            [*dsts, kind, min_confidence],
        ))

    def edges_out_of(self, srcs: list[str], kind: str,
                     min_confidence: int) -> list[dict[str, Any]]:
        if not srcs:
            return []
        marks = ",".join("?" for _ in srcs)
        return _rows(self._conn.execute(
            f"SELECT * FROM edges WHERE src IN ({marks})"  # noqa: S608
            " AND kind = ? AND confidence >= ?",
            [*srcs, kind, min_confidence],
        ))

    def close(self) -> None:
        self._conn.close()
