"""End-to-end smoke test through a real MCP stdio session.

Requires a built index (run `cudaq-docs-mcp build` first). Exercises every
tool the way a client would: spawn the server, initialize, call, print.
"""

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "cudaq_docs_mcp"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", ", ".join(t.name for t in tools.tools))

            async def call(tool: str, **args):
                res = await session.call_tool(tool, args)
                text = res.content[0].text if res.content else "(empty)"
                flag = " [ERROR]" if res.is_error else ""
                print(f"\n=== {tool} {args}{flag}\n{text[:1200]}")

            await call("search_docs", query="run a kernel on the GPU state vector simulator")
            await call("find_api", name="sample", language="python")
            await call("get_page", path="using/quick_start")
            await call("search_examples", query="GHZ state", language="python")
            await call("list_targets", category="simulator")


if __name__ == "__main__":
    asyncio.run(main())
