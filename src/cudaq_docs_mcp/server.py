"""The MCP server: five tools and two resources over the docs index."""

from __future__ import annotations

import json
import os
import re
import sqlite3

from mcp.server.mcpserver import MCPServer

from . import __version__, assets
from . import db as dbmod
from .detect import installed_cudaq_version
from .targets import load_targets

INSTRUCTIONS = """\
Authoritative NVIDIA CUDA-Q documentation, version-pinned to the user's
installed cudaq package. CUDA-Q's API moves quickly, so consult these tools
before answering CUDA-Q questions from memory. search_docs finds relevant
documentation; get_page fetches a whole page; find_api resolves exact Python
and C++ symbols; search_examples returns complete runnable programs;
list_targets explains which simulator or hardware backend fits a task.
Results carry canonical doc URLs suitable for citation.\
"""

mcp = MCPServer(name="cudaq-docs", instructions=INSTRUCTIONS, version=__version__)

_DOMAIN = {"python": "py", "cpp": "cpp", "c++": "cpp"}
_PAGE_CAP = 60_000
_EXAMPLE_CAP = 6_000


def _resolve_version(version: str | None) -> tuple[str, str | None]:
    if version:
        return version, None
    installed = installed_cudaq_version()
    if installed:
        return installed, f"cudaq {installed} detected; serving matching docs"
    return "latest", "no cudaq installation detected; serving latest docs"


def _open(version: str | None) -> tuple[sqlite3.Connection, str, str | None]:
    ver, note = _resolve_version(version)
    path = dbmod.index_path(ver)
    if not path.exists():
        assets.try_download(ver)
    if not path.exists() and os.environ.get("CUDAQ_DOCS_MCP_AUTOBUILD") == "1":
        from .ingest import build_index_sync

        build_index_sync(version=ver)
    if not path.exists() and ver != "latest":
        alt = dbmod.index_path("latest")
        if not alt.exists():
            assets.try_download("latest")
        if alt.exists():
            extra = (
                f"no index for cudaq {ver}; serving 'latest' docs instead. "
                f"Run `cudaq-docs-mcp build --version {ver}` for pinned answers"
            )
            note = f"{note}; {extra}" if note else extra
            ver, path = "latest", alt
    if not path.exists():
        raise RuntimeError(
            f"No docs index available for '{ver}'. Run `cudaq-docs-mcp build "
            f"--version {ver}` once (about a minute), or set "
            f"CUDAQ_DOCS_MCP_AUTOBUILD=1 to build on first use."
        )
    return dbmod.connect(path), ver, note


def _payload(version: str, note: str | None, **fields) -> dict:
    out: dict = {"version": version}
    if note:
        out["note"] = note
    out.update(fields)
    return out


@mcp.tool()
def search_docs(query: str, version: str | None = None, limit: int = 5) -> dict:
    """Search the NVIDIA CUDA-Q documentation and return ranked excerpts.

    Use this before answering any CUDA-Q question from memory: the platform
    moves quickly and memorized APIs are often stale. Each result carries a
    breadcrumb, an excerpt, and the canonical doc URL to cite.

    Args:
        query: Natural language or keywords, for example "run kernel on GPU
            state vector" or "quantinuum credentials".
        version: Docs version such as "0.15.0" or "latest". Defaults to the
            installed cudaq version.
        limit: Maximum number of results (default 5).
    """
    conn, ver, note = _open(version)
    try:
        results = dbmod.search_chunks(conn, query, limit=max(1, min(limit, 20)))
    finally:
        conn.close()
    return _payload(ver, note, results=results)


@mcp.tool()
def get_page(path: str, version: str | None = None) -> dict:
    """Fetch one documentation page as clean markdown.

    Args:
        path: Page path as returned by search_docs, for example
            "using/quick_start" or "using/backends/sims/svsims".
        version: Docs version. Defaults to the installed cudaq version.
    """
    conn, ver, note = _open(version)
    try:
        page = dbmod.get_page(conn, path)
    finally:
        conn.close()
    if page is None:
        return _payload(ver, note, error=f"no page matches '{path}'")
    md = page["markdown"]
    truncated = len(md) > _PAGE_CAP
    if truncated:
        outline = re.findall(r"^#{1,3} .+$", md, flags=re.M)
        md = md[:_PAGE_CAP]
        return _payload(
            ver,
            note,
            path=page["path"],
            title=page["title"],
            url=page["url"],
            truncated=True,
            outline=outline,
            markdown=md,
        )
    return _payload(
        ver, note, path=page["path"], title=page["title"], url=page["url"], markdown=md
    )


