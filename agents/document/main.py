"""
Document Agent — FastAPI microservice on port 8003.

Inherits all A2A protocol handling from BaseA2AAgent:
  - 5 standard endpoints (agent.json, health, tasks/send, get, cancel)
  - Registry auto-registration + heartbeat
  - JSON-RPC 2.0 request/response envelope
  - Bearer token auth on task endpoints

Only this file defines:
  - AgentCard (what this agent advertises)
  - Tool declarations (for Gemini function calling)
  - Tool execution dispatch (to mcp_server.py bridge)
  - System prompt (agent's persona and instructions)
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from agents.base.a2a_server import BaseA2AAgent
from agents.document.mcp_server import execute_mcp_tool, get_gemini_tool_declarations
from shared.a2a_types import AgentCapabilities, AgentCard, AgentProvider, AgentSkill
from shared.config import settings
from shared.logging_config import setup_logging


class DocumentAgent(BaseA2AAgent):
    """
    Document processing agent.

    Workflow for typical task:
      1. Gemini receives task (e.g. "summarize this PDF")
      2. Gemini calls extract_text_tool(source=...) via function calling
      3. execute_mcp_tool bridges call → tools.py → returns text
      4. Gemini calls summarize_document_tool(text=...) 
      5. execute_mcp_tool bridges → tools.py → Gemini nested call → summary
      6. Gemini composes final response from tool results
    """

    agent_card = AgentCard(
        name="document-agent",
        description=(
            "Processes documents from PDF files, DOCX files, and web URLs. "
            "Extracts text content, generates summaries in multiple styles, "
            "and identifies named entities including people, organizations, "
            "dates, dollar amounts, and contact information."
        ),
        url=f"http://localhost:{settings.document_agent_port}",
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
                id="extract-text",
                name="Text Extraction",
                description=(
                    "Extract raw text from PDF, DOCX, TXT files or web URLs. "
                    "Handles HTML cleanup for web pages, multi-page PDFs."
                ),
                examples=[
                    "Extract text from /tmp/report.pdf",
                    "Get content from https://example.com/article",
                    "Read the DOCX file at /tmp/contract.docx",
                ],
            ),
            AgentSkill(
                id="summarize",
                name="Document Summarization",
                description=(
                    "Summarize documents in concise, detailed, bullet-point, "
                    "or executive summary style."
                ),
                examples=[
                    "Summarize this PDF in bullet points",
                    "Give me an executive summary of this report",
                    "What are the key points of this article?",
                ],
            ),
            AgentSkill(
                id="extract-entities",
                name="Entity Extraction",
                description=(
                    "Extract named entities: emails, URLs, dates, dollar amounts, "
                    "person names, and organization names."
                ),
                examples=[
                    "Find all email addresses in this document",
                    "Extract dates and dollar amounts from this contract",
                    "Who are the people mentioned in this report?",
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
            "You are a Document Processing Agent specialized in extracting, "
            "analyzing, and summarizing content from documents and web pages.\n\n"
            "Your workflow:\n"
            "1. When given a file path or URL, ALWAYS call extract_text_tool first\n"
            "2. Once you have the text, use summarize_document_tool or "
            "extract_entities_tool based on what the user needs\n"
            "3. Present results clearly, citing the source and key statistics\n\n"
            "Tool guidance:\n"
            "- extract_text_tool: handles PDF, DOCX, TXT, and URLs automatically\n"
            "- summarize_document_tool: choose style based on context "
            "(concise for quick overview, executive for business docs, "
            "bullet for lists, detailed for research)\n"
            "- extract_entities_tool: useful for contracts, reports, "
            "news articles — finds contact info, dates, amounts\n\n"
            "Always report the source type and word count in your response."
        )


# ---------------------------------------------------------------------------
# App factory — module-level for uvicorn and test imports
# ---------------------------------------------------------------------------

setup_logging()
_agent = DocumentAgent()
app: FastAPI = _agent.build_app()


if __name__ == "__main__":
    uvicorn.run(
        "agents.document.main:app",
        host="0.0.0.0",
        port=settings.document_agent_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )