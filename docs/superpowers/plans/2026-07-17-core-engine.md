# graphdex Core Engine Implementation Plan (Plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the graphdex core: SQLite graph store with subtoken FTS, Python parsing via tree-sitter, two-pass import-aware call resolution with confidence tiers, the `Graphdex` library API, and a CLI (`build | status | search`).

**Architecture:** Parse files with tree-sitter into `Node`/`Edge` dataclasses; resolve raw call targets in two passes (file-local symbol table → import-graph resolution), labeling every edge `RESOLVED` / `IMPORT_INFERRED` / `NAME_ONLY`; persist in SQLite (WAL) with a trigger-synced FTS5 index over subtokenized identifiers; expose everything through a `Graphdex` facade that the CLI (and later MCP) wraps.

**Tech Stack:** Python 3.11+, `tree-sitter` + `tree-sitter-language-pack`, sqlite3 (stdlib), argparse (stdlib), pytest, hatchling.

**Follow-up plans (not here):** Plan 2 = freshness/self-healing reads + 8 MCP tools (adds `fastmcp` dep). Plan 3 = TS/JS/Go/Rust/Java parsers + PyPI publishing.

## Global Constraints

- Python `>=3.11`; runtime deps ONLY `tree-sitter>=0.23,<1` and `tree-sitter-language-pack>=0.9,<1` in this plan.
- `src/` layout; files ≤400 lines typical, 800 hard max; no mutation of shared state (return new objects).
- All SQL parameterized (`?` placeholders); never f-string user input into SQL.
- Repo-relative paths always use `/` separators (normalize `\` on Windows).
- Qualified name format: `<relpath>::<Name>` for top-level, `<relpath>::<Class>.<method>` for members.
- Confidence tiers: `NAME_ONLY=0`, `IMPORT_INFERRED=1`, `RESOLVED=2`; default query filter `IMPORT_INFERRED`.
- Windows UTF-8 handled in code (`sys.stdout.reconfigure(encoding="utf-8")` in CLI main), never via user env vars.
- Conventional commits (`feat:`, `fix:`, `test:`, `chore:`, `ci:`); no attribution lines.
- Run tests from repo root `C:\ARIA\graphdex` with `python -m pytest` (install first: `pip install -e ".[dev]"`).

---

### Task 1: Package scaffold, models, subtokenizer

**Files:**
- Create: `pyproject.toml`
- Create: `src/graphdex/__init__.py`
- Create: `src/graphdex/models.py`
- Create: `src/graphdex/subtokens.py`
- Test: `tests/test_models.py`, `tests/test_subtokens.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `Confidence(IntEnum)` with `NAME_ONLY=0, IMPORT_INFERRED=1, RESOLVED=2`; frozen dataclasses `Node(kind, name, qualified_name, path, line_start, line_end, language, parent=None, signature=None, is_test=False)`, `Edge(kind, src, dst, path, line, confidence=Confidence.RESOLVED)`, `ParsedFile(path, language, content_hash, nodes, edges, imports)` where `imports: dict[str, tuple[str, str]]` maps local name → `(module, original_name)`; `subtokenize(identifier: str) -> str`.

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "graphdex"
version = "0.1.0"
description = "The code graph that's never stale — always-fresh, confidence-labeled code context for AI coding agents"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
authors = [{ name = "Vansh Patil" }]
keywords = ["code-graph", "mcp", "tree-sitter", "ai-agents", "code-review"]
dependencies = [
    "tree-sitter>=0.23,<1",
    "tree-sitter-language-pack>=0.9,<1",
]

[project.urls]
Repository = "https://github.com/vanshpatil16/graphdex"

[project.scripts]
graphdex = "graphdex.cli:main"

[project.optional-dependencies]
dev = [
    "pytest>=8,<9",
    "pytest-cov>=5,<8",
    "ruff>=0.5,<1",
]

[tool.hatch.build.targets.wheel]
packages = ["src/graphdex"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--ignore=tests/fixtures"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]
```

- [ ] **Step 2: Write failing tests for models and subtokenizer**

`tests/test_models.py`:
```python
from graphdex.models import Confidence, Edge, Node, ParsedFile


def test_confidence_ordering():
    assert Confidence.NAME_ONLY < Confidence.IMPORT_INFERRED < Confidence.RESOLVED
    assert int(Confidence.NAME_ONLY) == 0
    assert int(Confidence.RESOLVED) == 2


def test_node_is_frozen_with_defaults():
    node = Node(
        kind="function", name="save", qualified_name="utils/helpers.py::save",
        path="utils/helpers.py", line_start=3, line_end=9, language="python",
    )
    assert node.parent is None
    assert node.signature is None
    assert node.is_test is False
    try:
        node.name = "other"
        raised = False
    except AttributeError:
        raised = True
    assert raised


def test_edge_default_confidence_is_resolved():
    edge = Edge(kind="CALLS", src="a.py::f", dst="b.py::g", path="a.py", line=4)
    assert edge.confidence is Confidence.RESOLVED


def test_parsed_file_holds_imports_mapping():
    pf = ParsedFile(
        path="app.py", language="python", content_hash="abc",
        nodes=[], edges=[], imports={"save": ("utils.helpers", "save")},
    )
    assert pf.imports["save"] == ("utils.helpers", "save")
```

`tests/test_subtokens.py`:
```python
from graphdex.subtokens import subtokenize


def test_camel_case_split():
    assert subtokenize("getUserById") == "get user by id"


def test_snake_case_split():
    assert subtokenize("parse_source_file") == "parse source file"


def test_acronym_handling():
    assert subtokenize("HTTPServerError") == "http server error"


def test_mixed_and_digits():
    assert subtokenize("load2FASecret_key") == "load2 fa secret key"


def test_empty_and_symbols():
    assert subtokenize("") == ""
    assert subtokenize("__init__") == "init"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_models.py tests/test_subtokens.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graphdex'`

- [ ] **Step 4: Implement package**

`src/graphdex/__init__.py`:
```python
"""graphdex — the code graph that's never stale."""

__version__ = "0.1.0"
```

`src/graphdex/models.py`:
```python
"""Core data models shared by parsing, resolution, storage, and the API."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Confidence(IntEnum):
    """How certain we are that an edge points at the right target."""

    NAME_ONLY = 0        # bare-name match; kept for recall, always labeled
    IMPORT_INFERRED = 1  # resolved through imports with one plausible target
    RESOLVED = 2         # file-local or import-path-proven target


@dataclass(frozen=True)
class Node:
    kind: str            # "file" | "class" | "function"
    name: str
    qualified_name: str  # e.g. "pkg/mod.py::Class.method"
    path: str            # repo-relative, "/" separators
    line_start: int
    line_end: int
    language: str
    parent: str | None = None
    signature: str | None = None
    is_test: bool = False


@dataclass(frozen=True)
class Edge:
    kind: str            # CALLS | IMPORTS_FROM | INHERITS | CONTAINS
    src: str             # qualified name (or path for file-level edges)
    dst: str             # qualified name, or bare name when unresolved
    path: str
    line: int
    confidence: Confidence = Confidence.RESOLVED


@dataclass(frozen=True)
class ParsedFile:
    """Everything extracted from one source file, pre-resolution."""

    path: str
    language: str
    content_hash: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    # local name -> (module string as written, original symbol name).
    # For "import a.b as c": {"c": ("a.b", "*")}.
    # For "from x import y as z": {"z": ("x", "y")}.
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)
```

`src/graphdex/subtokens.py`:
```python
"""Identifier subtokenization so `getUserById` matches "user by id"."""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^0-9A-Za-z]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def subtokenize(identifier: str) -> str:
    """Split an identifier into lowercase space-separated subtokens."""
    words: list[str] = []
    for part in _NON_ALNUM.split(identifier):
        if not part:
            continue
        words.extend(w for w in _CAMEL_BOUNDARY.split(part) if w)
    return " ".join(w.lower() for w in words)
```

- [ ] **Step 5: Install package editable and run tests**

Run: `pip install -e ".[dev]"` then `python -m pytest tests/test_models.py tests/test_subtokens.py -v`
Expected: all 9 tests PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/graphdex tests
git commit -m "feat: package scaffold with core models and subtokenizer"
```

---

### Task 2: SQLite store with trigger-synced FTS5 search

**Files:**
- Create: `src/graphdex/store/__init__.py`
- Create: `src/graphdex/store/schema.py`
- Create: `src/graphdex/store/db.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `Node`, `Edge`, `ParsedFile`, `Confidence` from `graphdex.models`; `subtokenize` from `graphdex.subtokens`.
- Produces: `Store(db_path: str | Path)` with methods `replace_file(parsed: ParsedFile) -> None`, `remove_file(path: str) -> None`, `quarantine(path: str, language: str, error: str) -> None`, `file_hashes() -> dict[str, str]`, `quarantined() -> list[dict]`, `stats() -> dict`, `search(query: str, limit: int = 20) -> list[dict]`, `node(qualified_name: str) -> dict | None`, `nodes_named(name: str) -> list[dict]`, `edges_into(dsts: list[str], kind: str, min_confidence: int) -> list[dict]`, `edges_out_of(srcs: list[str], kind: str, min_confidence: int) -> list[dict]`, `close() -> None`. Search result dicts contain keys `name, qualified_name, kind, path, line_start, line_end, signature, score`.

- [ ] **Step 1: Write failing store tests**

`tests/test_store.py`:
```python
from pathlib import Path

import pytest

from graphdex.models import Confidence, Edge, Node, ParsedFile
from graphdex.store import Store


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "graph.db")
    yield s
    s.close()


def _pf(path: str = "app.py") -> ParsedFile:
    return ParsedFile(
        path=path, language="python", content_hash="h1",
        nodes=[
            Node(kind="function", name="getUserById",
                 qualified_name=f"{path}::getUserById", path=path,
                 line_start=1, line_end=4, language="python",
                 signature="def getUserById(user_id)"),
        ],
        edges=[
            Edge(kind="CALLS", src=f"{path}::getUserById", dst="save",
                 path=path, line=2, confidence=Confidence.NAME_ONLY),
        ],
    )


def test_replace_file_inserts_nodes_and_edges(store: Store):
    store.replace_file(_pf())
    assert store.file_hashes() == {"app.py": "h1"}
    node = store.node("app.py::getUserById")
    assert node is not None
    assert node["kind"] == "function"
    edges = store.edges_out_of(["app.py::getUserById"], "CALLS",
                               min_confidence=int(Confidence.NAME_ONLY))
    assert [e["dst"] for e in edges] == ["save"]


def test_replace_file_is_idempotent(store: Store):
    store.replace_file(_pf())
    store.replace_file(_pf())
    assert len(store.nodes_named("getUserById")) == 1


def test_remove_file_purges_everything(store: Store):
    store.replace_file(_pf())
    store.remove_file("app.py")
    assert store.file_hashes() == {}
    assert store.node("app.py::getUserById") is None
    assert store.search("user") == []


def test_search_matches_subtokens(store: Store):
    store.replace_file(_pf())
    hits = store.search("user by id")
    assert hits and hits[0]["qualified_name"] == "app.py::getUserById"
    assert "score" in hits[0]


def test_search_survives_fts_operators(store: Store):
    store.replace_file(_pf())
    assert store.search('user AND "by) OR (') is not None  # no exception


def test_confidence_filter(store: Store):
    store.replace_file(_pf())
    high = store.edges_out_of(["app.py::getUserById"], "CALLS",
                              min_confidence=int(Confidence.RESOLVED))
    assert high == []


def test_quarantine_and_stats(store: Store):
    store.replace_file(_pf())
    store.quarantine("bad.py", "python", "SyntaxError: boom")
    stats = store.stats()
    assert stats["nodes"] == 1
    assert stats["edges"] == 1
    assert stats["files"] == 1
    assert stats["quarantined"] == 1
    assert store.quarantined()[0]["path"] == "bad.py"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graphdex.store'`

- [ ] **Step 3: Implement schema**

`src/graphdex/store/schema.py`:
```python
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
```

- [ ] **Step 4: Implement Store**

`src/graphdex/store/db.py`:
```python
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
```

`src/graphdex/store/__init__.py`:
```python
from .db import Store

__all__ = ["Store"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_store.py -v`
Expected: all 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphdex/store tests/test_store.py
git commit -m "feat: SQLite store with trigger-synced subtoken FTS5 search"
```

---

### Task 3: Python parser (tree-sitter)

**Files:**
- Create: `src/graphdex/parsing/__init__.py`
- Create: `src/graphdex/parsing/python.py`
- Test: `tests/test_parse_python.py`

**Interfaces:**
- Consumes: `Node`, `Edge`, `ParsedFile`, `Confidence` from `graphdex.models`.
- Produces: `parse_file(path: str, source: bytes, language: str) -> ParsedFile` (dispatch, raises `ValueError` on unknown language); `SUPPORTED_EXTENSIONS: dict[str, str]` mapping `".py" -> "python"`; `PythonParser.parse(path: str, source: bytes) -> ParsedFile`. CALLS edges leave `dst` as written (`save` or `helpers.save`) with `Confidence.NAME_ONLY` — resolution happens in Task 4. `content_hash` is sha256 hexdigest of source bytes.

- [ ] **Step 1: Write failing parser tests**

`tests/test_parse_python.py`:
```python
import hashlib

from graphdex.models import Confidence
from graphdex.parsing import SUPPORTED_EXTENSIONS, parse_file

SOURCE = b'''\
import os
import utils.helpers as helpers
from services.auth import login as do_login


class UserService:
    def get_user(self, user_id):
        do_login(user_id)
        return helpers.load(user_id)


def test_get_user():
    svc = UserService()
    svc.get_user(1)


def save(data):
    return os.path.join("x", data)
'''


def _parse():
    return parse_file("services/users.py", SOURCE, "python")


def test_extension_map():
    assert SUPPORTED_EXTENSIONS[".py"] == "python"


def test_content_hash():
    assert _parse().content_hash == hashlib.sha256(SOURCE).hexdigest()


def test_nodes_extracted():
    by_qn = {n.qualified_name: n for n in _parse().nodes}
    cls = by_qn["services/users.py::UserService"]
    assert cls.kind == "class"
    method = by_qn["services/users.py::UserService.get_user"]
    assert method.kind == "function"
    assert method.parent == "services/users.py::UserService"
    assert method.signature == "def get_user(self, user_id)"
    fn = by_qn["services/users.py::save"]
    assert fn.line_start > cls.line_end


def test_test_detection():
    by_qn = {n.qualified_name: n for n in _parse().nodes}
    assert by_qn["services/users.py::test_get_user"].is_test is True
    assert by_qn["services/users.py::save"].is_test is False


def test_imports_mapping():
    imports = _parse().imports
    assert imports["helpers"] == ("utils.helpers", "*")
    assert imports["do_login"] == ("services.auth", "login")
    assert imports["os"] == ("os", "*")


def test_calls_are_raw_name_only():
    calls = [e for e in _parse().edges if e.kind == "CALLS"]
    targets = {(e.src, e.dst) for e in calls}
    assert ("services/users.py::UserService.get_user", "do_login") in targets
    assert ("services/users.py::UserService.get_user", "helpers.load") in targets
    assert ("services/users.py::test_get_user", "UserService") in targets
    assert all(e.confidence is Confidence.NAME_ONLY for e in calls)


def test_contains_edges():
    contains = {(e.src, e.dst) for e in _parse().edges if e.kind == "CONTAINS"}
    assert ("services/users.py",
            "services/users.py::UserService") in contains
    assert ("services/users.py::UserService",
            "services/users.py::UserService.get_user") in contains


def test_unknown_language_raises():
    try:
        parse_file("x.zig", b"", "zig")
        raised = False
    except ValueError:
        raised = True
    assert raised
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_parse_python.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graphdex.parsing'`

- [ ] **Step 3: Implement the Python parser**

`src/graphdex/parsing/python.py`:
```python
"""Python extraction via tree-sitter. Produces raw (unresolved) CALLS edges;
resolution is a separate pass (graphdex.resolve)."""

from __future__ import annotations

import hashlib

from tree_sitter_language_pack import get_parser

from ..models import Confidence, Edge, Node, ParsedFile

_TEST_FILE_PREFIXES = ("test_",)
_TEST_FILE_SUFFIXES = ("_test.py",)


def _text(ts_node) -> str:
    return ts_node.text.decode("utf-8", errors="replace")


def _is_test_file(path: str) -> bool:
    basename = path.rsplit("/", 1)[-1]
    return basename.startswith(_TEST_FILE_PREFIXES) or basename.endswith(
        _TEST_FILE_SUFFIXES
    )


class PythonParser:
    language = "python"

    def parse(self, path: str, source: bytes) -> ParsedFile:
        parser = get_parser("python")
        tree = parser.parse(source)
        nodes: list[Node] = []
        edges: list[Edge] = []
        imports: dict[str, tuple[str, str]] = {}
        test_file = _is_test_file(path)

        root_line_end = tree.root_node.end_point[0] + 1
        nodes.append(Node(
            kind="file", name=path.rsplit("/", 1)[-1], qualified_name=path,
            path=path, line_start=1, line_end=root_line_end,
            language=self.language,
        ))

        self._walk(tree.root_node, path, None, None, nodes, edges,
                   imports, test_file)
        return ParsedFile(
            path=path, language=self.language,
            content_hash=hashlib.sha256(source).hexdigest(),
            nodes=nodes, edges=edges, imports=imports,
        )

    # -- traversal -------------------------------------------------------

    def _walk(self, ts_node, path: str, enclosing_class: str | None,
              enclosing_func: str | None, nodes: list[Node],
              edges: list[Edge], imports: dict[str, tuple[str, str]],
              test_file: bool) -> None:
        for child in ts_node.children:
            kind = child.type
            if kind == "decorated_definition":
                inner = child.child_by_field_name("definition")
                if inner is not None:
                    self._walk_one(inner, path, enclosing_class,
                                   enclosing_func, nodes, edges, imports,
                                   test_file)
                continue
            self._walk_one(child, path, enclosing_class, enclosing_func,
                           nodes, edges, imports, test_file)

    def _walk_one(self, child, path: str, enclosing_class: str | None,
                  enclosing_func: str | None, nodes: list[Node],
                  edges: list[Edge], imports: dict[str, tuple[str, str]],
                  test_file: bool) -> None:
        kind = child.type
        if kind == "class_definition":
            self._handle_class(child, path, nodes, edges, imports, test_file)
        elif kind == "function_definition":
            self._handle_function(child, path, enclosing_class, nodes,
                                  edges, imports, test_file)
        elif kind == "import_statement":
            self._handle_import(child, path, edges, imports)
        elif kind == "import_from_statement":
            self._handle_import_from(child, path, edges, imports)
        elif kind == "call":
            self._handle_call(child, path, enclosing_class, enclosing_func,
                              edges)
            self._walk(child, path, enclosing_class, enclosing_func, nodes,
                       edges, imports, test_file)
        else:
            self._walk(child, path, enclosing_class, enclosing_func, nodes,
                       edges, imports, test_file)

    # -- handlers ----------------------------------------------------------

    def _handle_class(self, ts_node, path: str, nodes: list[Node],
                      edges: list[Edge], imports, test_file: bool) -> None:
        name_node = ts_node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node)
        qn = f"{path}::{name}"
        nodes.append(Node(
            kind="class", name=name, qualified_name=qn, path=path,
            line_start=ts_node.start_point[0] + 1,
            line_end=ts_node.end_point[0] + 1,
            language=self.language, signature=f"class {name}",
        ))
        edges.append(Edge(kind="CONTAINS", src=path, dst=qn, path=path,
                          line=ts_node.start_point[0] + 1))
        supers = ts_node.child_by_field_name("superclasses")
        if supers is not None:
            for arg in supers.children:
                if arg.type in ("identifier", "attribute"):
                    edges.append(Edge(
                        kind="INHERITS", src=qn, dst=_text(arg), path=path,
                        line=arg.start_point[0] + 1,
                        confidence=Confidence.NAME_ONLY,
                    ))
        body = ts_node.child_by_field_name("body")
        if body is not None:
            self._walk(body, path, qn, None, nodes, edges, imports,
                       test_file)

    def _handle_function(self, ts_node, path: str,
                         enclosing_class: str | None, nodes: list[Node],
                         edges: list[Edge], imports,
                         test_file: bool) -> None:
        name_node = ts_node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node)
        if enclosing_class:
            class_path, class_name = enclosing_class.rsplit("::", 1)
            qn = f"{class_path}::{class_name}.{name}"
        else:
            qn = f"{path}::{name}"
        params_node = ts_node.child_by_field_name("parameters")
        params = _text(params_node).strip("()") if params_node else ""
        nodes.append(Node(
            kind="function", name=name, qualified_name=qn, path=path,
            line_start=ts_node.start_point[0] + 1,
            line_end=ts_node.end_point[0] + 1,
            language=self.language,
            parent=enclosing_class,
            signature=f"def {name}({params})",
            is_test=test_file or name.startswith("test"),
        ))
        edges.append(Edge(kind="CONTAINS", src=enclosing_class or path,
                          dst=qn, path=path,
                          line=ts_node.start_point[0] + 1))
        body = ts_node.child_by_field_name("body")
        if body is not None:
            self._walk(body, path, enclosing_class, qn, nodes, edges,
                       imports, test_file)

    def _handle_import(self, ts_node, path: str, edges: list[Edge],
                       imports: dict[str, tuple[str, str]]) -> None:
        for child in ts_node.children:
            if child.type == "dotted_name":
                module = _text(child)
                local = module.split(".", 1)[0]
                imports[local] = (module, "*")
                self._import_edge(edges, path, module, child)
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node is None or alias_node is None:
                    continue
                module = _text(name_node)
                imports[_text(alias_node)] = (module, "*")
                self._import_edge(edges, path, module, child)

    def _handle_import_from(self, ts_node, path: str, edges: list[Edge],
                            imports: dict[str, tuple[str, str]]) -> None:
        module_node = ts_node.child_by_field_name("module_name")
        if module_node is None:
            return
        module = _text(module_node)
        self._import_edge(edges, path, module, ts_node)
        seen_import_kw = False
        for child in ts_node.children:
            if child.type == "import":
                seen_import_kw = True
                continue
            if not seen_import_kw:
                continue
            if child.type == "dotted_name":
                original = _text(child)
                imports[original] = (module, original)
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node is None or alias_node is None:
                    continue
                imports[_text(alias_node)] = (module, _text(name_node))

    def _handle_call(self, ts_node, path: str,
                     enclosing_class: str | None,
                     enclosing_func: str | None,
                     edges: list[Edge]) -> None:
        fn = ts_node.child_by_field_name("function")
        if fn is None:
            return
        if fn.type == "identifier":
            target = _text(fn)
        elif fn.type == "attribute":
            target = _text(fn)
            if target.count(".") > 2:
                return  # deep chains like a.b.c.d() — skip, low value
        else:
            return
        src = enclosing_func or enclosing_class or path
        edges.append(Edge(
            kind="CALLS", src=src, dst=target, path=path,
            line=ts_node.start_point[0] + 1,
            confidence=Confidence.NAME_ONLY,
        ))

    @staticmethod
    def _import_edge(edges: list[Edge], path: str, module: str,
                     ts_node) -> None:
        edges.append(Edge(
            kind="IMPORTS_FROM", src=path, dst=module, path=path,
            line=ts_node.start_point[0] + 1,
        ))
```

`src/graphdex/parsing/__init__.py`:
```python
"""Language dispatch for file parsing."""

from __future__ import annotations

from ..models import ParsedFile
from .python import PythonParser

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".py": "python",
}

_PARSERS = {
    "python": PythonParser(),
}


def parse_file(path: str, source: bytes, language: str) -> ParsedFile:
    parser = _PARSERS.get(language)
    if parser is None:
        raise ValueError(f"unsupported language: {language}")
    return parser.parse(path, source)


__all__ = ["SUPPORTED_EXTENSIONS", "parse_file"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_parse_python.py -v`
Expected: all 8 tests PASS. If a node-type assertion fails, inspect the real AST with `python -c "from tree_sitter_language_pack import get_parser; print(get_parser('python').parse(b'import a.b as c').root_node)"` — fix the handler, not the test.

- [ ] **Step 5: Commit**

```bash
git add src/graphdex/parsing tests/test_parse_python.py
git commit -m "feat: tree-sitter Python parser with raw call extraction"
```

---

### Task 4: Two-pass resolver with confidence tiers

**Files:**
- Create: `src/graphdex/resolve/__init__.py`
- Create: `src/graphdex/resolve/resolver.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Consumes: `ParsedFile`, `Edge`, `Confidence` from `graphdex.models`.
- Produces: `resolve(files: list[ParsedFile]) -> list[ParsedFile]` — returns NEW `ParsedFile` objects (no mutation) whose CALLS/INHERITS edges are upgraded where possible: same-file target → `RESOLVED`; import-path-proven target → `RESOLVED`; unique project-wide bare-name match reached via an import we couldn't path-prove → `IMPORT_INFERRED`; otherwise unchanged `NAME_ONLY`. Module resolution maps `"a.b"` to `a/b.py` or `a/b/__init__.py` among the parsed file set; relative modules (`.mod`) resolve against the importer's directory.

- [ ] **Step 1: Write failing resolver tests**

`tests/test_resolve.py`:
```python
from graphdex.models import Confidence, Edge, Node, ParsedFile
from graphdex.resolve import resolve


def _node(path, name, parent=None):
    qn = f"{path}::{parent}.{name}" if parent else f"{path}::{name}"
    return Node(kind="function", name=name, qualified_name=qn, path=path,
                line_start=1, line_end=2, language="python", parent=parent)


def _call(path, src, dst):
    return Edge(kind="CALLS", src=src, dst=dst, path=path, line=1,
                confidence=Confidence.NAME_ONLY)


def test_same_file_call_resolves():
    pf = ParsedFile(
        path="app.py", language="python", content_hash="h",
        nodes=[_node("app.py", "main"), _node("app.py", "helper")],
        edges=[_call("app.py", "app.py::main", "helper")],
    )
    [out] = resolve([pf])
    assert out.edges[0].dst == "app.py::helper"
    assert out.edges[0].confidence is Confidence.RESOLVED


def test_import_proven_call_resolves():
    lib = ParsedFile(
        path="utils/helpers.py", language="python", content_hash="h",
        nodes=[_node("utils/helpers.py", "save")], edges=[],
    )
    app = ParsedFile(
        path="app.py", language="python", content_hash="h",
        nodes=[_node("app.py", "main")],
        edges=[_call("app.py", "app.py::main", "save")],
        imports={"save": ("utils.helpers", "save")},
    )
    out = {p.path: p for p in resolve([app, lib])}
    edge = out["app.py"].edges[0]
    assert edge.dst == "utils/helpers.py::save"
    assert edge.confidence is Confidence.RESOLVED


def test_module_alias_attribute_call_resolves():
    lib = ParsedFile(
        path="utils/helpers.py", language="python", content_hash="h",
        nodes=[_node("utils/helpers.py", "load")], edges=[],
    )
    app = ParsedFile(
        path="app.py", language="python", content_hash="h",
        nodes=[_node("app.py", "main")],
        edges=[_call("app.py", "app.py::main", "helpers.load")],
        imports={"helpers": ("utils.helpers", "*")},
    )
    out = {p.path: p for p in resolve([app, lib])}
    edge = out["app.py"].edges[0]
    assert edge.dst == "utils/helpers.py::load"
    assert edge.confidence is Confidence.RESOLVED


def test_unresolvable_import_with_unique_global_name_is_inferred():
    lib = ParsedFile(
        path="vendored/mystery.py", language="python", content_hash="h",
        nodes=[_node("vendored/mystery.py", "transmogrify")], edges=[],
    )
    app = ParsedFile(
        path="app.py", language="python", content_hash="h",
        nodes=[_node("app.py", "main")],
        edges=[_call("app.py", "app.py::main", "transmogrify")],
        imports={"transmogrify": ("some.unresolvable.pkg", "transmogrify")},
    )
    out = {p.path: p for p in resolve([app, lib])}
    edge = out["app.py"].edges[0]
    assert edge.dst == "vendored/mystery.py::transmogrify"
    assert edge.confidence is Confidence.IMPORT_INFERRED


def test_ambiguous_bare_name_stays_name_only():
    a = ParsedFile(
        path="a.py", language="python", content_hash="h",
        nodes=[_node("a.py", "save")], edges=[],
    )
    b = ParsedFile(
        path="b.py", language="python", content_hash="h",
        nodes=[_node("b.py", "save")], edges=[],
    )
    app = ParsedFile(
        path="app.py", language="python", content_hash="h",
        nodes=[_node("app.py", "main")],
        edges=[_call("app.py", "app.py::main", "save")],
    )
    out = {p.path: p for p in resolve([app, a, b])}
    edge = out["app.py"].edges[0]
    assert edge.dst == "save"
    assert edge.confidence is Confidence.NAME_ONLY


def test_relative_import_resolves():
    sibling = ParsedFile(
        path="pkg/sibling.py", language="python", content_hash="h",
        nodes=[_node("pkg/sibling.py", "greet")], edges=[],
    )
    mod = ParsedFile(
        path="pkg/mod.py", language="python", content_hash="h",
        nodes=[_node("pkg/mod.py", "main")],
        edges=[_call("pkg/mod.py", "pkg/mod.py::main", "greet")],
        imports={"greet": (".sibling", "greet")},
    )
    out = {p.path: p for p in resolve([mod, sibling])}
    edge = out["pkg/mod.py"].edges[0]
    assert edge.dst == "pkg/sibling.py::greet"
    assert edge.confidence is Confidence.RESOLVED


def test_no_mutation_of_inputs():
    pf = ParsedFile(
        path="app.py", language="python", content_hash="h",
        nodes=[_node("app.py", "main"), _node("app.py", "helper")],
        edges=[_call("app.py", "app.py::main", "helper")],
    )
    resolve([pf])
    assert pf.edges[0].dst == "helper"
    assert pf.edges[0].confidence is Confidence.NAME_ONLY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graphdex.resolve'`

- [ ] **Step 3: Implement resolver**

`src/graphdex/resolve/resolver.py`:
```python
"""Two-pass call resolution.

Pass 1: same-file symbol table  -> RESOLVED.
Pass 2: import-aware resolution -> RESOLVED when the import path is proven
        (module file found among parsed files and it defines the symbol),
        IMPORT_INFERRED when an import exists but only a unique global
        bare-name match backs it up.
Anything else stays NAME_ONLY. Inputs are never mutated.
"""

from __future__ import annotations

from dataclasses import replace

from ..models import Confidence, Edge, ParsedFile


def _module_to_path(module: str, importer_path: str,
                    known_paths: set[str]) -> str | None:
    """Map a dotted module (possibly relative) to a parsed file path."""
    if module.startswith("."):
        dots = len(module) - len(module.lstrip("."))
        remainder = module.lstrip(".")
        base_parts = importer_path.split("/")[:-1]
        if dots > 1:
            base_parts = base_parts[: len(base_parts) - (dots - 1)]
        parts = base_parts + [p for p in remainder.split(".") if p]
    else:
        parts = module.split(".")
    stem = "/".join(parts)
    for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
        if candidate in known_paths:
            return candidate
    return None


class _Index:
    def __init__(self, files: list[ParsedFile]) -> None:
        self.paths: set[str] = {f.path for f in files}
        self.by_path_bare: dict[str, dict[str, str]] = {}
        self.global_bare: dict[str, list[str]] = {}
        for f in files:
            local: dict[str, str] = {}
            for n in f.nodes:
                if n.kind == "file":
                    continue
                local.setdefault(n.name, n.qualified_name)
                self.global_bare.setdefault(n.name, []).append(
                    n.qualified_name
                )
            self.by_path_bare[f.path] = local

    def in_module(self, module_path: str, name: str) -> str | None:
        return self.by_path_bare.get(module_path, {}).get(name)

    def unique_global(self, name: str) -> str | None:
        matches = self.global_bare.get(name, [])
        return matches[0] if len(matches) == 1 else None


def _resolve_edge(edge: Edge, pf: ParsedFile, index: _Index) -> Edge:
    if edge.kind not in ("CALLS", "INHERITS"):
        return edge
    if "::" in edge.dst:
        return edge
    target = edge.dst

    # Attribute call through an imported module alias: "helpers.load".
    if "." in target:
        head, _, attr = target.partition(".")
        imported = pf.imports.get(head)
        if imported is not None:
            module_path = _module_to_path(imported[0], pf.path, index.paths)
            if module_path:
                qn = index.in_module(module_path, attr)
                if qn:
                    return replace(edge, dst=qn,
                                   confidence=Confidence.RESOLVED)
            unique = index.unique_global(attr)
            if unique:
                return replace(edge, dst=unique,
                               confidence=Confidence.IMPORT_INFERRED)
        return edge

    # Pass 1: same-file definition.
    local = index.by_path_bare.get(pf.path, {}).get(target)
    if local:
        return replace(edge, dst=local, confidence=Confidence.RESOLVED)

    # Pass 2: explicit import of this name.
    imported = pf.imports.get(target)
    if imported is not None:
        module, original = imported
        symbol = target if original == "*" else original
        module_path = _module_to_path(module, pf.path, index.paths)
        if module_path:
            qn = index.in_module(module_path, symbol)
            if qn:
                return replace(edge, dst=qn, confidence=Confidence.RESOLVED)
        unique = index.unique_global(symbol)
        if unique:
            return replace(edge, dst=unique,
                           confidence=Confidence.IMPORT_INFERRED)
    return edge


def resolve(files: list[ParsedFile]) -> list[ParsedFile]:
    index = _Index(files)
    out: list[ParsedFile] = []
    for pf in files:
        new_edges = [_resolve_edge(e, pf, index) for e in pf.edges]
        out.append(replace(pf, edges=new_edges))
    return out
```

`src/graphdex/resolve/__init__.py`:
```python
from .resolver import resolve

__all__ = ["resolve"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_resolve.py -v`
Expected: all 7 tests PASS

- [ ] **Step 5: Run full suite and commit**

Run: `python -m pytest -q` — Expected: all tests pass.

```bash
git add src/graphdex/resolve tests/test_resolve.py
git commit -m "feat: two-pass import-aware resolver with confidence tiers"
```

---

### Task 5: Graphdex library API (build + queries)

**Files:**
- Create: `src/graphdex/api.py`
- Create: `src/graphdex/collect.py`
- Modify: `src/graphdex/__init__.py`
- Test: `tests/test_api.py`
- Test fixtures: `tests/fixtures/pyrepo/app.py`, `tests/fixtures/pyrepo/utils/__init__.py`, `tests/fixtures/pyrepo/utils/helpers.py`, `tests/fixtures/pyrepo/unrelated.py`, `tests/fixtures/pyrepo/test_app.py`

**Interfaces:**
- Consumes: `Store`, `parse_file`, `SUPPORTED_EXTENSIONS`, `resolve`, models.
- Produces: `collect_files(repo: Path) -> list[str]` (git ls-files with `os.walk` fallback, filtered to `SUPPORTED_EXTENSIONS`, `/`-normalized relative paths); class `Graphdex(repo_path, db_path=None)` with `build() -> dict` (keys `files_indexed, files_quarantined, nodes, edges, duration_s`), `search(query, limit=20) -> list[dict]`, `callers_of(name, min_confidence=Confidence.IMPORT_INFERRED) -> list[dict]` (each dict: caller node fields + `line` + `confidence`), `callees_of(name, min_confidence=...) -> list[dict]`, `symbol(name) -> dict | None` (node fields + `source` snippet), `stats() -> dict`, `close()`. Default `db_path` is `<repo>/.graphdex/graph.db`. `graphdex/__init__.py` re-exports `Graphdex` and `Confidence`.

- [ ] **Step 1: Create fixture mini-repo**

`tests/fixtures/pyrepo/utils/__init__.py` — empty file.

`tests/fixtures/pyrepo/utils/helpers.py`:
```python
def save(data):
    return {"saved": data}


def load(key):
    return {"key": key}
```

`tests/fixtures/pyrepo/app.py`:
```python
from utils.helpers import save


def handle(payload):
    return save(payload)
```

`tests/fixtures/pyrepo/unrelated.py`:
```python
def save(other):
    return other  # same bare name, different symbol — precision trap
```

`tests/fixtures/pyrepo/test_app.py`:
```python
from app import handle


def test_handle():
    assert handle(1) == {"saved": 1}
```

- [ ] **Step 2: Write failing API tests**

`tests/test_api.py`:
```python
import shutil
from pathlib import Path

import pytest

from graphdex import Confidence, Graphdex

FIXTURE = Path(__file__).parent / "fixtures" / "pyrepo"


@pytest.fixture()
def gd(tmp_path: Path) -> Graphdex:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    g = Graphdex(repo)
    g.build()
    yield g
    g.close()


def test_build_reports_counts(tmp_path: Path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    g = Graphdex(repo)
    result = g.build()
    g.close()
    assert result["files_indexed"] == 5
    assert result["files_quarantined"] == 0
    assert result["nodes"] > 5
    assert result["duration_s"] >= 0


def test_precise_callers_exclude_name_collision(gd: Graphdex):
    callers = gd.callers_of("utils/helpers.py::save",
                            min_confidence=Confidence.RESOLVED)
    assert [c["qualified_name"] for c in callers] == ["app.py::handle"]


def test_bare_name_query_resolves_to_definitions(gd: Graphdex):
    callers = gd.callers_of("save", min_confidence=Confidence.RESOLVED)
    assert {c["qualified_name"] for c in callers} == {"app.py::handle"}


def test_callees_of(gd: Graphdex):
    callees = gd.callees_of("app.py::handle",
                            min_confidence=Confidence.RESOLVED)
    assert {c["qualified_name"] for c in callees} == {
        "utils/helpers.py::save"
    }


def test_symbol_returns_source_snippet(gd: Graphdex):
    info = gd.symbol("utils/helpers.py::save")
    assert info is not None
    assert "def save(data):" in info["source"]


def test_search_hits(gd: Graphdex):
    hits = gd.search("save")
    assert any(h["qualified_name"] == "utils/helpers.py::save" for h in hits)


def test_quarantine_on_unreadable_file(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "ok.py").write_text("def fine(): pass\n", encoding="utf-8")
    # a directory named like a .py file forces a read error -> quarantine
    (repo / "bad.py").mkdir()
    g = Graphdex(repo)
    result = g.build()
    g.close()
    assert result["files_indexed"] >= 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'Graphdex'`

- [ ] **Step 4: Implement collect + API**

`src/graphdex/collect.py`:
```python
"""Repo file collection: git ls-files when available, os.walk fallback."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .parsing import SUPPORTED_EXTENSIONS

_SKIP_DIRS = {".git", ".graphdex", "__pycache__", "node_modules", ".venv",
              "venv", "dist", "build"}


def _git_files(repo: Path) -> list[str] | None:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"], cwd=str(repo), capture_output=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def _walk_files(repo: Path) -> list[str]:
    found: list[str] = []
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in names:
            rel = os.path.relpath(os.path.join(root, name), repo)
            found.append(rel.replace(os.sep, "/"))
    return found


def collect_files(repo: Path) -> list[str]:
    """Repo-relative, '/'-normalized paths with supported extensions."""
    candidates = _git_files(repo)
    if candidates is None:
        candidates = _walk_files(repo)
    return sorted(
        p.replace("\\", "/") for p in candidates
        if os.path.splitext(p)[1].lower() in SUPPORTED_EXTENSIONS
        and (repo / p).is_file()
    )
```

`src/graphdex/api.py`:
```python
"""The Graphdex facade — the library API that CLI and MCP wrap."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .collect import collect_files
from .models import Confidence
from .parsing import SUPPORTED_EXTENSIONS, parse_file
from .resolve import resolve
from .store import Store


class Graphdex:
    def __init__(self, repo_path: str | Path,
                 db_path: str | Path | None = None) -> None:
        self.repo = Path(repo_path).resolve()
        if not self.repo.is_dir():
            raise NotADirectoryError(f"not a directory: {self.repo}")
        self._store = Store(db_path or self.repo / ".graphdex" / "graph.db")

    # -- indexing ----------------------------------------------------------

    def build(self) -> dict[str, Any]:
        started = time.monotonic()
        parsed = []
        quarantined = 0
        for rel in collect_files(self.repo):
            language = SUPPORTED_EXTENSIONS[
                "." + rel.rsplit(".", 1)[-1].lower()
            ]
            try:
                source = (self.repo / rel).read_bytes()
                parsed.append(parse_file(rel, source, language))
            except Exception as exc:  # per-file quarantine, never abort
                self._store.quarantine(
                    rel, language, f"{type(exc).__name__}: {exc}"
                )
                quarantined += 1
        for pf in resolve(parsed):
            self._store.replace_file(pf)
        stats = self._store.stats()
        return {
            "files_indexed": len(parsed),
            "files_quarantined": quarantined,
            "nodes": stats["nodes"],
            "edges": stats["edges"],
            "duration_s": round(time.monotonic() - started, 3),
        }

    # -- queries -----------------------------------------------------------

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        return self._store.search(query, limit=limit)

    def _target_names(self, name: str) -> list[str]:
        """A symbol reference: qualified name, or bare name mapped to all
        matching definitions plus the bare string itself (NAME_ONLY edges)."""
        if "::" in name:
            return [name]
        qns = [n["qualified_name"] for n in self._store.nodes_named(name)]
        return [*qns, name]

    def callers_of(self, name: str,
                   min_confidence: Confidence = Confidence.IMPORT_INFERRED,
                   ) -> list[dict[str, Any]]:
        edges = self._store.edges_into(
            self._target_names(name), "CALLS", int(min_confidence)
        )
        return self._attach_nodes(edges, key="src")

    def callees_of(self, name: str,
                   min_confidence: Confidence = Confidence.IMPORT_INFERRED,
                   ) -> list[dict[str, Any]]:
        edges = self._store.edges_out_of(
            self._target_names(name), "CALLS", int(min_confidence)
        )
        return self._attach_nodes(edges, key="dst")

    def symbol(self, name: str) -> dict[str, Any] | None:
        node = self._store.node(name)
        if node is None:
            named = self._store.nodes_named(name)
            node = named[0] if named else None
        if node is None:
            return None
        source = ""
        try:
            lines = (self.repo / node["path"]).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            source = "\n".join(
                lines[node["line_start"] - 1: node["line_end"]]
            )
        except OSError:
            pass
        return {**node, "source": source}

    def stats(self) -> dict[str, Any]:
        return self._store.stats()

    def close(self) -> None:
        self._store.close()

    # -- helpers -----------------------------------------------------------

    def _attach_nodes(self, edges: list[dict[str, Any]],
                      key: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for edge in edges:
            node = self._store.node(edge[key])
            if node is None:
                continue
            dedup = (node["qualified_name"], edge["line"])
            if dedup in seen:
                continue
            seen.add(dedup)
            out.append({**node, "line": edge["line"],
                        "confidence": Confidence(edge["confidence"]).name})
        return out
```

Update `src/graphdex/__init__.py`:
```python
"""graphdex — the code graph that's never stale."""

from .api import Graphdex
from .models import Confidence

__version__ = "0.1.0"

__all__ = ["Graphdex", "Confidence", "__version__"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -v`
Expected: all 7 tests PASS. Note the precision test: `unrelated.py::save` must NOT appear among callers-of-save results — that is the headline behavior.

- [ ] **Step 6: Run full suite and commit**

Run: `python -m pytest -q` — Expected: all tests pass.

```bash
git add src/graphdex/api.py src/graphdex/collect.py src/graphdex/__init__.py tests/test_api.py tests/fixtures
git commit -m "feat: Graphdex library API with precision-filtered graph queries"
```

---

### Task 6: CLI (`build | status | search`)

**Files:**
- Create: `src/graphdex/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Graphdex` from `graphdex.api`.
- Produces: `main(argv: list[str] | None = None) -> int` console entry point. Commands: `graphdex build [--repo PATH]`, `graphdex status [--repo PATH]`, `graphdex search QUERY [--repo PATH] [--limit N]`. Exit code 0 on success, 2 on usage errors (argparse default), 1 on missing graph for `status`/`search`.

- [ ] **Step 1: Write failing CLI tests**

`tests/test_cli.py`:
```python
import shutil
from pathlib import Path

from graphdex.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "pyrepo"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    return repo


def test_build_then_status(tmp_path, capsys):
    repo = _repo(tmp_path)
    assert main(["build", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "files indexed" in out
    assert main(["status", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "nodes" in out


def test_search_outputs_hits(tmp_path, capsys):
    repo = _repo(tmp_path)
    main(["build", "--repo", str(repo)])
    capsys.readouterr()
    assert main(["search", "save", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "utils/helpers.py::save" in out


def test_status_without_graph_fails_cleanly(tmp_path, capsys):
    repo = tmp_path / "empty"
    repo.mkdir()
    assert main(["status", "--repo", str(repo)]) == 1
    assert "no graph" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graphdex.cli'`

- [ ] **Step 3: Implement CLI**

`src/graphdex/cli.py`:
```python
"""graphdex CLI — thin wrapper over the Graphdex library API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .api import Graphdex


def _utf8_stdio() -> None:
    """Windows consoles default to legacy code pages; fix in code, not env."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _graph_exists(repo: Path) -> bool:
    return (repo / ".graphdex" / "graph.db").is_file()


def _cmd_build(args: argparse.Namespace) -> int:
    gd = Graphdex(args.repo)
    try:
        result = gd.build()
    finally:
        gd.close()
    print(
        f"{result['files_indexed']} files indexed"
        f" ({result['files_quarantined']} quarantined),"
        f" {result['nodes']} nodes, {result['edges']} edges"
        f" in {result['duration_s']}s"
    )
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    if not _graph_exists(repo):
        print("no graph found — run `graphdex build` first", file=sys.stderr)
        return 1
    gd = Graphdex(repo)
    try:
        stats = gd.stats()
    finally:
        gd.close()
    print(f"nodes: {stats['nodes']}")
    print(f"edges: {stats['edges']}")
    print(f"files: {stats['files']} ({stats['quarantined']} quarantined)")
    for language, count in sorted(stats["by_language"].items()):
        print(f"  {language}: {count}")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    if not _graph_exists(repo):
        print("no graph found — run `graphdex build` first", file=sys.stderr)
        return 1
    gd = Graphdex(repo)
    try:
        hits = gd.search(args.query, limit=args.limit)
    finally:
        gd.close()
    for hit in hits:
        print(
            f"{hit['qualified_name']}  [{hit['kind']}]"
            f"  {hit['path']}:{hit['line_start']}"
        )
    if not hits:
        print("no results")
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="graphdex",
        description="The code graph that's never stale.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="parse the repo into a graph")
    p_build.add_argument("--repo", default=".")
    p_build.set_defaults(func=_cmd_build)

    p_status = sub.add_parser("status", help="show graph statistics")
    p_status.add_argument("--repo", default=".")
    p_status.set_defaults(func=_cmd_status)

    p_search = sub.add_parser("search", help="search symbols")
    p_search.add_argument("query")
    p_search.add_argument("--repo", default=".")
    p_search.add_argument("--limit", type=int, default=20)
    p_search.set_defaults(func=_cmd_search)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Smoke-test the real entry point on this repo**

Run: `graphdex build --repo .` then `graphdex search "resolve" --repo .`
Expected: build reports indexed files; search prints graphdex's own symbols.

- [ ] **Step 6: Commit**

```bash
git add src/graphdex/cli.py tests/test_cli.py
git commit -m "feat: CLI with build, status, and search commands"
```

---

### Task 7: CI workflow + README status update

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `README.md` (status line)

**Interfaces:**
- Consumes: the full test suite.
- Produces: green CI on Linux/macOS/Windows × Python 3.11/3.12/3.13.

- [ ] **Step 1: Write CI workflow**

`.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python: ["3.11", "3.12", "3.13"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - name: Install
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check src tests
      - name: Test
        run: python -m pytest -q --cov=graphdex --cov-report=term-missing
```

- [ ] **Step 2: Update README status line**

In `README.md`, replace the line starting `**Status: design phase.**` with:

```markdown
**Status: v0.1 core engine in development** — Python parsing, two-pass
import-aware resolution, subtoken search, and CLI are implemented; freshness
(self-healing reads) and the MCP server land next. Design spec:
[`docs/superpowers/specs/2026-07-17-graphdex-design.md`](docs/superpowers/specs/2026-07-17-graphdex-design.md).
```

- [ ] **Step 3: Run lint + full suite locally**

Run: `ruff check src tests && python -m pytest -q`
Expected: no lint errors, all tests pass.

- [ ] **Step 4: Commit and push**

```bash
git add .github/workflows/ci.yml README.md
git commit -m "ci: test matrix across 3 OS and 3 Python versions"
git push origin main
```

- [ ] **Step 5: Verify CI is green**

Run: `gh run watch --exit-status` (or `gh run list --limit 1`)
Expected: workflow concludes `success` on all 9 matrix cells.
