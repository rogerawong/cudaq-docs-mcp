from importlib import metadata

from cudaq_docs_mcp import detect


def _fake(versions):
    def fake_version(dist):
        if dist in versions:
            return versions[dist]
        raise metadata.PackageNotFoundError(dist)

    return fake_version


def test_cu13_only_environment(monkeypatch):
    monkeypatch.setattr(detect.metadata, "version", _fake({"cuda-quantum-cu13": "0.14.0"}))
    assert detect.installed_cudaq_version() == "0.14.0"


def test_metapackage_wins_over_wheel(monkeypatch):
    monkeypatch.setattr(
        detect.metadata,
        "version",
        _fake({"cudaq": "0.15.0", "cuda-quantum-cu13": "0.15.1"}),
    )
    assert detect.installed_cudaq_version() == "0.15.0"


def test_none_when_absent(monkeypatch):
    monkeypatch.setattr(detect.metadata, "version", _fake({}))
    assert detect.installed_cudaq_version() is None
