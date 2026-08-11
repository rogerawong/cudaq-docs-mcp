# cudaq-docs-mcp

An MCP server that serves NVIDIA [CUDA-Q](https://github.com/NVIDIA/cuda-quantum) documentation, API reference, and runnable examples to AI agents: version-pinned to the cudaq you actually have installed.

Community project, not affiliated with or endorsed by NVIDIA. CUDA-Q is a trademark of NVIDIA Corporation.

## Why

Quantum SDKs move faster than model training data. Ask an AI assistant to write CUDA-Q code and it answers from whatever it memorized: renamed APIs, retired target names, install steps for a version you do not run. The failure is version skew, and it lands where onboarding matters most: the first ten minutes.

This server gives any MCP-capable agent the current answer instead. Documentation search, exact API symbol resolution, complete runnable examples, and a backend-selection guide, all served from an index of the docs that match your installed cudaq package. No API keys and no embeddings: SQLite full-text search with BM25 ranking, on your machine, offline once the index exists.

## Quick start

One-time index build (about a minute; prebuilt downloads are on the roadmap):

```bash
uvx cudaq-docs-mcp build
```

Then register the server with your client.

**Claude Code**

```bash
claude mcp add cudaq-docs -- uvx cudaq-docs-mcp
```

**Claude Desktop** (`claude_desktop_config.json`), **Cursor** (`.cursor/mcp.json`), or any client that takes a JSON server map:

```json
{
  "mcpServers": {
    "cudaq-docs": {
      "command": "uvx",
      "args": ["cudaq-docs-mcp"]
    }
  }
}
```

**VS Code** (`.vscode/mcp.json`):

```json
{
  "servers": {
    "cudaq-docs": {
      "type": "stdio",
      "command": "uvx",
      "args": ["cudaq-docs-mcp"]
    }
  }
}
```

Prefer pip? `pip install cudaq-docs-mcp` and use `cudaq-docs-mcp` as the command.

## Tools

| Tool | What it returns |
| --- | --- |
| `search_docs(query, version?, limit?)` | Ranked doc excerpts with breadcrumbs and canonical URLs |
| `get_page(path, version?)` | One full documentation page as clean markdown |
| `find_api(name, language?, version?)` | Exact Python or C++ symbol, kind, doc URL, and an excerpt |
| `search_examples(query, language?, version?, limit?)` | Complete runnable programs from the CUDA-Q repository at the matching release |
| `list_targets(category?)` | All 24 execution targets: simulators, hardware providers, and clouds, with selection snippets and when-to-use guidance |

Resources: `cudaq://versions` (installed and indexed versions) and `cudaq://llms.txt` (CUDA-Q's own llms.txt for the served version).

## Version-pinned answers

Every tool resolves its docs version in this order:

1. An explicit `version` argument ("0.15.0", "latest")
2. The installed cudaq package, detected from distribution metadata (cudaq is never imported)
3. `latest`

Indexes are per-version. When a pinned index is missing the server says so in the response and serves `latest` instead, with the one command that fixes it. Skew becomes visible instead of silent.

## How it works

CUDA-Q publishes the raw material: a Sphinx inventory (`objects.inv`) listing every page and API symbol, markdown mirrors of each docs page, a per-version `llms.txt`, and example sources in the repository. This server builds on that groundwork:

- `objects.inv` is the crawl manifest and the API symbol table: no scraping heuristics
- each markdown mirror is cleaned of theme chrome, code blocks are rebuilt with their language, and heading anchors are preserved for deep links
- pages are chunked by heading and indexed in SQLite FTS5 (porter stemming, BM25 ranking)
- examples, snippets, and application sources are fetched from the GitHub release tag that matches the docs version

The whole index is one SQLite file per version in your cache directory (`cudaq-docs-mcp info` shows where). A nightly workflow rebuilds the `latest` index so refreshes stay a download, not a build.

## CLI

```bash
cudaq-docs-mcp            # serve MCP on stdio (what clients run)
cudaq-docs-mcp build      # build the index for your installed cudaq, else latest
cudaq-docs-mcp build --version 0.15.0
cudaq-docs-mcp info       # cache location, indexed versions, detected cudaq
```

Set `CUDAQ_DOCS_MCP_AUTOBUILD=1` to build automatically on first use, and `CUDAQ_DOCS_MCP_CACHE` to relocate the cache.

## Roadmap

- Prebuilt indexes as release assets, so first run is a download instead of a build
- An eval set of real developer questions, with published retrieval scores
- CUDA-QX library docs

## Contributing

Issues and PRs are welcome. Commits need a DCO sign-off (`git commit -s`); see [CONTRIBUTING.md](CONTRIBUTING.md). Built in the open with Claude Code.

## License

[Apache-2.0](LICENSE). Documentation content belongs to NVIDIA Corporation & Affiliates, originates from the Apache-2.0 licensed [NVIDIA/cuda-quantum](https://github.com/NVIDIA/cuda-quantum) repository, and every served result links back to the canonical page. See [NOTICE](NOTICE).
