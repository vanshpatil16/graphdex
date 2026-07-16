# graphdex — Design Spec

- **Date:** 2026-07-17
- **Status:** Approved (pending user review of this document)
- **Repo:** `vanshpatil16/graphdex` (public, MIT)
- **Package:** `graphdex` on PyPI (name verified free on 2026-07-17)

## Summary

graphdex is a Python library + CLI + MCP server that maintains an always-correct
structural code graph (functions, classes, imports, calls, tests) and serves
token-budgeted, confidence-labeled context to AI coding agents.

Tagline: **"the code graph that's never stale."**

## Background and motivation

We analyzed [code-review-graph](https://github.com/tirth8205/code-review-graph)
(MIT) and found four load-bearing weaknesses for agent/IDE use:

1. **Imprecise cross-file call resolution.** Call targets are qualified only
   against same-file definitions; cross-file callers are matched by bare name
   at query time, conflating unrelated symbols named `run`, `get`, `init`, etc.
2. **No freshness contract.** Query tools answer from the stored graph with no
   indication of whether it reflects the working tree. Correctness depends on
   hooks/watchers/daemons staying alive; when they die, agents silently get
   wrong answers.
3. **30 MCP tools.** Most agent harnesses serialize every tool schema into
   every request — thousands of tokens of overhead per turn before any query.
4. **Search indexes only names/signatures** (self-reported MRR 0.35), with no
   subtoken splitting, and embeddings silently rot after incremental updates.

graphdex is a clean-room implementation (no code copied; credit given in the
README) that fixes all four by design.

## Decisions log

| Decision | Choice | Alternatives considered |
|---|---|---|
| Name | `graphdex` | repolens, blastgraph, aria-graph, codenexus, code-atlas |
| Stack | Python 3.11+ | TypeScript/Node, Rust core + Python bindings |
| Visibility | Public from day one, MIT | Private until v0.1 |
| v1 scope | Lean, agent-first core | Feature parity + fixes; thin spike |
| Architecture | **B: Self-healing reads** | A: build + watchers (CRG model); C: LSP-backed |

**Why Approach B:** every query dirty-checks the working tree and repairs the
graph inline before answering. Correctness never depends on a background
process. Watchers become an optional optimization, never a correctness
requirement. This is the headline differentiator.

## Product definition

One PyPI package exposing three surfaces over a single core:

1. **Library API** (`graphdex.Graphdex`) — the primary artifact ("turn into a
   library"). CLI and MCP are thin wrappers over it.
2. **CLI** (`graphdex build | status | search | impact | serve`).
3. **MCP server** (`graphdex serve`, stdio; `uvx graphdex serve` must work).

## v1 language set

Six languages done excellently, not 35 done shallowly:

**Python, TypeScript, JavaScript (+JSX/TSX), Go, Rust, Java.**

Each language is its own parser module (~300 lines) over a shared tree-sitter
walker (`tree-sitter-language-pack` bindings). A `languages.toml` plugin
mechanism for user-added grammars is planned for v1.x, not v1.0.

## Architecture

`src/` layout. Small, focused modules (≤400 lines typical, 800 max).

### `graphdex/parsing/`
- Shared tree-sitter walker + one module per language.
- Extracts nodes (File, Class, Function, Test) and raw edges (CALLS,
  IMPORTS_FROM, INHERITS, CONTAINS, TESTED_BY) with byte-exact line spans.
- Per-file failure quarantine: a file that fails to parse is recorded in a
  `quarantine` table with the error; the build never aborts.

### `graphdex/resolve/`
Two-pass resolution — the precision fix:
- **Pass 1 (file-local):** same-file symbol table qualifies local calls.
- **Pass 2 (project-wide, import-aware):** a call to a name imported from
  module X resolves to X's definition via the import graph.
- Every edge carries a confidence tier:
  - `RESOLVED` — file-local or import-path-proven target.
  - `IMPORT_INFERRED` — resolved through re-exports/aliases with one
    plausible target.
  - `NAME_ONLY` — bare-name match (kept for recall, always labeled).
- All query surfaces accept `min_confidence` (default `IMPORT_INFERRED`).

### `graphdex/store/`
- SQLite in `.graphdex/graph.db`, WAL mode, versioned schema with migrations.
- Per-file content-hash table for dirty detection.
- FTS5 index maintained **by triggers** (insert/update/delete sync — never a
  full drop/rebuild).
- Subtoken indexing: identifiers are split on camelCase/snake_case at index
  time (`getUserById` → `get user by id`) so natural-language queries hit.

### `graphdex/freshness/`
The self-healing core:
1. On every query: `git status --porcelain` (fallback: mtime scan for
   non-git dirs) + content-hash compare → dirty file set (~10 ms typical).
2. Dirty files re-parsed and re-resolved inline under a time budget
   (default 2 s, configurable via `GRAPHDEX_REPAIR_BUDGET`).
3. Every response includes:
   ```json
   "freshness": {
     "state": "fresh" | "repaired" | "stale",
     "dirty_files": 0,
     "repaired_files": 3,
     "built_at": "2026-07-17T12:00:00Z"
   }
   ```
4. Budget exceeded → answer from the stale graph, `state: "stale"` with the
   remaining dirty count. Never silently wrong; stale is always labeled.

### `graphdex/api/`
- `Graphdex(repo_path)` facade: `build()`, `search(q)`, `symbol(name)`,
  `callers_of(name)`, `callees_of(name)`, `tests_for(name)`,
  `impact(files)`, `review_context(base_ref)`, `stats()`.
- Returns plain dataclasses; no MCP/CLI types leak into the library API.

### `graphdex/mcp/`
**8 tools, not 30** (FastMCP, stdio transport):

| Tool | Purpose |
|---|---|
| `index` | Build or repair the graph; returns stats + freshness |
| `search` | Hybrid FTS5 subtoken search; returns ranked symbols + snippets |
| `symbol` | One symbol: definition, signature, source snippet, spans |
| `relations` | callers / callees / tests / imports / inheritance for a symbol |
| `impact` | Blast radius of changed files (confidence-filtered) |
| `review_context` | Diff-scoped review bundle: changed symbols, impact, test gaps |
| `stats` | Graph size, language breakdown, quarantine report |
| `configure` | Set per-session defaults (token_budget, min_confidence) |

Every tool accepts `token_budget` (default 2000) and returns source snippets
inline (assembled within budget, most-relevant first) so agents skip the
follow-up file-read round trip.

### `graphdex/cli.py`
`graphdex build | status | search | impact | serve` — thin wrappers over
`api/`. `NO_COLOR` respected. Windows UTF-8 handled in code (never requires
user-side `PYTHONUTF8` workarounds).

## Data flow

- **Build:** collect files (`git ls-files` + ignore file) → parse (parallel) →
  resolve (2 passes) → store (single transaction) → FTS via triggers.
- **Query:** dirty-check → inline repair (budgeted) → SQL traversal →
  snippet assembly within token budget → JSON with freshness + confidence.

## Error handling

- Parse failure → quarantine with reason, build continues.
- Repair budget exceeded → honest `stale` response, never an error.
- Git absent → mtime-based dirty detection fallback.
- DB schema mismatch → auto-migrate forward; refuse (with clear message) to
  open a newer-schema DB with an older graphdex.
- All user input (paths, symbol names, queries) validated at API boundary;
  SQL always parameterized.

## Testing

- pytest; fixture mini-repos per language under `tests/fixtures/<lang>/`.
- **Golden-file resolution tests:** exact expected edge sets (with confidence
  tiers) per fixture; any precision regression fails CI.
- Freshness tests: mutate fixture file → query → assert `repaired` state and
  correct post-edit answer.
- Benchmark harness (`benchmarks/`): resolution precision vs a bare-name
  baseline; token cost per tool response. Numbers published honestly in the
  README (no whole-corpus strawman baselines).
- CI: GitHub Actions matrix — Linux, macOS, **Windows** — Python 3.11/3.12/3.13.
- Coverage target: 80%+.

## Packaging

- hatchling build; `[project.scripts] graphdex = graphdex.cli:main`.
- Runtime deps kept minimal: `tree-sitter`, `tree-sitter-language-pack`,
  `fastmcp`. Everything else stdlib.
- Publish to PyPI on tagged release via GitHub Actions (trusted publishing).

## Non-goals for v1 (explicit YAGNI — v2 candidates)

Execution flows, community detection, wiki generation, daemons/watchers,
embeddings/vector search, VS Code extension, GitHub Action, multi-repo
registry, LSP enrichment (Approach C — designed to slot into `resolve/` as an
optional enricher later).

## Success criteria

1. Cross-file resolution precision beats bare-name matching on the golden
   fixtures (measured, in CI).
2. Every MCP response respects its `token_budget` and carries `freshness` +
   confidence metadata.
3. Correct answers with **zero** background processes: edit a file, query
   immediately, get the post-edit truth (repair path).
4. Build ≤10 s on a 500-file repo; typical inline repair ≤2 s.
5. `pip install graphdex && graphdex build && graphdex serve` works on
   Windows, macOS, Linux with no extra configuration.

## Risks

- **tree-sitter grammar drift** — pin `tree-sitter-language-pack` minor
  version; golden tests catch extraction changes.
- **Import resolution complexity varies by language** (TS path aliases, Go
  modules, Rust `use` trees) — per-language resolver helpers behind one
  interface; ship Python + TS first-class, iterate on the rest before v1.0.
- **Repair latency on huge diffs** (rebase of 500 files) — budget + honest
  `stale` labeling is the designed mitigation; `graphdex build` catches up.
