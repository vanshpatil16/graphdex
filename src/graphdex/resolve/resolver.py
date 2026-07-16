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
