# agents/web_search/mcp_server.py
"""
MCP Layer using MCPServer (MCP SDK 2.0).

CONFIRMED IMPORT PATH:
    from mcp.server.mcpserver import MCPServer

CONFIRMED: @app.tool() decorator EXISTS on MCPServer.
This works identically to FastMCP's @app.tool().

ARCHITECTURE:
─────────────────────────────────────────────────────
This module has TWO responsibilities:

1. MCP SERVER (for Claude Desktop / MCP clients)
   MCPServer instance with @tool decorators.
   Can be run standalone via stdio or HTTP/SSE.

2. GEMINI BRIDGE (for internal agent tool calling)
   execute_mcp_tool() + get_gemini_tool_declarations()
   Used by main.py's Gemini tool-calling loop.

This dual approach means:
- Any MCP client (Claude Desktop) can use our tools
- Our Gemini agent can also use the same tools
- Single source of truth for tool implementations
─────────────────────────────────────────────────────
"""

from __future__ import annotations
import json
from typing import Any

from mcp.server.mcpserver import MCPServer
import structlog

from shared.config import settings
from agents.web_search.tools import (
    search_web,
    get_news,
    fetch_url,
)

logger = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════
# MCP SERVER INSTANCE
# ══════════════════════════════════════════════════════════════

mcp = MCPServer(
    name="web-search-agent",
    title="Web Search Agent",
    description=(
        "Specialized MCP server for web research. "
        "Provides tools for searching the web, "
        "fetching news, and reading URL content."
    ),
    instructions=(
        "Use these tools to find current information from the web. "
        "Always cite sources with URLs in your responses. "
        "search_web_tool for general search, "
        "get_news_tool for recent news, "
        "fetch_url_tool to read specific pages."
    ),
    version="1.0.0",
)


# ══════════════════════════════════════════════════════════════
# TOOL DEFINITIONS
#
# @mcp.tool() registers the function as an MCP tool.
# MCPServer auto-generates JSON schema from type hints.
# Docstring becomes the tool description for LLM clients.
# ══════════════════════════════════════════════════════════════

