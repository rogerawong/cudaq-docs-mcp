"""Result-embedded signposts: turn-N routing hints in search_docs responses."""

import pytest

from cudaq_docs_mcp import assets
from cudaq_docs_mcp import db as dbmod
from cudaq_docs_mcp import server
from cudaq_docs_mcp.server import _see_also


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CUDAQ_DOCS_MCP_CACHE", str(tmp_path))
    monkeypatch.delenv("CUDAQ_DOCS_MCP_AUTOBUILD", raising=False)
    monkeypatch.setattr(assets, "try_download", lambda version: None)
    monkeypatch.setattr(server, "installed_cudaq_version", lambda: None)
    yield tmp_path


def make_index(pages):
    path = dbmod.index_path("latest")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = dbmod.connect(path, readonly=False)
    dbmod.create_schema(conn)
    for i, (page_path, content) in enumerate(pages, start=1):
        conn.execute(
            "INSERT INTO pages(path, title, url, markdown) VALUES (?, ?, ?, ?)",
            (page_path, page_path, f"https://x/{page_path}.html", content),
        )
        conn.execute(
            "INSERT INTO chunks(page_id, breadcrumb, anchor, content) VALUES (?, ?, ?, ?)",
            (i, page_path, "", content),
        )
    dbmod.rebuild_fts(conn)
    conn.commit()
    conn.close()


def test_hint_fires_once_for_comparison_pages():
    hint = _see_also(["using/backends/sims/svsims", "using/backends/sims/mqpusims"])
    assert hint and "list_targets" in hint


def test_detail_pages_stay_silent():
    # The debugging-question pages share the using/backends/sims/ prefix with
    # the comparison pages; the allowlist, not a prefix, separates them.
    assert _see_also(["using/backends/sims/tnsims"]) is None
    assert _see_also(["using/backends/sims/noisy", "api/languages/cpp_api"]) is None
    assert _see_also([]) is None


def test_search_docs_attaches_and_omits_field():
    make_index(
        [
            ("using/backends/sims/svsims", "mgpu option scales the nvidia state vector"),
            ("using/backends/sims/tnsims", "tensornet mps seed reproducibility notes"),
        ]
    )
    hit = server.search_docs("mgpu option nvidia")
    assert hit["results"]
    assert "list_targets" in hit["see_also"]

    miss = server.search_docs("tensornet mps seed")
    assert miss["results"]
    assert "see_also" not in miss
