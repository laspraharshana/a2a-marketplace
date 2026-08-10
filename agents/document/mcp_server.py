"""
Document Agent MCP server.

Three tools exposed to Gemini:
  extract_text      — PDF/DOCX/URL → raw text
  summarize_document — text → structured summary
  extract_entities  — text → categorized entities

Bridge pattern same as data_analysis:
  Gemini function-calls → execute_mcp_tool() → tools.py functions
  MCPServer instance kept for A2A spec compliance.
"""

from __future__ import annotations

import json

import structlog
from mcp.server.mcpserver import MCPServer

from agents.document.tools import (
    EntityResult,
    ExtractionResult,
    SummaryResult,
    extract_entities,
    extract_text,
    summarize_document,
)

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

mcp = MCPServer(
    name="document-agent",
    title="Document Processing Agent",
    description=(
        "Extracts text from PDF/DOCX/URL sources, summarizes documents, "
        "and extracts named entities (people, dates, organizations, etc.)."
    ),
    instructions=(
        "Use extract_text first to get document content, "
        "then summarize_document or extract_entities as needed. "
        "For URL sources, extract_text handles HTML cleanup automatically."
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Tool registrations
# ---------------------------------------------------------------------------

@mcp.tool()
async def extract_text_tool(
    source: str,
    source_type: str = "auto",
) -> str:
    """
    Extract text from a document source.

    Supports PDF files, DOCX files, plain text files, and URLs.
    For URLs, automatically cleans HTML and extracts main content.
    For PDFs served via URL, detects content-type and extracts accordingly.

    Args:
        source: File path (e.g. '/tmp/report.pdf') or URL
                (e.g. 'https://example.com/article')
        source_type: Detection mode — 'auto' (default), 'pdf', 'docx',
                     'url', or 'txt'. Use 'auto' unless you know the type.

    Returns:
        JSON string with extraction results including the text content
        and metadata (word count, page count, etc.).
    """
    result: ExtractionResult = await extract_text(source, source_type)

    if not result.success:
        return json.dumps({
            "success": False,
            "error": result.error,
            "source": source,
        })

    return json.dumps({
        "success": True,
        "text": result.text[:8000],   # cap for tool response size
        "text_truncated": len(result.text) > 8000,
        "full_text_length": len(result.text),
        "source_type": result.source,
        "page_count": result.page_count,
        "word_count": result.word_count,
        "char_count": result.char_count,
        "summary_line": result.summary_line(),
    })


@mcp.tool()
async def summarize_document_tool(
    text: str,
    style: str = "concise",
    max_length: int = 300,
) -> str:
    """
    Summarize document text with configurable style.

    Best used after extract_text_tool to get the document content.
    Makes a nested LLM call internally for summarization quality.

    Args:
        text: The document text to summarize (from extract_text_tool).
        style: Summary style —
               'concise'   (default): brief, main points only
               'detailed'  : comprehensive, all sections
               'bullet'    : bullet points with overview
               'executive' : purpose, findings, recommendations
        max_length: Target word count for the summary (default 300).
                    Approximate — LLM may vary ±20%.

    Returns:
        JSON string with summary text and extracted key points list.
    """
    result: SummaryResult = await summarize_document(text, style, max_length)

    if not result.success:
        return json.dumps({"success": False, "error": result.error})

    return json.dumps({
        "success": True,
        "summary": result.summary,
        "key_points": result.key_points,
        "word_count_original": result.word_count_original,
        "word_count_summary": result.word_count_summary,
        "compression_ratio": (
            round(result.word_count_summary / result.word_count_original, 3)
            if result.word_count_original > 0 else 0
        ),
    })


@mcp.tool()
async def extract_entities_tool(
    text: str,
    entity_types: str = "all",
) -> str:
    """
    Extract named entities from document text.

    Uses regex heuristics (no NLP model required). Good precision
    for structured entities (emails, URLs, dates, dollar amounts).
    Name/organization extraction is heuristic — may miss some.

    Args:
        text: Document text to analyze (from extract_text_tool).
        entity_types: Comma-separated list of types to extract, or 'all'.
                      Valid types: emails, urls, dates, numbers,
                                   names, organizations
                      Example: 'emails,dates,numbers'
                      Default: 'all' (extract everything)

    Returns:
        JSON string with entities dict grouped by type and total count.
    """
    # Parse entity_types string → list
    if entity_types.strip().lower() == "all":
        types_list = None  # tools.py uses None for all
    else:
        types_list = [t.strip() for t in entity_types.split(",") if t.strip()]

    result: EntityResult = await extract_entities(text, types_list)

    if not result.success:
        return json.dumps({"success": False, "error": result.error})

    return json.dumps({
        "success": True,
        "entities": result.entities,
        "total_found": result.total_found,
        "types_extracted": list(result.entities.keys()),
    })


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------

@mcp.resource("resource://document-agent/capabilities")
async def get_capabilities() -> str:
    return json.dumps({
        "agent": "document-agent",
        "version": "1.0.0",
        "tools": [
            {
                "name": "extract_text_tool",
                "supported_sources": ["pdf", "docx", "txt", "url"],
                "max_file_size_mb": 50,
            },
            {
                "name": "summarize_document_tool",
                "styles": ["concise", "detailed", "bullet", "executive"],
                "max_input_chars": 12000,
            },
            {
                "name": "extract_entities_tool",
                "entity_types": [
                    "emails", "urls", "dates", "numbers",
                    "names", "organizations",
                ],
                "method": "regex_heuristic",
            },
        ],
    })


# ---------------------------------------------------------------------------
# Gemini bridge
# ---------------------------------------------------------------------------

def get_gemini_tool_declarations() -> list[dict]:
    """
    Return tool declarations in Gemini format (NOT MCP inputSchema format).

    Key: uses "parameters" not "inputSchema".
    These are passed to GenerateContentConfig(tools=[...]).
    """
    return [
        {
            "name": "extract_text_tool",
            "description": (
                "Extract text from a PDF file, DOCX file, plain text file, "
                "or web URL. Returns the extracted text and metadata. "
                "Use this first before summarizing or analyzing a document."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": (
                            "File path (e.g. '/tmp/report.pdf') or URL "
                            "(e.g. 'https://example.com/article')"
                        ),
                    },
                    "source_type": {
                        "type": "string",
                        "description": (
                            "Type hint: 'auto' (default), 'pdf', 'docx', "
                            "'url', or 'txt'"
                        ),
                        "enum": ["auto", "pdf", "docx", "url", "txt"],
                    },
                },
                "required": ["source"],
            },
        },
        {
            "name": "summarize_document_tool",
            "description": (
                "Summarize document text. Call extract_text_tool first "
                "to get the text, then pass it here. Produces a summary "
                "and key bullet points."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Document text to summarize",
                    },
                    "style": {
                        "type": "string",
                        "description": (
                            "Summary style: 'concise' (default), 'detailed', "
                            "'bullet', or 'executive'"
                        ),
                        "enum": ["concise", "detailed", "bullet", "executive"],
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Target word count (default 300)",
                    },
                },
                "required": ["text"],
            },
        },
        {
            "name": "extract_entities_tool",
            "description": (
                "Extract named entities from document text: emails, URLs, "
                "dates, dollar amounts, person names, organizations. "
                "Uses regex heuristics — good for structured entities."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Document text to analyze",
                    },
                    "entity_types": {
                        "type": "string",
                        "description": (
                            "Comma-separated entity types or 'all'. "
                            "Valid: emails, urls, dates, numbers, "
                            "names, organizations"
                        ),
                    },
                },
                "required": ["text"],
            },
        },
    ]


