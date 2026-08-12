# tests/test_web_search_mcp.py
"""
Tests for Web Search Agent.
Layer 1: MCP schemas
Layer 2: Tool execution  
Layer 3: A2A endpoints
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from agents.web_search.tools import (
    SearchResult,
    NewsResult,
    FetchResult,
)
from agents.web_search.mcp_server import (
    execute_mcp_tool,
    get_gemini_tool_declarations,
)
from agents.web_search.main import app, verify_bearer_token


# ══════════════════════════════════════════════════════════════
# LAYER 1: MCP SCHEMA TESTS
# ══════════════════════════════════════════════════════════════

class TestMCPSchemas:

    def test_gemini_declarations_returns_three_tools(self):
        declarations = get_gemini_tool_declarations()
        assert len(declarations) == 3

    def test_gemini_declarations_tool_names(self):
        declarations = get_gemini_tool_declarations()
        names = {d["name"] for d in declarations}
        assert names == {
            "search_web_tool",
            "get_news_tool",
            "fetch_url_tool"
        }

    def test_gemini_declarations_use_parameters_key(self):
        declarations = get_gemini_tool_declarations()
        for decl in declarations:
            assert "parameters" in decl
            assert "inputSchema" not in decl

    def test_each_declaration_has_description(self):
        declarations = get_gemini_tool_declarations()
        for decl in declarations:
            assert "description" in decl
            assert len(decl["description"]) > 20

    def test_search_web_requires_query(self):
        declarations = get_gemini_tool_declarations()
        search = next(
            d for d in declarations
            if d["name"] == "search_web_tool"
        )
        assert "query" in search["parameters"]["required"]

    def test_get_news_requires_topic(self):
        declarations = get_gemini_tool_declarations()
        news = next(
            d for d in declarations
            if d["name"] == "get_news_tool"
        )
        assert "topic" in news["parameters"]["required"]

    def test_fetch_url_requires_url(self):
        declarations = get_gemini_tool_declarations()
        fetch = next(
            d for d in declarations
            if d["name"] == "fetch_url_tool"
        )
        assert "url" in fetch["parameters"]["required"]


# ══════════════════════════════════════════════════════════════
# LAYER 2: TOOL EXECUTION TESTS
# ══════════════════════════════════════════════════════════════

class TestToolExecution:

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error_string(self):
        result = await execute_mcp_tool(
            "nonexistent_tool", {"arg": "value"}
        )
        assert isinstance(result, str)
        assert "Error" in result
        assert "Unknown tool" in result

    @pytest.mark.asyncio
    async def test_missing_required_arg_returns_error(self):
        result = await execute_mcp_tool("search_web_tool", {})
        assert isinstance(result, str)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_search_web_tool_formats_results(self):
        mock_results = [
            SearchResult(
                title="Quantum Computing in Singapore",
                url="https://example.com/quantum",
                snippet="Singapore leads in quantum research",
                source="duckduckgo"
            ),
            SearchResult(
                title="Second Result Title",
                url="https://example.com/second",
                snippet="Another relevant snippet",
                source="duckduckgo"
            )
        ]
        with patch(
            "agents.web_search.mcp_server.search_web",
            new_callable=AsyncMock,
            return_value=mock_results
        ):
            result = await execute_mcp_tool(
                "search_web_tool",
                {"query": "quantum computing Singapore",
                 "max_results": 2}
            )
        assert "Quantum Computing in Singapore" in result
        assert "https://example.com/quantum" in result
        assert "[1]" in result
        assert "[2]" in result
        assert "Found 2 results" in result

    @pytest.mark.asyncio
    async def test_get_news_tool_formats_articles(self):
        mock_news = [
            NewsResult(
                title="AI Funding Round Announced",
                url="https://news.example.com/ai-funding",
                snippet="Major AI startup secures funding",
                published_date="2025-07-15",
                source_name="TechCrunch"
            )
        ]
        with patch(
            "agents.web_search.mcp_server.get_news",
            new_callable=AsyncMock,
            return_value=mock_news
        ):
            result = await execute_mcp_tool(
                "get_news_tool",
                {"topic": "AI funding", "max_results": 1}
            )
        assert "AI Funding Round Announced" in result
        assert "TechCrunch" in result
        assert "2025-07-15" in result
        assert "Found 1 articles" in result

    @pytest.mark.asyncio
    async def test_fetch_url_tool_formats_content(self):
        mock_result = FetchResult(
            url="https://example.com/article",
            content="This is the full article content.",
            title="Example Article Title",
            status_code=200
        )
        with patch(
            "agents.web_search.mcp_server.fetch_url",
            new_callable=AsyncMock,
            return_value=mock_result
        ):
            result = await execute_mcp_tool(
                "fetch_url_tool",
                {"url": "https://example.com/article"}
            )
        assert "Example Article Title" in result
        assert "https://example.com/article" in result
        assert "200" in result
        assert "This is the full article content." in result

    @pytest.mark.asyncio
    async def test_empty_search_results_handled(self):
        with patch(
            "agents.web_search.mcp_server.search_web",
            new_callable=AsyncMock,
            return_value=[]
        ):
            result = await execute_mcp_tool(
                "search_web_tool",
                {"query": "obscure topic xyz999"}
            )
        assert "No search results found" in result

    @pytest.mark.asyncio
    async def test_empty_news_results_handled(self):
        with patch(
            "agents.web_search.mcp_server.get_news",
            new_callable=AsyncMock,
            return_value=[]
        ):
            result = await execute_mcp_tool(
                "get_news_tool",
                {"topic": "obscure topic xyz999"}
            )
        assert "No news articles found" in result


# ══════════════════════════════════════════════════════════════
# LAYER 3: A2A ENDPOINT TESTS
# ══════════════════════════════════════════════════════════════

# ── Auth bypass for tests that need authenticated access ──────
# This overrides FastAPI's dependency injection.
# Instead of checking a real token, we just return "test-token".
# This is the CORRECT FastAPI pattern for testing auth endpoints.

def override_verify_bearer_token() -> str:
    """
    Test override: skip real token verification.
    Returns a fake token string so the endpoint
    treats the request as authenticated.
    """
    return "test-token"


class TestA2AEndpoints:

    @pytest_asyncio.fixture
    async def client(self):
        """
        Unauthenticated client.
        Use for testing endpoints that require NO auth.
        """
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as ac:
            yield ac

    @pytest_asyncio.fixture
    async def auth_client(self):
        """
        Authenticated client using dependency override.
        Use for testing endpoints that require auth.

        FastAPI dependency_overrides replaces
        verify_bearer_token with our test stub
        for the duration of the test.
        """
        app.dependency_overrides[verify_bearer_token] = \
            override_verify_bearer_token
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as ac:
            yield ac
        # IMPORTANT: clean up override after test
        app.dependency_overrides.clear()

    # ── Agent Card (public) ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_agent_card_is_public(self, client):
        """Agent card needs no auth"""
        response = await client.get("/.well-known/agent.json")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_agent_card_required_fields(self, client):
        response = await client.get("/.well-known/agent.json")
        data = response.json()
        assert data["name"] == "web-search-agent"
        assert "description" in data
        assert "url" in data
        assert "skills" in data
        assert "capabilities" in data

    @pytest.mark.asyncio
    async def test_agent_card_has_three_skills(self, client):
        response = await client.get("/.well-known/agent.json")
        data = response.json()
        assert len(data["skills"]) == 3

    @pytest.mark.asyncio
    async def test_agent_card_skills_have_required_fields(
        self, client
    ):
        response = await client.get("/.well-known/agent.json")
        data = response.json()
        for skill in data["skills"]:
            assert "id" in skill
            assert "name" in skill
            assert "description" in skill

    # ── Health (public) ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_health_returns_healthy(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["agent"] == "web-search-agent"

    # ── Auth rejection tests (unauthenticated client) ─────────

    @pytest.mark.asyncio
    async def test_task_endpoint_rejects_missing_auth(
        self, client
    ):
        """No auth header → 401"""
        response = await client.post(
            "/a2a/tasks/send",
            json={
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {}
            }
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_task_endpoint_rejects_wrong_token(
        self, client
    ):
        """Wrong token → 401"""
        response = await client.post(
            "/a2a/tasks/send",
            headers={"Authorization": "Bearer wrong-token"},
            json={
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {
                    "id": "task-001",
                    "message": {
                        "role": "user",
                        "parts": [
                            {"type": "text", "text": "test"}
                        ]
                    }
                }
            }
        )
        assert response.status_code == 401

    # ── Task lifecycle tests (auth_client fixture) ────────────

    @pytest.mark.asyncio
    async def test_send_task_returns_completed(self, auth_client):
        """Full happy path: send → completed with artifact"""
        with patch(
            "agents.web_search.main.run_agent_with_tools",
            new_callable=AsyncMock,
            return_value=(
                "Found 3 quantum computing companies "
                "in Singapore."
            )
        ):
            response = await auth_client.post(
                "/a2a/tasks/send",
                json={
                    "jsonrpc": "2.0",
                    "id": "req-001",
                    "method": "tasks/send",
                    "params": {
                        "id": "task-001",
                        "message": {
                            "role": "user",
                            "parts": [{
                                "type": "text",
                                "text": "Search quantum computing"
                            }]
                        }
                    }
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "req-001"
        assert "result" in data

        result = data["result"]
        assert result["id"] == "task-001"
        assert result["status"]["state"] == "completed"
        assert "artifacts" in result
        assert len(result["artifacts"]) == 1

        text = result["artifacts"][0]["parts"][0]["text"]
        assert "quantum computing" in text.lower()

    @pytest.mark.asyncio
    async def test_get_task_after_send(self, auth_client):
        """Task can be retrieved by ID after sending"""
        task_id = "task-get-test-001"

        with patch(
            "agents.web_search.main.run_agent_with_tools",
            new_callable=AsyncMock,
            return_value="Search completed successfully."
        ):
            await auth_client.post(
                "/a2a/tasks/send",
                json={
                    "jsonrpc": "2.0",
                    "id": "req-002",
                    "method": "tasks/send",
                    "params": {
                        "id": task_id,
                        "message": {
                            "role": "user",
                            "parts": [{
                                "type": "text",
                                "text": "test task"
                            }]
                        }
                    }
                }
            )

        response = await auth_client.post(
            "/a2a/tasks/get",
            json={
                "jsonrpc": "2.0",
                "id": "req-003",
                "method": "tasks/get",
                "params": {"id": task_id}
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["id"] == task_id
        assert data["result"]["status"]["state"] == "completed"

    @pytest.mark.asyncio
    async def test_get_nonexistent_task_returns_error(
        self, auth_client
    ):
        """
        Non-existent task → HTTP 200, error in JSON-RPC body.
        JSON-RPC errors are always HTTP 200 with error in body.
        Error code -32001 = TASK_NOT_FOUND.
        """
        response = await auth_client.post(
            "/a2a/tasks/get",
            json={
                "jsonrpc": "2.0",
                "id": "req-004",
                "method": "tasks/get",
                "params": {"id": "task-does-not-exist"}
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32001

    @pytest.mark.asyncio
    async def test_cancel_task(self, auth_client):
        """Task can be canceled"""
        task_id = "task-cancel-test-001"

        with patch(
            "agents.web_search.main.run_agent_with_tools",
            new_callable=AsyncMock,
            return_value="Done."
        ):
            await auth_client.post(
                "/a2a/tasks/send",
                json={
                    "jsonrpc": "2.0",
                    "id": "req-005",
                    "method": "tasks/send",
                    "params": {
                        "id": task_id,
                        "message": {
                            "role": "user",
                            "parts": [{
                                "type": "text",
                                "text": "test"
                            }]
                        }
                    }
                }
            )

        response = await auth_client.post(
            "/a2a/tasks/cancel",
            json={
                "jsonrpc": "2.0",
                "id": "req-006",
                "method": "tasks/cancel",
                "params": {"id": task_id}
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["status"]["state"] == "canceled"