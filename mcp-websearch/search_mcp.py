#!/usr/bin/env python3
"""Minimal web search MCP server using DuckDuckGo."""

import asyncio
import logging
import sys
from typing import Any

from duckduckgo_search import DDGS
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
)

# Enable logging to both stderr and a file for debugging
import os
log_dir = "/tmp/search-mcp"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "search-mcp.log")

# Set up logging handlers
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# File handler
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logger.addHandler(file_handler)

# Stderr handler
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.DEBUG)
stderr_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logger.addHandler(stderr_handler)


# Initialize MCP server
server = Server(name="search-mcp", version="0.1.0")


def search_duckduckgo(query: str, max_results: int = 5) -> str:
    """
    Search using DuckDuckGo DDGS scraper and return formatted results.

    Args:
        query: Search query string
        max_results: Maximum number of results to return (default: 5)

    Returns:
        Formatted search results as string
    """
    logger = logging.getLogger("search_mcp")
    logger.info(f"Search request: query='{query}', max_results={max_results}")

    try:
        # Use DDGS to search
        ddgs = DDGS()
        results = list(ddgs.text(query, max_results=max_results))

        if not results:
            msg = f"No results found for '{query}'."
            logger.warning(msg)
            return msg

        # Format results for LLM
        output = f"Search results for '{query}':\n\n"
        for i, result in enumerate(results, 1):
            output += f"{i}. **{result['title']}**\n"
            if result.get("href"):
                output += f"   URL: {result['href']}\n"
            if result.get("body"):
                output += f"   {result['body']}\n"
            output += "\n"

        logger.info(f"Returning {len(results)} results for query '{query}'")
        return output

    except TimeoutError:
        msg = f"Error: Search request timed out for query '{query}'. Check your internet connection."
        logger.error(msg)
        return msg
    except Exception as e:
        msg = f"Error: Failed to search for '{query}': {str(e)}"
        logger.error(msg, exc_info=True)
        return msg


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    logger = logging.getLogger("search_mcp")
    logger.info("Listing available tools")
    return [
        Tool(
            name="web_search",
            description="Search the web using DuckDuckGo. No API key required.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a tool."""
    logger = logging.getLogger("search_mcp")
    logger.info(f"Tool call: name='{name}', arguments={arguments}")

    # Support both "web_search" and "search" names for compatibility
    if name in ("web_search", "search"):
        query = arguments.get("query", "")
        max_results = arguments.get("max_results", 5)

        logger.info(f"Executing search: query='{query}', max_results={max_results}")

        if not query:
            error_msg = "Error: 'query' parameter is required"
            logger.error(error_msg)
            return [TextContent(type="text", text=error_msg)]

        result = search_duckduckgo(query, max_results)
        logger.info(f"Search result: {len(result)} characters")
        return [TextContent(type="text", text=result)]

    error_msg = f"Error: Unknown tool '{name}'. Available tools: web_search"
    logger.error(error_msg)
    return [TextContent(type="text", text=error_msg)]


async def main():
    """Run the MCP server."""
    logger = logging.getLogger("search_mcp")
    logger.info(f"Starting search-mcp server (logs: {log_file})")

    # Create stdio transport
    transport = stdio_server()

    # Connect server to transport and run
    async with transport as streams:
        await server.run(
            streams[0],
            streams[1],
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
