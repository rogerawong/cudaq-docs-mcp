"""Download prebuilt indexes from GitHub release assets.

A nightly workflow publishes refreshed indexes to a rolling release so
first-run users get an index in seconds instead of building one. Any
failure falls through to None; callers then build locally or explain how.
"""

from __future__ import annotations

import gzip
import os
from pathlib import Path

import httpx

from . import db as dbmod

RELEASE_TAG = "index-v1"
REPO = "rogerawong/cudaq-docs-mcp"


def try_download(version: str) -> Path | None:
    dest = dbmod.index_path(version)
    url = (
        f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/{dest.name}.gz"
    )
    try:
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            r = client.get(url)
            if r.status_code != 200:
                return None
            data = gzip.decompress(r.content)
    except (httpx.HTTPError, gzip.BadGzipFile, OSError):
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".downloading")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    return dest
