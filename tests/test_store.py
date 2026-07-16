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
