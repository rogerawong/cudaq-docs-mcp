from cudaq_docs_mcp.targets import load_targets

REQUIRED = {
    "name",
    "category",
    "kind",
    "summary",
    "gpu",
    "select_python",
    "select_cli",
    "when_to_use",
    "docs_url",
}


def test_targets_shape():
    data = load_targets()
    assert data["how_to_choose"]
    assert len(data["targets"]) >= 20
    for t in data["targets"]:
        assert REQUIRED <= set(t), f"missing fields on {t.get('name')}"
        assert t["category"] in ("simulator", "hardware", "cloud")
        assert t["docs_url"].startswith("https://nvidia.github.io/cuda-quantum/")


def test_core_targets_present():
    names = {t["name"] for t in load_targets()["targets"]}
    assert {"qpp-cpu", "nvidia", "tensornet", "stim", "dynamics", "ionq", "quantinuum", "braket"} <= names
