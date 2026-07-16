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
