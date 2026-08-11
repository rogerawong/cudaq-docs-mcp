"""Parser for Sphinx objects.inv inventories (format version 2).

The inventory is the machine-readable manifest of a Sphinx site: every
document and every API symbol, with its URI. CUDA-Q publishes one per
docs version, which makes it both our crawl manifest (std:doc entries)
and our API symbol table (py:* and cpp:* entries).
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

_HEADER = b"# Sphinx inventory version 2"
# name domain:role priority uri dispname  (name may contain spaces)
_LINE = re.compile(r"(.+?)\s+(\S+):(\S+)\s+(-?\d+)\s+(\S+)\s+(.*)")


@dataclass(frozen=True)
class InvEntry:
    name: str
    domain: str
    role: str
    priority: int
    uri: str
    dispname: str


def parse_objects_inv(data: bytes) -> list[InvEntry]:
    """Parse raw objects.inv bytes into inventory entries."""
    if not data.startswith(_HEADER):
        raise ValueError("not a Sphinx v2 inventory")
    # Four header lines, then a zlib-compressed payload.
    offset = 0
    for _ in range(4):
        offset = data.index(b"\n", offset) + 1
    text = zlib.decompress(data[offset:]).decode("utf-8")

    entries: list[InvEntry] = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        name, domain, role, priority, uri, dispname = m.groups()
        if uri.endswith("$"):
            uri = uri[:-1] + name
        if dispname == "-":
            dispname = name
        entries.append(InvEntry(name, domain, role, int(priority), uri, dispname))
    return entries


def doc_pages(entries: list[InvEntry]) -> list[InvEntry]:
    """Entries for documentation pages (the crawl manifest)."""
    return [e for e in entries if e.domain == "std" and e.role == "doc"]


def api_symbols(entries: list[InvEntry]) -> list[InvEntry]:
    """Entries for Python and C++ API symbols."""
    return [e for e in entries if e.domain in ("py", "cpp")]
