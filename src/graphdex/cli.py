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
