"""
Code Agent — FastAPI microservice on port 8004.

Inherits all A2A protocol handling from BaseA2AAgent.
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from agents.base.a2a_server import BaseA2AAgent
from agents.code.mcp_server import execute_mcp_tool, get_gemini_tool_declarations
from shared.a2a_types import AgentCapabilities, AgentCard, AgentProvider, AgentSkill
from shared.config import settings
from shared.logging_config import setup_logging


class CodeAgent(BaseA2AAgent):
    """
    Code analysis and execution agent.

    Typical workflows:
      "Analyze this code" → analyze_code_tool (static, no execution)
      "Run this code"     → execute_code_tool (subprocess sandbox)
      "Explain this code" → explain_code_tool (Gemini explanation)
      "Review this code"  → analyze + explain (two tool calls)
    """

    agent_card = AgentCard(
        name="code-agent",
        description=(
            "Analyzes Python code structure and complexity using AST and radon, "
            "executes code safely in an isolated subprocess with timeout and memory "
            "limits, and explains code with improvement suggestions using AI."
        ),
        url=f"http://localhost:{settings.code_agent_port}",
        version="1.0.0",
        provider=AgentProvider(
            organization="A2A Marketplace",
            url="http://localhost",
        ),
        capabilities=AgentCapabilities(
            streaming=False,
            pushNotifications=False,
            stateTransitionHistory=False,
        ),
        skills=[
            AgentSkill(
                id="analyze-code",
                name="Code Analysis",
                description=(
                    "Static analysis of Python code: function/class structure, "
                    "cyclomatic complexity with radon grades (A-F), import analysis, "
                    "and style issues. No code execution."
                ),
                examples=[
                    "Analyze the complexity of this Python function",
                    "How many functions and classes does this module have?",
                    "Check this code for missing docstrings",
                ],
            ),
            AgentSkill(
                id="execute-code",
                name="Code Execution",
                description=(
                    "Execute Python code in a sandboxed subprocess. "
                    "10-second timeout, 256MB memory limit. "
                    "Returns stdout, stderr, and exit code."
                ),
                examples=[
                    "Run this Python script and show the output",
                    "Execute this code and tell me the result",
                    "Test this function with sample inputs",
                ],
            ),
            AgentSkill(
                id="explain-code",
                name="Code Explanation",
                description=(
                    "AI-powered code explanation at brief, standard, or detailed level. "
                    "Includes complexity summary and improvement suggestions."
                ),
                examples=[
                    "Explain what this code does",
                    "Give me a detailed review of this function",
                    "What does this algorithm do and how can I improve it?",
                ],
            ),
        ],
    )

    def get_tool_declarations(self) -> list[dict]:
        return get_gemini_tool_declarations()

    async def execute_tool(self, tool_name: str, tool_args: dict) -> str:
        return await execute_mcp_tool(tool_name, tool_args)

    def get_system_prompt(self) -> str:
        return (
            "You are a Code Analysis and Execution Agent specialized in "
            "Python code review, execution, and explanation.\n\n"
            "Tool selection guide:\n"
            "- analyze_code_tool: use when asked to review structure, "
            "complexity, or quality WITHOUT running the code\n"
            "- execute_code_tool: use when asked to RUN, test, or verify "
            "code output. Always show stdout and stderr in your response.\n"
            "- explain_code_tool: use when asked to EXPLAIN or document code. "
            "Choose detail_level based on request: "
            "'brief' for quick overview, 'standard' for normal review, "
            "'detailed' for thorough analysis\n\n"
            "Combining tools:\n"
            "- For code review: analyze_code_tool + explain_code_tool\n"
            "- For debugging: execute_code_tool (see error) + explain_code_tool\n"
            "- For learning: explain_code_tool + execute_code_tool (demonstrate)\n\n"
            "Always report: complexity grade, any issues found, "
            "and concrete improvement suggestions."
        )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

setup_logging()
_agent = CodeAgent()
app: FastAPI = _agent.build_app()


if __name__ == "__main__":
    uvicorn.run(
        "agents.code.main:app",
        host="0.0.0.0",
        port=settings.code_agent_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )