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
