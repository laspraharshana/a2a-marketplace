# agents/data_analysis/main.py
"""
Data Analysis Agent — A2A microservice on port 8002.

Inherits all A2A protocol handling from BaseA2AAgent.
Only defines: agent_card, tools, system prompt.

Usage:
    uvicorn agents.data_analysis.main:app --port 8002
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from agents.base.a2a_server import BaseA2AAgent
from agents.data_analysis.mcp_server import (
    execute_mcp_tool,
    get_gemini_tool_declarations,
)
from shared.a2a_types import AgentCard
from shared.config import get_settings

settings = get_settings()


class DataAnalysisAgent(BaseA2AAgent):
    """
    Data Analysis Agent.

    Capabilities:
    - Execute Python code (pandas, numpy, matplotlib)
    - Descriptive statistics on any numeric dataset
    - Chart generation (bar, line, scatter, histogram, pie)

    Inherits from BaseA2AAgent:
    - Full A2A + JSON-RPC protocol handling
    - Gemini tool-calling loop with fallback synthesis
    - Bearer token authentication
    - Task lifecycle management
    """

    agent_card = AgentCard(
        name="Data Analysis Agent",
        description=(
            "Analyzes data using Python, statistics, and visualization. "
            "Capable of executing custom analysis code, computing "
            "descriptive statistics, and generating charts."
        ),
        url=f"http://localhost:{settings.data_analysis_agent_port}",
        version="1.0.0",
        provider={"organization": "A2A Marketplace", "url": "http://localhost"},
        capabilities={"streaming": False, "pushNotifications": False},
        skills=[
            {
                "id": "python-execution",
                "name": "Python Code Execution",
                "description": "Run data analysis code with pandas/numpy",
                "tags": ["python", "pandas", "numpy", "code"],
                "examples": [
                    "Compute the mean of [1,2,3,4,5]",
                    "Run: import pandas as pd; df = pd.DataFrame({'x': [1,2,3]}); print(df.describe())",
                ],
            },
            {
                "id": "statistics",
                "name": "Statistical Analysis",
                "description": "Descriptive stats: mean, median, std, percentiles",
                "tags": ["statistics", "analysis", "math"],
                "examples": [
                    "What are the statistics for [10, 20, 30, 40, 50]?",
                    "Analyze the distribution of these prices",
                ],
            },
            {
                "id": "visualization",
                "name": "Chart Generation",
                "description": "Create bar, line, scatter, histogram, pie charts",
                "tags": ["chart", "visualization", "matplotlib"],
                "examples": [
                    "Create a bar chart of monthly sales",
                    "Plot a histogram of this dataset",
                ],
            },
        ],
        authentication={"schemes": ["bearer"]},
    )

    def get_tool_declarations(self) -> list[dict[str, Any]]:
        return get_gemini_tool_declarations()

    async def execute_tool(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        return await execute_mcp_tool(tool_name, tool_args)

    def get_system_prompt(self) -> str:
        return (
            "You are a Data Analysis Agent specializing in Python-based "
            "data analysis, statistics, and visualization.\n\n"
            "Your capabilities:\n"
            "1. run_python_code_tool — Execute Python with pandas/numpy/math\n"
            "2. statistical_analysis_tool — Compute descriptive statistics\n"
            "3. create_chart_tool — Generate charts as base64 PNG\n\n"
            "Guidelines:\n"
            "- For statistical questions, use statistical_analysis_tool first\n"
            "- For custom logic or transformations, use run_python_code_tool\n"
            "- For visualization requests, use create_chart_tool\n"
            "- Always interpret results and explain what they mean\n"
            "- When returning charts, note the base64 string is the image\n"
            "- Be precise with numbers, round appropriately\n"
        )


# ── Module-level app (Uvicorn entry point) ────────────────────────────────────

_agent = DataAnalysisAgent()
app: FastAPI = _agent.build_app()