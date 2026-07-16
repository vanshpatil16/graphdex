# graphdex

> **The code graph that's never stale.**

A Python library + CLI + MCP server that maintains an always-correct structural
code graph (functions, classes, imports, calls, tests) and serves
token-budgeted, confidence-labeled context to AI coding agents.

**Status: v0.1 core engine in development** — Python parsing, two-pass
import-aware resolution, subtoken search, and CLI are implemented; freshness
(self-healing reads) and the MCP server land next. Design spec:
[`docs/superpowers/specs/2026-07-17-graphdex-design.md`](docs/superpowers/specs/2026-07-17-graphdex-design.md).

## Why graphdex

Code-graph tools for AI agents share four recurring weaknesses:

| Problem elsewhere | graphdex answer |
|---|---|
| Stale graphs served as fresh when watchers die | **Self-healing reads** — every query dirty-checks the working tree and repairs the graph inline; every response carries a `freshness` field |
| Cross-file calls matched by bare name (false blast radii) | **Import-aware two-pass resolution** with per-edge confidence tiers (`RESOLVED` / `IMPORT_INFERRED` / `NAME_ONLY`) and `min_confidence` filtering |
| 30 MCP tools taxing every agent request | **8 consolidated tools** that return source snippets inline within a `token_budget` |
| Search that only sees exact identifier names | **Subtoken FTS5 indexing** — `getUserById` matches "user by id" |

## Planned surfaces (v1)

- **Library:** `from graphdex import Graphdex; gd = Graphdex("."); gd.callers_of("login")`
- **CLI:** `graphdex build | status | search | impact | serve`
- **MCP:** `graphdex serve` (stdio) — works with Claude Code, Cursor, Codex, and any MCP client

v1 languages: Python, TypeScript, JavaScript (+JSX/TSX), Go, Rust, Java.

## Credits

Clean-room implementation inspired by the excellent
[code-review-graph](https://github.com/tirth8205/code-review-graph) (MIT) —
our [analysis of its trade-offs](docs/superpowers/specs/2026-07-17-graphdex-design.md#background-and-motivation)
shaped this design. No code is copied from it.

## License

[MIT](LICENSE)