@mcp.tool()
async def search_web_tool(
    query: str,
    max_results: int = 5
) -> str:
    """
    Search the web for current information on any topic.
    Returns titles, URLs, and snippets from search results.
    Use for general web searches, finding current info,
    researching topics, or finding specific websites.

    Args:
        query: Search query. Be specific for better results.
               Example: 'quantum computing companies Singapore 2024'
        max_results: Number of results to return (1-10).
    """
    logger.info("mcp_tool_called", tool="search_web_tool", query=query)

    results = await search_web(
        query=query,
        max_results=max_results
    )

    if not results:
        return "No search results found for this query."

    lines = [f"Found {len(results)} results for '{query}':\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r.title}")
        lines.append(f"    URL: {r.url}")
        lines.append(f"    {r.snippet}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def get_news_tool(
    topic: str,
    max_results: int = 5
) -> str:
    """
    Fetch recent news articles about a specific topic.
    Returns articles with titles, snippets, and publish dates.
    Use when the user asks about recent events or
    wants up-to-date information on a subject.

    Args:
        topic: The news topic to search for.
               Example: 'AI startup funding Singapore'
        max_results: Number of articles to return (1-10).
    """
    logger.info("mcp_tool_called", tool="get_news_tool", topic=topic)

    news = await get_news(
        topic=topic,
        max_results=max_results
    )

    if not news:
        return f"No news articles found about '{topic}'."

    lines = [f"Found {len(news)} articles about '{topic}':\n"]
    for i, r in enumerate(news, 1):
        lines.append(f"[{i}] {r.title}")
        lines.append(f"    Source: {r.source_name}")
        if r.published_date:
            lines.append(f"    Date: {r.published_date}")
        lines.append(f"    URL: {r.url}")
        lines.append(f"    {r.snippet}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def fetch_url_tool(url: str) -> str:
    """
    Fetch and extract readable text content from a URL.
    Strips HTML tags and returns clean text.
    Use when you have a specific URL to read in full.

    Args:
        url: The full URL to fetch.
             Must start with http:// or https://
    """
    logger.info("mcp_tool_called", tool="fetch_url_tool", url=url)

    result = await fetch_url(url=url)

    lines = []
    if result.title:
        lines.append(f"Title: {result.title}")
    lines.append(f"URL: {result.url}")
    lines.append(f"Status: {result.status_code}")
    lines.append("─" * 50)
    lines.append(result.content)

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# RESOURCE DEFINITIONS
# ══════════════════════════════════════════════════════════════

@mcp.resource("resource://web-search/capabilities")
async def get_capabilities() -> str:
    """
    Web Search Agent capabilities and configuration.
    Read this to understand what this agent can do
    and which search providers are active.
    """
    capabilities = {
        "agent": "web-search-agent",
        "mcp_version": "2.0",
        "tools": [
            "search_web_tool",
            "get_news_tool",
            "fetch_url_tool"
        ],
        "search_providers": {
            "primary": "google_cse"
            if settings.google_search_api_key
            else "duckduckgo",
            "fallback": "duckduckgo"
        },
        "limits": {
            "max_results_per_query": 10,
            "max_content_length": 8000,
            "daily_google_quota": 100
        }
    }
    return json.dumps(capabilities, indent=2)


# ══════════════════════════════════════════════════════════════
# GEMINI BRIDGE
# Converts MCP tools → Gemini function calling format
# Used by main.py's agent loop
# ══════════════════════════════════════════════════════════════

def get_gemini_tool_declarations() -> list[dict[str, Any]]:
    """
    Export tool definitions in Gemini's function
    calling format.

    MCP uses 'inputSchema' key.
    Gemini uses 'parameters' key.
    Same JSON Schema content, different key name.
    """
    return [
        {
            "name": "search_web_tool",
            "description": (
                "Search the web for current information. "
                "Returns titles, URLs, and snippets. "
                "Use for research and finding current info."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query string"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results (1-10)",
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "get_news_tool",
            "description": (
                "Fetch recent news articles about a topic. "
                "Returns articles with dates and sources. "
                "Use for current events and recent news."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The news topic to search"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of articles (1-10)",
                    }
                },
                "required": ["topic"]
            }
        },
        {
            "name": "fetch_url_tool",
            "description": (
                "Fetch and read content from a specific URL. "
                "Returns clean extracted text without HTML. "
                "Use when you have a specific URL to read."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "Full URL to fetch "
                            "(http:// or https://)"
                        )
                    }
                },
                "required": ["url"]
            }
        },
    ]


async def execute_mcp_tool(
    tool_name: str,
    tool_args: dict[str, Any]
) -> str:
    """
    Execute a tool by name.

    This bridges Gemini's function calling with
    our MCP tool implementations.

    Gemini requests: tool_name + args
    We execute:      the matching tool function
    We return:       string result back to Gemini
    """
    logger.info(
        "executing_tool",
        tool=tool_name,
        args={k: str(v)[:50] for k, v in tool_args.items()}
    )

    try:
        if tool_name == "search_web_tool":
            return await search_web_tool(
                query=tool_args["query"],
                max_results=tool_args.get("max_results", 5)
            )

        elif tool_name == "get_news_tool":
            return await get_news_tool(
                topic=tool_args["topic"],
                max_results=tool_args.get("max_results", 5)
            )

        elif tool_name == "fetch_url_tool":
            return await fetch_url_tool(
                url=tool_args["url"]
            )

        else:
            logger.warning("unknown_tool_called", tool=tool_name)
            return f"Error: Unknown tool '{tool_name}'"

    except KeyError as e:
        msg = f"Missing required argument: {e}"
        logger.error("tool_missing_arg", tool=tool_name, error=msg)
        return f"Error: {msg}"

    except Exception as e:
        msg = f"Tool execution failed: {str(e)}"
        logger.error("tool_failed", tool=tool_name, error=msg, exc_info=True)
        return f"Error: {msg}"