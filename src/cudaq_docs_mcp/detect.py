"""Detect the installed cudaq package version.

The version-pinning thesis: answer from the docs matching what the user
actually has installed. Detection reads distribution metadata only, so it
never imports cudaq (which would pull in the full runtime).
"""

from __future__ import annotations

from importlib import metadata

_DIST_CANDIDATES = (
    "cudaq",
    "cuda-quantum",
    "cuda-quantum-cu13",
    "cuda-quantum-cu12",
    "cuda-quantum-cu11",
)


def installed_cudaq_version() -> str | None:
    for dist in _DIST_CANDIDATES:
        try:
            return metadata.version(dist)
        except metadata.PackageNotFoundError:
            continue
    return None
