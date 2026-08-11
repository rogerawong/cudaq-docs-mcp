"""Version resolution and index fallback logic, no network."""

import pytest

from cudaq_docs_mcp import assets
from cudaq_docs_mcp import db as dbmod
from cudaq_docs_mcp import server


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CUDAQ_DOCS_MCP_CACHE", str(tmp_path))
    monkeypatch.delenv("CUDAQ_DOCS_MCP_AUTOBUILD", raising=False)
    monkeypatch.setattr(assets, "try_download", lambda version: None)
    yield tmp_path


def make_index(version):
    path = dbmod.index_path(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = dbmod.connect(path, readonly=False)
    dbmod.create_schema(conn)
    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('llms_txt', '# CUDA-Q')",
    )
    dbmod.rebuild_fts(conn)
    conn.commit()
    conn.close()
    return path


def test_explicit_version_wins(monkeypatch):
    monkeypatch.setattr(server, "installed_cudaq_version", lambda: "0.15.0")
    ver, note = server._resolve_version("0.14.0")
    assert ver == "0.14.0" and note is None


def test_detected_version_is_default(monkeypatch):
    monkeypatch.setattr(server, "installed_cudaq_version", lambda: "0.15.0")
    ver, note = server._resolve_version(None)
    assert ver == "0.15.0"
    assert "detected" in note


def test_no_install_falls_back_to_latest(monkeypatch):
    monkeypatch.setattr(server, "installed_cudaq_version", lambda: None)
    ver, note = server._resolve_version(None)
    assert ver == "latest"


def test_missing_index_raises_with_instructions(monkeypatch):
    monkeypatch.setattr(server, "installed_cudaq_version", lambda: None)
    with pytest.raises(RuntimeError, match="cudaq-docs-mcp build"):
        server._open(None)


def test_pinned_missing_falls_back_to_latest_with_note(monkeypatch):
    monkeypatch.setattr(server, "installed_cudaq_version", lambda: "0.9.9")
    make_index("latest")
    conn, ver, note = server._open(None)
    conn.close()
    assert ver == "latest"
    assert "0.9.9" in note and "pinned answers" in note
