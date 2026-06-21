"""
BullyStop MCP Server

Exposes get_support_resources as a Model Context Protocol (MCP) tool over stdio.

Run standalone:
    python mcp_server.py

ADK agents connect to this via MCPToolset + StdioServerParameters (see
agents/bullystop_agents.py :: create_agents_with_mcp()).  The Gradio demo uses
a direct Python FunctionTool instead (same function, no subprocess overhead), but
this server demonstrates the full MCP pattern so the two are interchangeable.
"""

import asyncio
import json
import os
import sys

# Make the project root importable so skills/ is on the path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from skills.support_resources.scripts.get_support_resources import get_support_resources

server = Server("bullystop-resources")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_support_resources",
            description=(
                "Returns a curated list of verified anti-bullying and mental health "
                "support resources (hotlines, websites, government programs) for a "
                "specific country or region. "
                "Call this whenever the user needs external help, mentions being in "
                "crisis, asks for hotlines or resources, or when severity is 'high'. "
                "Always prefer calling this tool over inventing or guessing any phone "
                "numbers or websites."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "country": {
                        "type": "string",
                        "description": (
                            "Country name (e.g. 'Argentina', 'United States', 'Spain', "
                            "'Brazil') or 'default' if the user's country is unknown."
                        ),
                    }
                },
                "required": ["country"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "get_support_resources":
        country = arguments.get("country", "default")
        result = get_support_resources(country)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