async def execute_mcp_tool(name: str, args: dict) -> str:
    """
    Execute a tool by name with given args.

    Called by BaseA2AAgent.run_agent_with_tools() when Gemini
    makes a function call. Routes to the appropriate async tool function.

    Args:
        name: Tool name (must match Gemini declaration names)
        args: Tool arguments from Gemini function call

    Returns:
        String result to feed back to Gemini as tool response.
    """
    log.info("execute_mcp_tool", tool=name, args=list(args.keys()))

    try:
        if name == "extract_text_tool":
            return await extract_text_tool(
                source=args["source"],
                source_type=args.get("source_type", "auto"),
            )
        elif name == "summarize_document_tool":
            return await summarize_document_tool(
                text=args["text"],
                style=args.get("style", "concise"),
                max_length=args.get("max_length", 300),
            )
        elif name == "extract_entities_tool":
            return await extract_entities_tool(
                text=args["text"],
                entity_types=args.get("entity_types", "all"),
            )
        else:
            return json.dumps({
                "error": f"Unknown tool: {name}",
                "available": [
                    "extract_text_tool",
                    "summarize_document_tool",
                    "extract_entities_tool",
                ],
            })
    except KeyError as e:
        return json.dumps({"error": f"Missing required argument: {e}"})
    except Exception as e:
        log.exception("execute_mcp_tool_error", tool=name)
        return json.dumps({"error": f"Tool execution failed: {e}"})