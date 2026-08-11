"""SQLite storage and search for CUDA-Q docs indexes.

One database per docs version. Full-text search runs on SQLite's built-in
FTS5 with BM25 ranking and porter stemming: no embeddings, no API keys,
fully offline once the index exists.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path

SCHEMA_VERSION = 1
BASE_URL = "https://nvidia.github.io/cuda-quantum"

_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE pages (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE,
    title TEXT,
    url TEXT,
    markdown TEXT
);
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    page_id INTEGER REFERENCES pages(id),
    breadcrumb TEXT,
    anchor TEXT,
    content TEXT
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    content, breadcrumb,
    content='chunks', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE TABLE api (
    name TEXT,
    dispname TEXT,
    domain TEXT,
    role TEXT,
    uri TEXT,
    priority INTEGER
);
CREATE INDEX api_name ON api(name);
CREATE TABLE examples (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE,
    language TEXT,
    url TEXT,
    content TEXT
);
CREATE VIRTUAL TABLE examples_fts USING fts5(
    content, path,
    content='examples', content_rowid='id',
    tokenize='porter unicode61'
);
"""


def cache_dir() -> Path:
    env = os.environ.get("CUDAQ_DOCS_MCP_CACHE")
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "cudaq-docs-mcp"
    xdg = os.environ.get("XDG_CACHE_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return root / "cudaq-docs-mcp"


def index_path(version: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", version)
    return cache_dir() / f"index-{safe}-s{SCHEMA_VERSION}.sqlite3"


def indexed_versions() -> list[str]:
    pat = re.compile(rf"^index-(.+)-s{SCHEMA_VERSION}\.sqlite3$")
    found = []
    if cache_dir().exists():
        for p in cache_dir().iterdir():
            m = pat.match(p.name)
            if m:
                found.append(m.group(1))
    return sorted(found)


def connect(path: Path, readonly: bool = True) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    conn.execute("INSERT INTO examples_fts(examples_fts) VALUES('rebuild')")


def get_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}


def _match_strings(query: str) -> tuple[str, str]:
    """Sanitize a natural-language query into FTS5 match strings.

    Each token is phrase-quoted so FTS5 operators in user text cannot
    break the query. Returns (all-terms, any-term) variants.
    """
    tokens = re.findall(r"[A-Za-z0-9_.+#-]+", query)[:12]
    quoted = [f'"{t}"' for t in tokens if t.strip(".-_")]
    return " ".join(quoted), " OR ".join(quoted)


def search_chunks(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict]:
    and_q, or_q = _match_strings(query)
    if not and_q:
        return []
    sql = """
        SELECT p.path, p.title, p.url, c.breadcrumb, c.anchor,
               snippet(chunks_fts, 0, '', '', ' … ', 48) AS snippet,
               bm25(chunks_fts) AS score
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        JOIN pages p ON p.id = c.page_id
        WHERE chunks_fts MATCH ?
        ORDER BY score LIMIT ?
    """
    rows = conn.execute(sql, (and_q, limit)).fetchall()
    if not rows and or_q != and_q:
        rows = conn.execute(sql, (or_q, limit)).fetchall()
    out = []
    for r in rows:
        url = r["url"] + (f"#{r['anchor']}" if r["anchor"] else "")
        out.append(
            {
                "breadcrumb": r["breadcrumb"],
                "snippet": r["snippet"],
                "page": r["path"],
                "url": url,
            }
        )
    return out


def get_page(conn: sqlite3.Connection, path: str) -> dict | None:
    norm = path.strip().lstrip("/")
    norm = re.sub(r"\.(html|md)$", "", norm)
    row = conn.execute(
        "SELECT path, title, url, markdown FROM pages WHERE path = ?", (norm,)
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT path, title, url, markdown FROM pages WHERE path LIKE ? "
            "ORDER BY length(path) LIMIT 1",
            (f"%{norm}",),
        ).fetchone()
    return dict(row) if row else None


def find_api(
    conn: sqlite3.Connection, name: str, domain: str | None = None, limit: int = 10
) -> list[dict]:
    """Tiered symbol lookup: exact, then dotted/scoped suffix, then substring."""
    clauses = []
    dom_sql = " AND domain = ?" if domain else ""

    def run(where: str, params: tuple) -> list[sqlite3.Row]:
        p = params + ((domain,) if domain else ())
        return conn.execute(
            f"SELECT name, dispname, domain, role, uri, priority FROM api "
            f"WHERE {where}{dom_sql} ORDER BY priority, length(name) LIMIT ?",
            p + (limit,),
        ).fetchall()

    rows = run("(name = ? COLLATE NOCASE OR dispname = ? COLLATE NOCASE)", (name, name))
    if not rows:
        rows = run(
            "(name LIKE ? COLLATE NOCASE OR name LIKE ? COLLATE NOCASE)",
            (f"%.{name}", f"%::{name}"),
        )
    if not rows:
        rows = run("name LIKE ? COLLATE NOCASE", (f"%{name}%",))
    seen: set[tuple[str, str]] = set()
    out = []
    for r in rows:
        key = (r["domain"], r["name"])
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(r))
    return out


def search_examples(
    conn: sqlite3.Connection, query: str, language: str | None = None, limit: int = 5
) -> list[dict]:
    and_q, or_q = _match_strings(query)
    if not and_q:
        return []
    lang_sql = " AND e.language = ?" if language else ""
    sql = f"""
        SELECT e.path, e.language, e.url, e.content, bm25(examples_fts) AS score
        FROM examples_fts
        JOIN examples e ON e.id = examples_fts.rowid
        WHERE examples_fts MATCH ?{lang_sql}
        ORDER BY score LIMIT ?
    """
    params: tuple = (and_q,) + ((language,) if language else ()) + (limit,)
    rows = conn.execute(sql, params).fetchall()
    if not rows and or_q != and_q:
        params = (or_q,) + ((language,) if language else ()) + (limit,)
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
