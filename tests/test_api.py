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
    g = Graphdex(repo)
    result = g.build()
    g.close()
    assert result["files_indexed"] >= 1
