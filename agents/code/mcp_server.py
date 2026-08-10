"""
Code Agent MCP server.

Three tools:
  analyze_code_tool  — AST + radon static analysis
  execute_code_tool  — sandboxed subprocess execution
  explain_code_tool  — Gemini explanation with suggestions

Bridge pattern identical to document agent.
"""

from __future__ import annotations

import json

import structlog
from mcp.server.mcpserver import MCPServer

from agents.code.tools import (
    AnalysisResult,
    ExecutionResult,
    ExplanationResult,
    analyze_code,
    execute_code,
    explain_code,
)

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

mcp = MCPServer(
    name="code-agent",
    title="Code Analysis and Execution Agent",
    description=(
        "Analyzes Python code structure and complexity, executes code in a "
        "sandboxed subprocess, and explains code with improvement suggestions."
    ),
    instructions=(
        "Use analyze_code_tool for static analysis without running code. "
        "Use execute_code_tool to run code and capture output. "
        "Use explain_code_tool to understand what code does. "
        "You can combine all three for comprehensive code review."
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Tool registrations
# ---------------------------------------------------------------------------

@mcp.tool()
async def analyze_code_tool(
    source: str,
    language: str = "python",
) -> str:
    """
    Analyze code structure and complexity without executing it.

    Provides: function count, class count, import list, cyclomatic complexity
    scores per function (radon), complexity grade (A=simple, F=complex),
    and missing docstring warnings.

    Args:
        source: Source code string to analyze.
        language: Programming language (default 'python').
                  Full analysis only for Python; other languages get line count.

    Returns:
        JSON string with structure metrics, complexity scores, and issue list.
    """
    result: AnalysisResult = await analyze_code(source, language)

    if not result.success:
        return json.dumps({"success": False, "error": result.error})

    return json.dumps({
        "success": True,
        "language": result.language,
        "metrics": {
            "line_count": result.line_count,
            "function_count": result.function_count,
            "class_count": result.class_count,
            "import_count": result.import_count,
            "avg_complexity": result.avg_complexity,
            "max_complexity": result.max_complexity,
            "complexity_grade": result.complexity_grade,
        },
        "functions": result.functions,
        "classes": result.classes,
        "imports": result.imports,
        "issues": result.issues,
    })


@mcp.tool()
async def execute_code_tool(
    source: str,
    stdin_input: str = "",
    timeout: int = 10,
) -> str:
    """
    Execute Python code in an isolated subprocess and return output.

    Security: fresh Python process per execution, 10s timeout,
    256MB memory limit, stdout/stderr captured not eval'd.
    Development sandbox — not for untrusted production use.

    Args:
        source: Python source code to execute.
        stdin_input: Optional string to pipe to stdin (for input() calls).
        timeout: Max execution seconds (1-30, default 10).

    Returns:
        JSON string with stdout, stderr, exit_code, timing, and timed_out flag.
    """
    result: ExecutionResult = await execute_code(source, stdin_input, timeout)

    if result.error and not result.stdout and not result.stderr:
        return json.dumps({"success": False, "error": result.error})

    return json.dumps({
        "success": result.success,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "execution_time_ms": result.execution_time_ms,
    })


@mcp.tool()
async def explain_code_tool(
    source: str,
    detail_level: str = "standard",
) -> str:
    """
    Explain what code does using AI analysis.

    Provides a natural language explanation, complexity summary,
    and actionable improvement suggestions.

    Args:
        source: Source code to explain.
        detail_level: Explanation depth —
                      'brief'    : 2-3 sentence overview
                      'standard' : section-by-section (default)
                      'detailed' : deep dive with improvement suggestions

    Returns:
        JSON string with explanation text, complexity summary, suggestions list.
    """
    result: ExplanationResult = await explain_code(source, detail_level)

    if not result.success:
        return json.dumps({"success": False, "error": result.error})

    return json.dumps({
        "success": True,
        "explanation": result.explanation,
        "complexity_summary": result.complexity_summary,
        "suggestions": result.suggestions,
    })


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------

@mcp.resource("resource://code-agent/capabilities")
async def get_capabilities() -> str:
    return json.dumps({
        "agent": "code-agent",
        "version": "1.0.0",
        "tools": [
            {
                "name": "analyze_code_tool",
                "languages": ["python"],
                "provides": [
                    "AST structure", "cyclomatic complexity",
                    "radon grades", "docstring warnings",
                ],
            },
            {
                "name": "execute_code_tool",
                "runtime": sys.version,
                "timeout_max": 30,
                "memory_limit_mb": 256,
                "sandbox": "subprocess isolation",
            },
            {
                "name": "explain_code_tool",
                "detail_levels": ["brief", "standard", "detailed"],
                "model": "gemini",
            },
        ],
    })


# ---------------------------------------------------------------------------
# Gemini bridge
# ---------------------------------------------------------------------------

def get_gemini_tool_declarations() -> list[dict]:
    """Tool declarations in Gemini format (parameters not inputSchema)."""
    return [
        {
            "name": "analyze_code_tool",
            "description": (
                "Statically analyze Python code structure and complexity. "
                "Returns function/class counts, import list, cyclomatic complexity "
                "per function (radon), letter grade (A=simple to F=complex), "
                "and missing docstring warnings. Does NOT execute the code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Python source code to analyze",
                    },
                    "language": {
                        "type": "string",
                        "description": "Programming language (default 'python')",
                    },
                },
                "required": ["source"],
            },
        },
        {
            "name": "execute_code_tool",
            "description": (
                "Execute Python code in an isolated subprocess. "
                "Captures stdout and stderr. Hard timeout of 10 seconds. "
                "Use for: testing code, running calculations, verifying output."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Python code to execute",
                    },
                    "stdin_input": {
                        "type": "string",
                        "description": "Optional text to pipe to stdin",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Max execution seconds (1-30, default 10)",
                    },
                },
                "required": ["source"],
            },
        },
        {
            "name": "explain_code_tool",
            "description": (
                "Explain what code does in plain English. "
                "Provides explanation, complexity summary, and improvement suggestions. "
                "Use when asked to review, understand, or document code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Source code to explain",
                    },
                    "detail_level": {
                        "type": "string",
                        "description": (
                            "'brief' (2-3 sentences), "
                            "'standard' (section-by-section, default), "
                            "'detailed' (deep dive with suggestions)"
                        ),
                        "enum": ["brief", "standard", "detailed"],
                    },
                },
                "required": ["source"],
            },
        },
    ]


async def execute_mcp_tool(name: str, args: dict) -> str:
    """Route Gemini function calls to the appropriate tool."""
    log.info("execute_mcp_tool", tool=name, args=list(args.keys()))

    try:
        if name == "analyze_code_tool":
            return await analyze_code_tool(
                source=args["source"],
                language=args.get("language", "python"),
            )
        elif name == "execute_code_tool":
            return await execute_code_tool(
                source=args["source"],
                stdin_input=args.get("stdin_input", ""),
                timeout=args.get("timeout", 10),
            )
        elif name == "explain_code_tool":
            return await explain_code_tool(
                source=args["source"],
                detail_level=args.get("detail_level", "standard"),
            )
        else:
            return json.dumps({
                "error": f"Unknown tool: {name}",
                "available": [
                    "analyze_code_tool",
                    "execute_code_tool",
                    "explain_code_tool",
                ],
            })
    except KeyError as e:
        return json.dumps({"error": f"Missing required argument: {e}"})
    except Exception as e:
        log.exception("execute_mcp_tool_error", tool=name)
        return json.dumps({"error": f"Tool execution failed: {e}"})


# Late import for resource endpoint — avoid circular at module level
import sys  # noqa: E402 (already imported in tools.py, fine here too)