"""Command-line entry point: serve (default), build, and info."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from . import db as dbmod
from .detect import installed_cudaq_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cudaq-docs-mcp",
        description="MCP server serving NVIDIA CUDA-Q documentation to AI agents.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"cudaq-docs-mcp {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("serve", help="run the MCP server on stdio (the default)")

    build = sub.add_parser("build", help="build a local docs index")
    build.add_argument(
        "--version",
        dest="docs_version",
        default=None,
        help="docs version to index, e.g. 0.15.0 or latest (default: installed cudaq, else latest)",
    )
    build.add_argument("--no-examples", action="store_true", help="skip example ingestion")
    build.add_argument("--limit", type=int, default=None, help="index only the first N pages")
    build.add_argument("--out", default=None, help="write the index to this directory")

    sub.add_parser("info", help="show cache location, indexes, and detected cudaq")

    args = parser.parse_args(argv)

    if args.cmd == "build":
        from .ingest import build_index_sync

        version = args.docs_version or installed_cudaq_version() or "latest"
        build_index_sync(
            version=version,
            include_examples=not args.no_examples,
            limit=args.limit,
            out_dir=args.out,
        )
        return 0

    if args.cmd == "info":
        print(f"cudaq-docs-mcp {__version__}")
        print(f"installed cudaq: {installed_cudaq_version() or 'not detected'}")
        print(f"cache directory: {dbmod.cache_dir()}")
        versions = dbmod.indexed_versions()
        print(f"indexed versions: {', '.join(versions) if versions else 'none'}")
        return 0

    from .server import run

    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
