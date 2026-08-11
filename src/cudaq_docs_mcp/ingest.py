"""Build a searchable index for one CUDA-Q docs version.

Sources, all published by the CUDA-Q project itself:
- objects.inv: the Sphinx inventory, used as both crawl manifest and API
  symbol table
- the .md mirror of every docs page (cleaned by clean.py)
- llms.txt for the version
- example sources (docs/sphinx/examples, snippets, applications, targets)
  fetched from the matching release tag on GitHub
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Callable

import httpx

from . import db as dbmod
from .clean import chunk_doc, clean_page
from .inventory import InvEntry, api_symbols, doc_pages, parse_objects_inv

BASE = dbmod.BASE_URL
GH_API = "https://api.github.com"
GH_RAW = "https://raw.githubusercontent.com/NVIDIA/cuda-quantum"
EXAMPLE_DIRS = (
    "docs/sphinx/examples/",
    "docs/sphinx/snippets/",
    "docs/sphinx/applications/",
    "docs/sphinx/targets/",
)
EXAMPLE_EXTS = (".py", ".cpp", ".ipynb")
MAX_EXAMPLE_CHARS = 20_000


def _gh_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _fetch_page(
    client: httpx.AsyncClient, base: str, entry: InvEntry, sem: asyncio.Semaphore
) -> tuple[InvEntry, str | None]:
    page = entry.uri.split("#")[0]
    if not page.endswith(".html"):
        return entry, None
    async with sem:
        r = await client.get(f"{base}/{page.removesuffix('.html')}.md")
    return entry, (r.text if r.status_code == 200 else None)


def _notebook_to_text(raw: str) -> str:
    try:
        nb = json.loads(raw)
        parts = []
        for cell in nb.get("cells", []):
            src = "".join(cell.get("source", []))
            if not src.strip():
                continue
            if cell.get("cell_type") == "code":
                parts.append(f"```python\n{src}\n```")
            else:
                parts.append(src)
        return "\n\n".join(parts)
    except (json.JSONDecodeError, TypeError):
        return ""


async def _fetch_examples(
    client: httpx.AsyncClient, version: str, say: Callable[[str], None]
) -> list[dict]:
    tag = version
    if version == "latest":
        r = await client.get(
            f"{GH_API}/repos/NVIDIA/cuda-quantum/releases/latest", headers=_gh_headers()
        )
        tag = r.json().get("tag_name", "main") if r.status_code == 200 else "main"

    tree = None
    for ref in (tag, f"v{tag}"):
        r = await client.get(
            f"{GH_API}/repos/NVIDIA/cuda-quantum/git/trees/{ref}?recursive=1",
            headers=_gh_headers(),
        )
        if r.status_code == 200:
            tree, tag = r.json(), ref
            break
    if tree is None:
        say(f"[cudaq-docs-mcp] examples: no repo tree for {version}; skipping")
        return []
    if tree.get("truncated"):
        say("[cudaq-docs-mcp] examples: repo tree truncated; example set may be partial")

    wanted = [
        t
        for t in tree.get("tree", [])
        if t.get("type") == "blob"
        and t["path"].startswith(EXAMPLE_DIRS)
        and t["path"].endswith(EXAMPLE_EXTS)
        and t.get("size", 0) < 300_000
    ]
    say(f"[cudaq-docs-mcp] examples: fetching {len(wanted)} files at {tag}")
    sem = asyncio.Semaphore(8)

    async def one(t: dict) -> dict | None:
        async with sem:
            r = await client.get(f"{GH_RAW}/{tag}/{t['path']}")
        if r.status_code != 200:
            return None
        text = r.text
        if t["path"].endswith(".ipynb"):
            text = _notebook_to_text(text)
        if not text.strip():
            return None
        lang = "cpp" if t["path"].endswith(".cpp") else "python"
        return {
            "path": t["path"],
            "language": lang,
            "url": f"https://github.com/NVIDIA/cuda-quantum/blob/{tag}/{t['path']}",
            "content": text[:MAX_EXAMPLE_CHARS],
        }

    got = await asyncio.gather(*(one(t) for t in wanted))
    return [g for g in got if g]


async def build_index(
    version: str = "latest",
    include_examples: bool = True,
    limit: int | None = None,
    out_dir: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    say = progress or (lambda s: print(s, flush=True))
    base = f"{BASE}/{version}"

    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers={"User-Agent": "cudaq-docs-mcp"}
    ) as client:
        r = await client.get(f"{base}/objects.inv")
        r.raise_for_status()
        entries = parse_objects_inv(r.content)
        pages = doc_pages(entries)
        apis = api_symbols(entries)
        if limit:
            pages = pages[:limit]
        say(f"[cudaq-docs-mcp] {version}: {len(pages)} pages, {len(apis)} API symbols")

        sem = asyncio.Semaphore(8)
        fetched = await asyncio.gather(*(_fetch_page(client, base, e, sem) for e in pages))

        llms_r = await client.get(f"{base}/llms.txt")
        llms_txt = llms_r.text if llms_r.status_code == 200 else ""

        examples = await _fetch_examples(client, version, say) if include_examples else []

    target = Path(out_dir) if out_dir else dbmod.cache_dir()
    target.mkdir(parents=True, exist_ok=True)
    final = target / dbmod.index_path(version).name
    tmp = final.with_suffix(".building")
    if tmp.exists():
        tmp.unlink()

    conn = sqlite3.connect(tmp)
    dbmod.create_schema(conn)
    n_chunks = 0
    missing = 0
    for entry, md in fetched:
        if md is None:
            missing += 1
            continue
        page_path = entry.uri.split("#")[0].removesuffix(".html")
        url = f"{base}/{page_path}.html"
        doc = clean_page(md, page_url=url)
        title = doc.title or entry.dispname or page_path
        cur = conn.execute(
            "INSERT OR IGNORE INTO pages(path, title, url, markdown) VALUES (?, ?, ?, ?)",
            (page_path, title, url, doc.text),
        )
        if cur.rowcount == 0:
            continue
        pid = cur.lastrowid
        for ch in chunk_doc(doc):
            conn.execute(
                "INSERT INTO chunks(page_id, breadcrumb, anchor, content) VALUES (?, ?, ?, ?)",
                (pid, ch.breadcrumb or title, ch.anchor, ch.content),
            )
            n_chunks += 1

    conn.executemany(
        "INSERT INTO api(name, dispname, domain, role, uri, priority) VALUES (?, ?, ?, ?, ?, ?)",
        [(a.name, a.dispname, a.domain, a.role, a.uri, a.priority) for a in apis],
    )
    for ex in examples:
        conn.execute(
            "INSERT OR IGNORE INTO examples(path, language, url, content) VALUES (?, ?, ?, ?)",
            (ex["path"], ex["language"], ex["url"], ex["content"]),
        )

    meta = {
        "version": version,
        "schema": str(dbmod.SCHEMA_VERSION),
        "built_at": str(int(time.time())),
        "docs_base": base,
        "pages": str(len(pages) - missing),
        "pages_missing_md": str(missing),
        "chunks": str(n_chunks),
        "api_symbols": str(len(apis)),
        "examples": str(len(examples)),
        "llms_txt": llms_txt,
    }
    conn.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", meta.items())
    dbmod.rebuild_fts(conn)
    conn.commit()
    conn.close()
    os.replace(tmp, final)
    say(
        f"[cudaq-docs-mcp] wrote {final}: {meta['pages']} pages, {n_chunks} chunks, "
        f"{len(apis)} symbols, {len(examples)} examples "
        f"({missing} pages had no md mirror)"
    )
    return final


def build_index_sync(**kwargs) -> Path:
    return asyncio.run(build_index(**kwargs))