@mcp.tool()
def find_api(name: str, language: str | None = None, version: str | None = None) -> dict:
    """Resolve a CUDA-Q API symbol to its canonical definition and doc URL.

    Args:
        name: Symbol name, full or partial: "sample", "cudaq.observe",
            "qvector", "set_target".
        language: "python" or "cpp" to filter; omit for both.
        version: Docs version. Defaults to the installed cudaq version.
    """
    domain = _DOMAIN.get(language.lower()) if language else None
    conn, ver, note = _open(version)
    try:
        rows = dbmod.find_api(conn, name, domain=domain)
        base = f"{dbmod.BASE_URL}/{ver}"
        matches = [
            {
                "name": r["name"],
                "kind": f"{r['domain']}:{r['role']}",
                "url": f"{base}/{r['uri']}",
            }
            for r in rows
        ]
        excerpt = None
        if rows:
            top = rows[0]
            page_path = top["uri"].split("#")[0].removesuffix(".html")
            tail = top["name"].split(".")[-1].split("::")[-1]
            row = conn.execute(
                "SELECT c.content FROM chunks c JOIN pages p ON p.id = c.page_id "
                "WHERE p.path = ? AND c.content LIKE ? LIMIT 1",
                (page_path, f"%{tail}%"),
            ).fetchone()
            if row:
                excerpt = row["content"][:2000]
    finally:
        conn.close()
    if not matches:
        return _payload(ver, note, matches=[], hint="try a shorter or partial name")
    return _payload(ver, note, matches=matches, excerpt=excerpt)


@mcp.tool()
def search_examples(
    query: str,
    language: str | None = None,
    version: str | None = None,
    limit: int = 3,
) -> dict:
    """Find complete, runnable CUDA-Q example programs.

    Sources are the example, snippet, and application files shipped in the
    CUDA-Q repository at the matching release. Prefer adapting these over
    writing kernels from memory.

    Args:
        query: What the example should show, for example "GHZ state",
            "VQE", or "noise model".
        language: "python" or "cpp" to filter; omit for both.
        version: Docs version. Defaults to the installed cudaq version.
        limit: Maximum number of examples (default 3).
    """
    lang = None
    if language:
        lang = {"python": "python", "cpp": "cpp", "c++": "cpp"}.get(language.lower())
    conn, ver, note = _open(version)
    try:
        rows = dbmod.search_examples(conn, query, language=lang, limit=max(1, min(limit, 10)))
    finally:
        conn.close()
    results = []
    for r in rows:
        content = r["content"]
        entry = {
            "path": r["path"],
            "language": r["language"],
            "url": r["url"],
            "content": content[:_EXAMPLE_CAP],
        }
        if len(content) > _EXAMPLE_CAP:
            entry["truncated"] = True
        results.append(entry)
    return _payload(ver, note, results=results)


@mcp.tool()
def list_targets(category: str | None = None) -> dict:
    """List CUDA-Q execution targets (backends) with guidance on choosing.

    Covers simulators (CPU, GPU state vector, tensor network, noisy,
    dynamics), quantum hardware providers, and cloud aggregators, each with
    selection snippets and doc URLs. Call this when deciding where to run a
    kernel or when the user names a provider.

    Args:
        category: Optional filter: "simulator", "hardware", or "cloud".
    """
    data = load_targets()
    targets = data["targets"]
    if category:
        targets = [t for t in targets if t["category"] == category.lower()]
    return {
        "how_to_choose": data["how_to_choose"],
        "docs_reviewed": data["docs_reviewed"],
        "targets": targets,
    }


@mcp.resource("cudaq://versions")
def versions_resource() -> str:
    """Installed cudaq version, indexed docs versions, and the default."""
    default, note = _resolve_version(None)
    return json.dumps(
        {
            "server": __version__,
            "installed_cudaq": installed_cudaq_version(),
            "default_docs_version": default,
            "note": note,
            "indexed_versions": dbmod.indexed_versions(),
            "docs_site": dbmod.BASE_URL,
        },
        indent=2,
    )


@mcp.resource("cudaq://llms.txt")
def llms_resource() -> str:
    """The llms.txt published with the default docs version."""
    try:
        conn, _, _ = _open(None)
    except RuntimeError as exc:
        return f"(no index available: {exc})"
    try:
        return dbmod.get_meta(conn).get("llms_txt", "")
    finally:
        conn.close()


def run() -> None:
    mcp.run()
