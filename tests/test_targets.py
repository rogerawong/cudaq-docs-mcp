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


def test_list_targets_category_filter_and_enum_schema():
    """Category filter works, the schema enforces the enum, and an invalid
    value that reaches the handler gets a named error, never an empty list."""
    import asyncio
    import json

    from cudaq_docs_mcp.server import list_targets, mcp

    hw = list_targets(category="hardware")["targets"]
    assert hw and all(t["category"] == "hardware" for t in hw)
    assert len(list_targets()["targets"]) >= 20

    bad = list_targets(category="banana")
    assert "targets" not in bad
    assert "simulator" in bad["error"] and "hardware" in bad["error"] and "cloud" in bad["error"]

    tools = asyncio.run(mcp.list_tools())
    lt = next(t for t in tools if t.name == "list_targets")
    schema = json.dumps(lt.model_dump())
    assert "simulator" in schema and "hardware" in schema and "cloud" in schema
    assert "enum" in schema


def test_find_api_cross_references_list_targets():
    """The target-option-values question class is redirected from the winning
    tool's side: find_api's description points at list_targets."""
    import asyncio

    from cudaq_docs_mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    fa = next(t for t in tools if t.name == "find_api")
    assert "list_targets" in fa.description
    assert "set_target" in fa.description
