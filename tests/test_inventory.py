import zlib

import pytest

from cudaq_docs_mcp.inventory import api_symbols, doc_pages, parse_objects_inv

HEADER = (
    b"# Sphinx inventory version 2\n"
    b"# Project: CUDA-Q\n"
    b"# Version: latest\n"
    b"# The remainder of this file is compressed using zlib.\n"
)


def make_inv() -> bytes:
    lines = (
        "using/quick_start std:doc -1 using/quick_start.html Quick Start\n"
        "cudaq.sample py:function 1 api/languages/python_api.html#$ -\n"
        "cudaq::qvector cpp:class 1 api/languages/cpp_api.html#qvector qvector\n"
        "Quick Start std:label -1 using/quick_start.html#quick-start -\n"
    )
    return HEADER + zlib.compress(lines.encode())


def test_parse_expands_and_classifies():
    entries = parse_objects_inv(make_inv())
    assert len(entries) == 4

    sample = next(e for e in entries if e.name == "cudaq.sample")
    assert sample.uri == "api/languages/python_api.html#cudaq.sample"
    assert sample.dispname == "cudaq.sample"

    label = next(e for e in entries if e.role == "label")
    assert label.name == "Quick Start"  # names may contain spaces

    docs = doc_pages(entries)
    assert [d.uri for d in docs] == ["using/quick_start.html"]
    assert {a.domain for a in api_symbols(entries)} == {"py", "cpp"}


def test_rejects_non_inventory():
    with pytest.raises(ValueError):
        parse_objects_inv(b"not an inventory")
