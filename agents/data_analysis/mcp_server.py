# agents/data_analysis/mcp_server.py
"""
MCP server for Data Analysis Agent.

Three tools exposed:
  run_python_code      — Execute analysis code
  statistical_analysis — Descriptive stats
  create_chart         — Chart generation

Pattern: same internal bridge as Web Search Agent.
MCPServer for spec compliance, execute_mcp_tool()
bridges Gemini function calls to tool implementations.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from mcp.server.mcpserver import MCPServer

from agents.data_analysis.tools import (
    CodeResult,
    ChartResult,
    StatsResult,
    create_chart,
    run_python_code,
    statistical_analysis,
)

logger = structlog.get_logger(__name__)

# ── MCP Server instance ───────────────────────────────────────────────────────

mcp = MCPServer(
    name="data-analysis-agent",
    title="Data Analysis Agent",
    description=(
        "Executes Python code, computes statistics, "
        "and generates charts for data analysis tasks."
    ),
    instructions=(
        "Use run_python_code for custom analysis. "
        "Use statistical_analysis for quick descriptive stats. "
        "Use create_chart to visualize data as base64 PNG."
    ),
    version="1.0.0",
)


# ── MCP tool definitions ──────────────────────────────────────────────────────

@mcp.tool()
async def run_python_code_tool(code: str, timeout_seconds: int = 10) -> str:
    """
    Execute Python code for data analysis.
    Code runs in a restricted sandbox with pandas, numpy, math available.
    Print statements are captured and returned.
    Returns: execution output, computed variables, or error message.
    """
    result: CodeResult = await run_python_code(code, timeout_seconds)
    if result.success:
        parts = []
        if result.output:
            parts.append(f"Output:\n{result.output.strip()}")
        if result.variables:
            parts.append(f"Variables: {json.dumps(result.variables, indent=2)}")
        return "\n\n".join(parts) if parts else "Code executed successfully (no output)"
    return f"Error: {result.error}"


@mcp.tool()
async def statistical_analysis_tool(
    data_json: str,
    column: str = "",
) -> str:
    """
    Compute descriptive statistics on numeric data.
    data_json: JSON array. Either [1,2,3] or [{"col": 1}, {"col": 2}].
    column: required when data_json contains objects (pick which field).
    Returns: count, mean, median, std_dev, min, max, percentiles, IQR.
    """
    try:
        data = json.loads(data_json)
    except json.JSONDecodeError as exc:
        return f"Error: Invalid JSON — {exc}"

    result: StatsResult = await statistical_analysis(
        data, column=column if column else None
    )

    if result.success:
        lines = [f"**Statistical Analysis** ({result.stats['count']} points)"]
        for key, val in result.stats.items():
            if key == "count":
                continue
            lines.append(f"  {key}: {val}")
        return "\n".join(lines)

    return f"Error: {result.error}"


@mcp.tool()
async def create_chart_tool(
    chart_type: str,
    data_json: str,
    title: str = "",
    x_label: str = "",
    y_label: str = "",
) -> str:
    """
    Generate a chart and return as base64-encoded PNG.
    chart_type: bar, line, scatter, histogram, or pie.
    data_json: JSON object with chart data.
      bar/pie:       {"labels": [...], "values": [...]}
      line/scatter:  {"x": [...], "y": [...]}
      histogram:     {"values": [...], "bins": 20}
    Returns: base64 PNG string prefixed with 'data:image/png;base64,'
    """
    try:
        data = json.loads(data_json)
    except json.JSONDecodeError as exc:
        return f"Error: Invalid JSON — {exc}"

    result: ChartResult = await create_chart(
        chart_type=chart_type,
        data=data,
        title=title,
        x_label=x_label,
        y_label=y_label,
    )

    if result.success:
        return f"data:image/png;base64,{result.image_base64}"

    return f"Error: {result.error}"


# ── Gemini tool bridge ────────────────────────────────────────────────────────

def get_gemini_tool_declarations() -> list[dict[str, Any]]:
    """
    Return Gemini-compatible function declarations for all three tools.
    Note: key is "parameters" (Gemini format), not "inputSchema" (MCP format).
    """
    return [
        {
            "name": "run_python_code_tool",
            "description": (
                "Execute Python code for data analysis. "
                "Pandas, numpy, math, statistics available. "
                "Returns captured output and computed variables."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Max execution time (default: 10)",
                    },
                },
                "required": ["code"],
            },
        },
        {
            "name": "statistical_analysis_tool",
            "description": (
                "Compute descriptive statistics: mean, median, std_dev, "
                "percentiles, IQR, skewness. Input: JSON array of numbers "
                "or objects."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_json": {
                        "type": "string",
                        "description": (
                            "JSON array: [1,2,3] or "
                            '[{"price": 10}, {"price": 20}]'
                        ),
                    },
                    "column": {
                        "type": "string",
                        "description": (
                            "Field name to extract from objects. "
                            "Leave empty for flat arrays."
                        ),
                    },
                },
                "required": ["data_json"],
            },
        },
        {
            "name": "create_chart_tool",
            "description": (
                "Generate bar, line, scatter, histogram, or pie chart. "
                "Returns base64 PNG string for embedding."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "description": "bar | line | scatter | histogram | pie",
                    },
                    "data_json": {
                        "type": "string",
                        "description": (
                            "JSON chart data. "
                            "bar/pie: {labels:[...], values:[...]}. "
                            "line/scatter: {x:[...], y:[...]}. "
                            "histogram: {values:[...], bins:20}"
                        ),
                    },
                    "title": {
                        "type": "string",
                        "description": "Chart title (optional)",
                    },
                    "x_label": {
                        "type": "string",
                        "description": "X axis label (optional)",
                    },
                    "y_label": {
                        "type": "string",
                        "description": "Y axis label (optional)",
                    },
                },
                "required": ["chart_type", "data_json"],
            },
        },
    ]


async def execute_mcp_tool(tool_name: str, tool_args: dict[str, Any]) -> str:
    """
    Bridge: Gemini function call → MCP tool execution.

    Called by BaseA2AAgent.execute_tool() in the tool-calling loop.
    Returns string result for Gemini to incorporate.
    """
    logger.info("mcp_tool_dispatch", tool=tool_name)

    if tool_name == "run_python_code_tool":
        return await run_python_code_tool(**tool_args)

    elif tool_name == "statistical_analysis_tool":
        return await statistical_analysis_tool(**tool_args)

    elif tool_name == "create_chart_tool":
        return await create_chart_tool(**tool_args)

    else:
        return f"Error: Unknown tool '{tool_name}'"