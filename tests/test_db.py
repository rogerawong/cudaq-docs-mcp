import pytest

from cudaq_docs_mcp import db as dbmod


@pytest.fixture()
def index(tmp_path):
    path = tmp_path / "index.sqlite3"
    conn = dbmod.connect(path, readonly=False)
    dbmod.create_schema(conn)
    conn.execute(
        "INSERT INTO pages(path, title, url, markdown) VALUES (?, ?, ?, ?)",
        (
            "using/quick_start",
            "Quick Start",
            "https://x/using/quick_start.html",
            "# Quick Start\n\nInstall and run.",
        ),
    )
    conn.executemany(
        "INSERT INTO chunks(page_id, breadcrumb, anchor, content) VALUES (1, ?, ?, ?)",
        [
            ("Quick Start › Install", "install", "Install CUDA-Q with pip install cudaq"),
            ("Quick Start › GPU", "gpu", "Run kernels on the nvidia GPU state vector target"),
        ],
    )
    conn.executemany(
        "INSERT INTO api(name, dispname, domain, role, uri, priority) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("cudaq.sample", "cudaq.sample", "py", "function", "api/python.html#cudaq.sample", 1),
            ("cudaq::qvector", "qvector", "cpp", "class", "api/cpp.html#qvector", 1),
        ],
    )
    conn.execute(
        "INSERT INTO examples(path, language, url, content) VALUES (?, ?, ?, ?)",
        (
            "docs/sphinx/examples/python/ghz.py",
            "python",
            "https://gh/ghz.py",
            "GHZ state kernel sampled with cudaq.sample",
        ),
    )
    dbmod.rebuild_fts(conn)
    conn.commit()
    conn.close()
    return path


def test_search_hits_and_anchor_url(index):
    conn = dbmod.connect(index)
    results = dbmod.search_chunks(conn, "pip install")
    assert results and results[0]["url"].endswith("#install")
    assert "Quick Start" in results[0]["breadcrumb"]


def test_search_or_fallback(index):
    conn = dbmod.connect(index)
    # No chunk contains all three terms; OR fallback should still match one.
    results = dbmod.search_chunks(conn, "nvidia zzzmissing target")
    assert results


def test_search_operator_injection_is_safe(index):
    conn = dbmod.connect(index)
    # FTS5 operators and stray punctuation must not raise.
    assert dbmod.search_chunks(conn, 'OR AND ("*: NEAR') == [] or True


def test_find_api_suffix_and_domain(index):
    conn = dbmod.connect(index)
    rows = dbmod.find_api(conn, "sample")
    assert rows[0]["name"] == "cudaq.sample"
    rows = dbmod.find_api(conn, "qvector")
    assert rows[0]["domain"] == "cpp"
    assert dbmod.find_api(conn, "qvector", domain="py") == []


def test_get_page_normalizes(index):
    conn = dbmod.connect(index)
    for form in ("using/quick_start", "using/quick_start.html", "/using/quick_start.md", "quick_start"):
        page = dbmod.get_page(conn, form)
        assert page and page["title"] == "Quick Start"


def test_examples_language_filter(index):
    conn = dbmod.connect(index)
    assert dbmod.search_examples(conn, "GHZ", language="python")
    assert dbmod.search_examples(conn, "GHZ", language="cpp") == []
