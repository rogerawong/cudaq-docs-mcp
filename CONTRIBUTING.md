# Contributing

Thanks for your interest. This is a small project with a small surface: five tools, two runtime dependencies (`mcp`, `httpx`), and the standard library for everything else. Keeping it that way is a feature.

## Development setup

```bash
python3 -m venv .venv          # Python 3.10 or newer
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Tests run offline by design. Network-dependent behavior (index building, asset download) is exercised manually:

```bash
.venv/bin/cudaq-docs-mcp build --limit 25   # small smoke build
.venv/bin/python scripts/smoke_mcp.py       # end-to-end MCP session
```

## Sign your commits (DCO)

Every commit needs a Developer Certificate of Origin sign-off, the same convention the upstream CUDA-Q repository uses:

```bash
git commit -s -m "Describe the change"
```

The `-s` flag adds a `Signed-off-by` line certifying you have the right to contribute the change under the project license.

## Ground rules

- Open an issue before a feature PR, so the approach gets discussed first.
- No new runtime dependencies without discussion.
- Docs claims follow the docs: if a target name, option, or URL changes upstream, cite the page you verified it against.
