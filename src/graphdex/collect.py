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
