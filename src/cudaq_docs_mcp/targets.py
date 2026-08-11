"""Curated CUDA-Q target (backend) matrix.

Answering "which target do I run this on?" is the recurring question that
connects quantum workloads to the GPU stack, so it gets structured data
rather than search results. Curated from the backends section of the
CUDA-Q docs; the source and review date are recorded in the data file.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources


@lru_cache(maxsize=1)
def load_targets() -> dict:
    ref = resources.files("cudaq_docs_mcp").joinpath("data/targets.json")
    return json.loads(ref.read_text(encoding="utf-8"))
