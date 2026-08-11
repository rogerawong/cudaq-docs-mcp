# cudaq-docs-mcp

MCP server serving NVIDIA CUDA-Q docs to agents, version-pinned to the installed cudaq package.

## Commands

```bash
.venv/bin/pytest                                  # unit tests, offline
.venv/bin/cudaq-docs-mcp build --limit 25         # smoke index build (network)
.venv/bin/cudaq-docs-mcp build --version latest   # full index build
.venv/bin/cudaq-docs-mcp info                     # cache dir, indexed versions
.venv/bin/python scripts/smoke_mcp.py             # end-to-end MCP stdio session
```

Commands assume the repo venv at `.venv`. Where the package is installed into a different environment (a codespace, for example), drop the prefix and call `cudaq-docs-mcp`, `pytest`, and `python` from that environment directly.

## Architecture

Pipeline: `inventory.py` parses CUDA-Q's Sphinx `objects.inv` (crawl manifest + API symbols) → `ingest.py` fetches the site's .md mirrors and repo example files → `clean.py` strips RTD theme chrome from the pandoc-converted mirrors, rebuilds fenced code blocks, extracts heading anchors, chunks by heading → `db.py` stores pages/chunks/api/examples in one SQLite file per docs version with FTS5 (porter, bm25). `server.py` exposes five tools + two resources on MCP SDK v2's `MCPServer`; `detect.py` resolves the default docs version from installed cudaq distribution metadata; `targets.py` + `data/targets.json` is the hand-curated backend matrix; `assets.py` downloads prebuilt indexes from GitHub release assets; `cli.py` wires serve/build/info.

## Constraints

- Runtime deps are exactly `mcp` and `httpx`; everything else is stdlib. Do not add deps casually.
- Tests must stay offline; network behavior is exercised through the manual commands above.
- Version resolution order (explicit arg → installed cudaq → latest) is the product thesis; do not change it silently.
- `data/targets.json` is curated from the docs by hand; when editing, verify names against the backends pages and update `docs_reviewed`.
- Repo prose (README, CONTRIBUTING) follows the maintainer's style: no em dashes, "via" is banned, Oxford comma, AP-style numbers.
