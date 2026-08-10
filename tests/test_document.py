"""
Document Agent tests — 41 tests across 4 test classes.

KEY PATCH PATH RULE:
  Patch where the name is USED, not where it's defined.
  mcp_server.py does: from agents.document.tools import extract_text
  So the live reference lives at: agents.document.mcp_server.extract_text
  Patching agents.document.tools.extract_text has NO effect on mcp_server.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agents.document.main import _agent, app
from agents.document.mcp_server import (
    execute_mcp_tool,
    get_gemini_tool_declarations,
)
from agents.document.tools import (
    EntityResult,
    ExtractionResult,
    SummaryResult,
    extract_entities,
    extract_text,
    summarize_document,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_client():
    app.dependency_overrides[_agent.auth_dependency] = lambda: "test-token"
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def sample_text() -> str:
    return (
        "Acme Corporation, Inc. was founded on January 15, 2020 by John Smith "
        "and Jane Doe. The company raised $5,000,000 in Series A funding. "
        "Contact us at info@acme.com or visit https://acme.com. "
        "Our Q3 2024 revenue was $2.5M, up 15% from Q3 2023. "
        "Headquarters: 123 Main Street, San Francisco, CA 94102."
    )


@pytest.fixture
def long_text() -> str:
    return "This is a test document. " * 500  # ~2500 words


# ---------------------------------------------------------------------------
# TestMCPSchemas (7 tests) — unchanged, all passing
# ---------------------------------------------------------------------------

class TestMCPSchemas:
    def test_tool_declarations_returns_list(self):
        decls = get_gemini_tool_declarations()
        assert isinstance(decls, list)

    def test_tool_declarations_count(self):
        decls = get_gemini_tool_declarations()
        assert len(decls) == 3

    def test_tool_names(self):
        decls = get_gemini_tool_declarations()
        names = [d["name"] for d in decls]
        assert "extract_text_tool" in names
        assert "summarize_document_tool" in names
        assert "extract_entities_tool" in names

    def test_uses_parameters_not_input_schema(self):
        for decl in get_gemini_tool_declarations():
            assert "parameters" in decl, (
                f"{decl['name']} uses inputSchema instead of parameters"
            )
            assert "inputSchema" not in decl

    def test_each_tool_has_description(self):
        for decl in get_gemini_tool_declarations():
            assert "description" in decl
            assert len(decl["description"]) > 10

    def test_extract_text_required_params(self):
        decls = {d["name"]: d for d in get_gemini_tool_declarations()}
        params = decls["extract_text_tool"]["parameters"]
        assert "source" in params["required"]
        assert "source" in params["properties"]
        assert "source_type" in params["properties"]

    def test_summarize_required_params(self):
        decls = {d["name"]: d for d in get_gemini_tool_declarations()}
        params = decls["summarize_document_tool"]["parameters"]
        assert "text" in params["required"]
        assert "style" in params["properties"]
        assert "max_length" in params["properties"]


# ---------------------------------------------------------------------------
# TestToolExecution (14 tests) — all patch paths fixed
# ---------------------------------------------------------------------------

class TestToolExecution:

    # --- extract_text ---

    @pytest.mark.asyncio
    async def test_extract_text_url_success(self):
        """
        Patch agents.document.mcp_server.extract_text — NOT tools.extract_text.
        mcp_server imported it by name; that local binding is what runs.
        """
        mock_result = ExtractionResult(
            success=True,
            text="Hello world from the web.",
            source="url",
            page_count=1,
            word_count=5,
            char_count=25,
        )
        with patch(
            "agents.document.mcp_server.extract_text",  # ← FIXED
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "extract_text_tool", {"source": "https://example.com"}
            )
        result = json.loads(result_json)
        assert result["success"] is True
        assert "text" in result
        assert result["source_type"] == "url"
        assert result["word_count"] == 5

    @pytest.mark.asyncio
    async def test_extract_text_failure(self):
        mock_result = ExtractionResult(
            success=False,
            text="",
            source="pdf",
            error="File not found: /tmp/missing.pdf",
        )
        with patch(
            "agents.document.mcp_server.extract_text",  # ← FIXED
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "extract_text_tool",
                {"source": "/tmp/missing.pdf", "source_type": "pdf"},
            )
        result = json.loads(result_json)
        assert result["success"] is False
        assert "File not found" in result["error"]

    @pytest.mark.asyncio
    async def test_extract_text_truncates_long_text(self):
        """Text longer than 8000 chars is truncated in tool response."""
        long = "x" * 10_000
        mock_result = ExtractionResult(
            success=True,
            text=long,
            source="txt",
            page_count=1,
            word_count=1,
            char_count=10_000,
        )
        with patch(
            "agents.document.mcp_server.extract_text",  # ← FIXED
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "extract_text_tool", {"source": "/tmp/big.txt"}
            )
        result = json.loads(result_json)
        assert result["success"] is True
        assert len(result["text"]) == 8000
        assert result["text_truncated"] is True
        assert result["full_text_length"] == 10_000

    # --- summarize_document ---

    @pytest.mark.asyncio
    async def test_summarize_success(self):
        mock_result = SummaryResult(
            success=True,
            summary="This document covers key topics.",
            key_points=["Point 1", "Point 2", "Point 3"],
            word_count_original=500,
            word_count_summary=6,
        )
        with patch(
            "agents.document.mcp_server.summarize_document",  # ← FIXED
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "summarize_document_tool",
                {"text": "Some long text...", "style": "concise"},
            )
        result = json.loads(result_json)
        assert result["success"] is True
        assert result["summary"] == "This document covers key topics."
        assert len(result["key_points"]) == 3
        assert result["compression_ratio"] == round(6 / 500, 3)

    @pytest.mark.asyncio
    async def test_summarize_failure(self):
        mock_result = SummaryResult(success=False, error="API error")
        with patch(
            "agents.document.mcp_server.summarize_document",  # ← FIXED
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "summarize_document_tool", {"text": "text"}
            )
        result = json.loads(result_json)
        assert result["success"] is False
        assert result["error"] == "API error"

    @pytest.mark.asyncio
    async def test_summarize_default_style(self):
        """Default style is 'concise', default max_length is 300."""
        mock_result = SummaryResult(
            success=True,
            summary="Summary",
            key_points=[],
            word_count_original=100,
            word_count_summary=10,
        )
        with patch(
            "agents.document.mcp_server.summarize_document",  # ← FIXED
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            await execute_mcp_tool("summarize_document_tool", {"text": "text"})

        mock_fn.assert_called_once_with("text", "concise", 300)

    # --- extract_entities ---

    @pytest.mark.asyncio
    async def test_extract_entities_success(self, sample_text):
        mock_result = EntityResult(
            success=True,
            entities={
                "emails": ["info@acme.com"],
                "urls": ["https://acme.com"],
                "dates": ["January 15, 2020", "Q3 2024"],
                "numbers": ["$5,000,000", "$2.5M", "15%"],
                "names": ["John Smith", "Jane Doe"],
                "organizations": ["Acme Corporation"],
            },
            total_found=11,
        )
        with patch(
            "agents.document.mcp_server.extract_entities",  # ← FIXED
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "extract_entities_tool", {"text": sample_text}
            )
        result = json.loads(result_json)
        assert result["success"] is True
        assert result["total_found"] == 11
        assert "emails" in result["entities"]
        assert "info@acme.com" in result["entities"]["emails"]

    @pytest.mark.asyncio
    async def test_extract_entities_filtered_types(self):
        """entity_types string 'emails,urls' → list ['emails', 'urls'] passed to tool."""
        mock_result = EntityResult(
            success=True,
            entities={"emails": ["test@example.com"]},
            total_found=1,
        )
        with patch(
            "agents.document.mcp_server.extract_entities",  # ← FIXED
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            await execute_mcp_tool(
                "extract_entities_tool",
                {"text": "some text", "entity_types": "emails,urls"},
            )

        # mock was called — call_args is not None
        assert mock_fn.call_args is not None
        call_args = mock_fn.call_args
        assert call_args[0][1] == ["emails", "urls"]

    @pytest.mark.asyncio
    async def test_extract_entities_all_type(self):
        """'all' entity_types → None passed to extract_entities."""
        mock_result = EntityResult(success=True, entities={}, total_found=0)
        with patch(
            "agents.document.mcp_server.extract_entities",  # ← FIXED
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            await execute_mcp_tool(
                "extract_entities_tool",
                {"text": "text", "entity_types": "all"},
            )

        assert mock_fn.call_args is not None
        call_args = mock_fn.call_args
        assert call_args[0][1] is None

    # --- execute_mcp_tool routing ---

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        result_json = await execute_mcp_tool("nonexistent_tool", {})
        result = json.loads(result_json)
        assert "error" in result
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_required_arg_returns_error(self):
        result_json = await execute_mcp_tool("extract_text_tool", {})
        result = json.loads(result_json)
        assert "error" in result

    # --- tools.py unit tests (call tools.py directly — no patch needed) ---

    @pytest.mark.asyncio
    async def test_extract_entities_emails(self, sample_text):
        result = await extract_entities(sample_text, ["emails"])
        assert result.success is True
        assert "info@acme.com" in result.entities["emails"]

    @pytest.mark.asyncio
    async def test_extract_entities_urls(self, sample_text):
        result = await extract_entities(sample_text, ["urls"])
        assert result.success is True
        assert any("acme.com" in u for u in result.entities["urls"])

    @pytest.mark.asyncio
    async def test_extract_entities_numbers(self, sample_text):
        result = await extract_entities(sample_text, ["numbers"])
        assert result.success is True
        nums = result.entities["numbers"]
        assert any("5,000,000" in n for n in nums)

    @pytest.mark.asyncio
    async def test_extract_entities_empty_text(self):
        result = await extract_entities("", ["emails"])
        assert result.success is False
        assert "No text" in result.error


# ---------------------------------------------------------------------------
# TestBaseAgent (6 tests) — unchanged, all passing
# ---------------------------------------------------------------------------

class TestBaseAgent:
    def test_agent_card_exists(self):
        assert _agent.agent_card is not None

    def test_agent_card_name(self):
        assert _agent.agent_card.name == "Document Agent"

    def test_agent_card_skills_count(self):
        assert len(_agent.agent_card.skills) == 3

    def test_agent_card_skill_ids(self):
        skill_ids = [s.id for s in _agent.agent_card.skills]
        assert "extract-text" in skill_ids
        assert "summarize" in skill_ids
        assert "extract-entities" in skill_ids

    def test_get_tool_declarations_returns_three(self):
        decls = _agent.get_tool_declarations()
        assert len(decls) == 3

    def test_system_prompt_not_empty(self):
        prompt = _agent.get_system_prompt()
        assert len(prompt) > 50
        assert "extract_text_tool" in prompt


# ---------------------------------------------------------------------------
# TestA2AEndpoints (13 tests) — unchanged, all passing
# ---------------------------------------------------------------------------

class TestA2AEndpoints:

    @pytest.mark.asyncio
    async def test_agent_card_public(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/.well-known/agent.json")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Document Agent"
        assert len(data["skills"]) == 3

    @pytest.mark.asyncio
    async def test_health_public(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_tasks_send_requires_auth(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/a2a/tasks/send",
                json={"jsonrpc": "2.0", "id": "1", "method": "tasks/send",
                      "params": {"message": {"role": "user", "parts": []}}},
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_tasks_send_success(self, auth_client):
        mock_response = MagicMock()
        mock_response.text = "I extracted the text successfully."
        mock_response.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(
                text="I extracted the text successfully.",
                function_call=None,
            )]))
        ]
        with patch("agents.base.a2a_server.asyncio.to_thread",
                   new_callable=AsyncMock, return_value=mock_response):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/a2a/tasks/send",
                    headers={"Authorization": "Bearer test-token"},
                    json={
                        "jsonrpc": "2.0",
                        "id": "test-1",
                        "method": "tasks/send",
                        "params": {
                            "message": {
                                "role": "user",
                                "parts": [{"text": "Extract text from https://example.com"}],
                            }
                        },
                    },
                )
        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "test-1"
        assert "result" in data
        assert data["result"]["status"]["state"] == "completed"

    @pytest.mark.asyncio
    async def test_tasks_send_returns_task_id(self, auth_client):
        mock_response = MagicMock()
        mock_response.text = "Done."
        mock_response.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(
                text="Done.", function_call=None,
            )]))
        ]
        with patch("agents.base.a2a_server.asyncio.to_thread",
                   new_callable=AsyncMock, return_value=mock_response):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/a2a/tasks/send",
                    headers={"Authorization": "Bearer test-token"},
                    json={
                        "jsonrpc": "2.0", "id": "1", "method": "tasks/send",
                        "params": {"message": {"role": "user",
                                               "parts": [{"text": "Summarize this"}]}},
                    },
                )
        task = response.json()["result"]
        assert "id" in task
        assert len(task["id"]) > 0

    @pytest.mark.asyncio
    async def test_tasks_get_not_found(self, auth_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/a2a/tasks/get",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "jsonrpc": "2.0", "id": "1", "method": "tasks/get",
                    "params": {"id": "nonexistent-task-id"},
                },
            )
        assert response.status_code == 200
        assert "error" in response.json()
        assert response.json()["error"]["code"] == -32001

    @pytest.mark.asyncio
    async def test_tasks_get_found(self, auth_client):
        mock_response = MagicMock()
        mock_response.text = "Result text."
        mock_response.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(
                text="Result text.", function_call=None,
            )]))
        ]
        with patch("agents.base.a2a_server.asyncio.to_thread",
                   new_callable=AsyncMock, return_value=mock_response):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                send_resp = await client.post(
                    "/a2a/tasks/send",
                    headers={"Authorization": "Bearer test-token"},
                    json={
                        "jsonrpc": "2.0", "id": "1", "method": "tasks/send",
                        "params": {"message": {"role": "user",
                                               "parts": [{"text": "test"}]}},
                    },
                )
                task_id = send_resp.json()["result"]["id"]

                get_resp = await client.post(
                    "/a2a/tasks/get",
                    headers={"Authorization": "Bearer test-token"},
                    json={
                        "jsonrpc": "2.0", "id": "2", "method": "tasks/get",
                        "params": {"id": task_id},
                    },
                )
        assert get_resp.status_code == 200
        assert get_resp.json()["result"]["id"] == task_id

    @pytest.mark.asyncio
    async def test_tasks_cancel_not_found(self, auth_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/a2a/tasks/cancel",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "jsonrpc": "2.0", "id": "1", "method": "tasks/cancel",
                    "params": {"id": "no-such-task"},
                },
            )
        assert response.status_code == 200
        assert "error" in response.json()

    @pytest.mark.asyncio
    async def test_tool_call_round_trip(self, auth_client):
        """
        call_count == 3:
          call 1 → Gemini returns function_call
          call 2 → tool's asyncio.to_thread (extract_text_tool internal)
          call 3 → Gemini returns final text
        """
        round1 = MagicMock()
        round1.text = None
        round1.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(
                text=None,
                function_call=MagicMock(
                    name="extract_text_tool",
                    args={"source": "https://example.com"},
                ),
            )]))
        ]

        round2 = MagicMock()
        round2.text = "The page contains information about widgets."
        round2.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(
                text="The page contains information about widgets.",
                function_call=None,
            )]))
        ]

        tool_response = json.dumps({
            "success": True,
            "text": "Widget information here.",
            "source_type": "url",
            "word_count": 3,
            "char_count": 25,
            "page_count": 1,
            "text_truncated": False,
            "full_text_length": 25,
            "summary_line": "Source: url | Pages: 1 | Words: 3 | Chars: 25",
        })

        call_count = 0

        async def mock_to_thread(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return round1
            elif call_count == 2:
                return tool_response
            else:
                return round2

        with patch("agents.base.a2a_server.asyncio.to_thread",
                   side_effect=mock_to_thread):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/a2a/tasks/send",
                    headers={"Authorization": "Bearer test-token"},
                    json={
                        "jsonrpc": "2.0", "id": "tool-test",
                        "method": "tasks/send",
                        "params": {"message": {"role": "user", "parts": [
                            {"text": "Extract text from https://example.com"}
                        ]}},
                    },
                )

        assert response.status_code == 200
        assert call_count == 3
        task = response.json()["result"]
        assert task["status"]["state"] == "completed"
        assert "widgets" in task["artifacts"][0]["parts"][0]["text"]

    @pytest.mark.asyncio
    async def test_invalid_json_rpc_returns_error(self, auth_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/a2a/tasks/send",
                headers={"Authorization": "Bearer test-token"},
                json={"not": "jsonrpc"},
            )
        assert response.status_code == 200
        assert "error" in response.json()

    @pytest.mark.asyncio
    async def test_agent_card_has_correct_url(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/.well-known/agent.json")
        assert "8003" in response.json()["url"]

    @pytest.mark.asyncio
    async def test_agent_card_provider(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/.well-known/agent.json")
        assert response.json()["provider"]["organization"] == "A2A Marketplace"

    @pytest.mark.asyncio
    async def test_wrong_bearer_token_rejected(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/a2a/tasks/send",
                headers={"Authorization": "Bearer wrong-token"},
                json={"jsonrpc": "2.0", "id": "1", "method": "tasks/send",
                      "params": {"message": {"role": "user", "parts": []}}},
            )
        assert response.status_code == 401