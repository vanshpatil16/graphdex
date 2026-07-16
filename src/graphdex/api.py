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
