# tests/test_data_analysis.py
"""
Data Analysis Agent test suite.

Structure mirrors test_web_search_mcp.py:
  TestMCPSchemas      — Tool declaration structure
  TestToolExecution   — Tool logic (mocked where needed)
  TestBaseAgent       — BaseA2AAgent logic
  TestA2AEndpoints    — HTTP endpoint behavior

All Gemini calls mocked — tests run without API keys.
Tool logic tested directly (no LLM needed).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agents.data_analysis.main import _agent, app
from agents.data_analysis.mcp_server import (
    execute_mcp_tool,
    get_gemini_tool_declarations,
)
from agents.data_analysis.tools import (
    create_chart,
    run_python_code,
    statistical_analysis,
)
from shared.a2a_types import TaskState


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    """Unauthenticated client — for testing auth rejection."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client():
    """Authenticated client — dependency override bypasses token check."""
    app.dependency_overrides[_agent.auth_dependency] = lambda: "test-token"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


def make_rpc_request(method: str, params: dict[str, Any], rpc_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": method,
        "params": params,
    }


def make_task_send_body(text: str, rpc_id: int = 1) -> dict:
    return make_rpc_request(
        method="tasks/send",
        params={
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": text}],
            }
        },
        rpc_id=rpc_id,
    )


# ─────────────────────────────────────────────
# TestMCPSchemas
# ─────────────────────────────────────────────

class TestMCPSchemas:
    """Verify tool declarations have correct structure for Gemini."""

    def test_returns_three_tools(self):
        tools = get_gemini_tool_declarations()
        assert len(tools) == 3

    def test_all_tools_have_required_keys(self):
        tools = get_gemini_tool_declarations()
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool  # Gemini format (not inputSchema)

    def test_run_python_code_schema(self):
        tools = get_gemini_tool_declarations()
        tool = next(t for t in tools if t["name"] == "run_python_code_tool")
        params = tool["parameters"]
        assert "code" in params["properties"]
        assert "code" in params["required"]
        # timeout_seconds is optional
        assert "timeout_seconds" not in params.get("required", [])

    def test_statistical_analysis_schema(self):
        tools = get_gemini_tool_declarations()
        tool = next(t for t in tools if t["name"] == "statistical_analysis_tool")
        params = tool["parameters"]
        assert "data_json" in params["properties"]
        assert "data_json" in params["required"]
        assert "column" in params["properties"]

    def test_create_chart_schema(self):
        tools = get_gemini_tool_declarations()
        tool = next(t for t in tools if t["name"] == "create_chart_tool")
        params = tool["parameters"]
        assert "chart_type" in params["required"]
        assert "data_json" in params["required"]
        # Optional fields
        assert "title" in params["properties"]
        assert "x_label" in params["properties"]
        assert "y_label" in params["properties"]

    def test_no_input_schema_key(self):
        """Gemini uses 'parameters', not 'inputSchema'."""
        tools = get_gemini_tool_declarations()
        for tool in tools:
            assert "inputSchema" not in tool

    def test_chart_types_documented(self):
        tools = get_gemini_tool_declarations()
        tool = next(t for t in tools if t["name"] == "create_chart_tool")
        chart_type_desc = tool["parameters"]["properties"]["chart_type"]["description"]
        for ct in ["bar", "line", "scatter", "histogram", "pie"]:
            assert ct in chart_type_desc


# ─────────────────────────────────────────────
# TestToolExecution
# ─────────────────────────────────────────────

class TestToolExecution:
    """Test tool implementations directly (no LLM)."""

    @pytest.mark.asyncio
    async def test_run_python_code_basic(self):
        result = await run_python_code("print('hello world')")
        assert result.success is True
        assert "hello world" in result.output

    @pytest.mark.asyncio
    async def test_run_python_code_captures_variables(self):
        result = await run_python_code("x = 42\ny = x * 2")
        assert result.success is True
        assert result.variables.get("x") == 42
        assert result.variables.get("y") == 84

    @pytest.mark.asyncio
    async def test_run_python_code_math(self):
        # math is pre-loaded — no import needed
        result = await run_python_code(
        "result = math.sqrt(144)\nprint(result)"
        )
        assert result.success is True
        assert "12.0" in result.output
    

    @pytest.mark.asyncio
    async def test_run_python_code_syntax_error(self):
        result = await run_python_code("def broken(:\n    pass")
        assert result.success is False
        assert result.error  # Has error message

    @pytest.mark.asyncio
    async def test_run_python_code_blocks_dangerous(self):
        """Sandbox should prevent os module access."""
        result = await run_python_code("import os; os.system('ls')")
        assert result.success is False  # NameError: name 'os' not defined

    @pytest.mark.asyncio
    async def test_statistical_analysis_flat_list(self):
        result = await statistical_analysis([10.0, 20.0, 30.0, 40.0, 50.0])
        assert result.success is True
        assert result.stats["mean"] == 30.0
        assert result.stats["count"] == 5
        assert result.stats["min"] == 10.0
        assert result.stats["max"] == 50.0

    @pytest.mark.asyncio
    async def test_statistical_analysis_with_column(self):
        data = [{"price": 100}, {"price": 200}, {"price": 300}]
        result = await statistical_analysis(data, column="price")
        assert result.success is True
        assert result.stats["mean"] == 200.0
        assert result.stats["count"] == 3

    @pytest.mark.asyncio
    async def test_statistical_analysis_too_few_points(self):
        result = await statistical_analysis([42.0])
        assert result.success is False
        assert "2" in result.error  # "Need at least 2"

    @pytest.mark.asyncio
    async def test_create_chart_bar(self):
        result = await create_chart(
            chart_type="bar",
            data={"labels": ["A", "B", "C"], "values": [10, 20, 30]},
            title="Test Bar Chart",
        )
        assert result.success is True
        assert result.image_base64  # Non-empty base64 string
        assert result.chart_type == "bar"

    @pytest.mark.asyncio
    async def test_create_chart_line(self):
        result = await create_chart(
            chart_type="line",
            data={"x": [1, 2, 3, 4], "y": [10, 20, 15, 25]},
        )
        assert result.success is True
        assert result.image_base64

    @pytest.mark.asyncio
    async def test_create_chart_histogram(self):
        import random
        values = [random.gauss(50, 10) for _ in range(100)]
        result = await create_chart(
            chart_type="histogram",
            data={"values": values, "bins": 15},
        )
        assert result.success is True
        assert result.image_base64

    @pytest.mark.asyncio
    async def test_create_chart_invalid_type(self):
        result = await create_chart(
            chart_type="radar",  # Not supported
            data={"x": [1, 2], "y": [3, 4]},
        )
        assert result.success is False
        assert "Unknown chart type" in result.error

    @pytest.mark.asyncio
    async def test_create_chart_missing_key(self):
        result = await create_chart(
            chart_type="bar",
            data={"labels": ["A", "B"]},  # Missing "values"
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_dispatch(self):
        result = await execute_mcp_tool(
            "statistical_analysis_tool",
            {"data_json": "[1, 2, 3, 4, 5]"},
        )
        assert "mean" in result
        assert "30" not in result  # Mean of 1-5 is 3.0

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_unknown(self):
        result = await execute_mcp_tool("nonexistent_tool", {})
        assert "Error" in result
        assert "Unknown tool" in result


# ─────────────────────────────────────────────
# TestBaseAgent
# ─────────────────────────────────────────────

class TestBaseAgent:
    """Test BaseA2AAgent logic directly (task store, tool loop)."""

    def test_task_lifecycle(self):
        """Task transitions: submitted → working → completed."""
        from shared.a2a_types import Message, TextPart
        from agents.data_analysis.main import DataAnalysisAgent

        agent = DataAnalysisAgent()
        msg = Message(role="user", parts=[TextPart(type="text", text="test")])
        task = agent._create_task("rpc-1", msg)

        assert task.status.state == TaskState.SUBMITTED
        task_id = task.id

        agent._update_task_working(task_id)
        assert agent._get_task(task_id).status.state == TaskState.WORKING

        agent._complete_task(task_id, "result here")
        completed = agent._get_task(task_id)
        assert completed.status.state == TaskState.COMPLETED
        assert completed.artifacts[0].parts[0].text == "result here"

    def test_task_cancel_working(self):
        from shared.a2a_types import Message, TextPart
        from agents.data_analysis.main import DataAnalysisAgent

        agent = DataAnalysisAgent()
        msg = Message(role="user", parts=[TextPart(type="text", text="test")])
        task = agent._create_task("rpc-2", msg)
        agent._update_task_working(task.id)

        cancelled = agent._cancel_task(task.id)
        assert cancelled is True
        assert agent._get_task(task.id).status.state == TaskState.CANCELED

    def test_task_cancel_completed_fails(self):
        from shared.a2a_types import Message, TextPart
        from agents.data_analysis.main import DataAnalysisAgent

        agent = DataAnalysisAgent()
        msg = Message(role="user", parts=[TextPart(type="text", text="test")])
        task = agent._create_task("rpc-3", msg)
        agent._complete_task(task.id, "done")

        # Cannot cancel a completed task
        cancelled = agent._cancel_task(task.id)
        assert cancelled is False

    def test_agent_card_structure(self):
        from agents.data_analysis.main import DataAnalysisAgent
        card = DataAnalysisAgent.agent_card
        assert card.name == "Data Analysis Agent"
        assert card.version == "1.0.0"
        assert len(card.skills) == 3
        skill_ids = [s.id for s in card.skills]
        assert "python-execution" in skill_ids
        assert "statistics" in skill_ids
        assert "visualization" in skill_ids

    @pytest.mark.asyncio
    async def test_text_extraction(self):
        from agents.data_analysis.main import DataAnalysisAgent

        agent = DataAnalysisAgent()

        # Mock response with text
        mock_part = MagicMock()
        mock_part.text = "Analysis complete"
        mock_part.function_call = None
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [mock_part]

        text = agent._extract_text(mock_response)
        assert text == "Analysis complete"

    @pytest.mark.asyncio
    async def test_tool_call_extraction(self):
        from agents.data_analysis.main import DataAnalysisAgent

        agent = DataAnalysisAgent()

        # Mock response with function_call
        mock_fc = MagicMock()
        mock_fc.name = "run_python_code_tool"
        mock_fc.args = {"code": "print(1)"}
        mock_part = MagicMock()
        mock_part.text = ""
        mock_part.function_call = mock_fc
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [mock_part]

        calls = agent._extract_tool_calls(mock_response)
        assert len(calls) == 1
        assert calls[0].name == "run_python_code_tool"


# ─────────────────────────────────────────────
# TestA2AEndpoints
# ─────────────────────────────────────────────

class TestA2AEndpoints:
    """Test HTTP endpoints — all Gemini calls mocked."""

    @pytest.mark.asyncio
    async def test_agent_card_public(self, client):
        """Agent card requires no auth."""
        response = await client.get("/.well-known/agent.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "Data Analysis Agent"
        assert "skills" in card
        assert len(card["skills"]) == 3

    @pytest.mark.asyncio
    async def test_health_public(self, client):
        """Health requires no auth."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["agent"] == "Data Analysis Agent"

    @pytest.mark.asyncio
    async def test_tasks_send_requires_auth(self, client):
        """tasks/send without token → 401."""
        response = await client.post(
            "/a2a/tasks/send",
            json=make_task_send_body("analyze data"),
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_tasks_get_requires_auth(self, client):
        response = await client.post(
            "/a2a/tasks/get",
            json=make_rpc_request("tasks/get", {"id": "fake-id"}),
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_tasks_cancel_requires_auth(self, client):
        response = await client.post(
            "/a2a/tasks/cancel",
            json=make_rpc_request("tasks/cancel", {"id": "fake-id"}),
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_tasks_send_success(self, auth_client):
        """Full tasks/send with mocked Gemini → completed task."""
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "Statistical analysis complete: mean=30.0"
        mock_part.function_call = None
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [mock_part]

        with patch(
            "agents.base.a2a_server.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await auth_client.post(
                "/a2a/tasks/send",
                json=make_task_send_body("Analyze [10, 20, 30, 40, 50]"),
            )

        assert response.status_code == 200
        body = response.json()
        assert "result" in body
        assert body["result"]["status"]["state"] == "completed"
        artifact_text = body["result"]["artifacts"][0]["parts"][0]["text"]
        assert "Statistical" in artifact_text

    @pytest.mark.asyncio
    async def test_tasks_send_uses_tool(self, auth_client):
        """Verify Gemini tool call → execute_tool → final response."""
        # Round 1: Gemini calls run_python_code_tool
        mock_fc = MagicMock()
        mock_fc.name = "run_python_code_tool"
        mock_fc.args = {"code": "print(sum([1,2,3]))"}

        mock_part_fc = MagicMock()
        mock_part_fc.text = ""
        mock_part_fc.function_call = mock_fc

        mock_response_1 = MagicMock()
        mock_response_1.candidates = [MagicMock()]
        mock_response_1.candidates[0].content.parts = [mock_part_fc]

        # Round 2: Gemini returns text
        mock_part_text = MagicMock()
        mock_part_text.text = "The sum of 1, 2, 3 is 6."
        mock_part_text.function_call = None

        mock_response_2 = MagicMock()
        mock_response_2.candidates = [MagicMock()]
        mock_response_2.candidates[0].content.parts = [mock_part_text]

        call_count = 0

        async def mock_to_thread(func, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_response_1 if call_count == 1 else mock_response_2

        with patch("agents.base.a2a_server.asyncio.to_thread", side_effect=mock_to_thread):
            response = await auth_client.post(
                "/a2a/tasks/send",
                json=make_task_send_body("What is 1+2+3?"),
            )

        assert response.status_code == 200
        body = response.json()
        assert body["result"]["status"]["state"] == "completed"
        # call_count == 3 because mock_to_thread intercepts ALL asyncio.to_thread calls:
        #   call 1: Gemini iteration 0 (returns tool call)
        #   call 2: run_python_code _run_sync (tools.py uses to_thread internally)
        #   call 3: Gemini iteration 1 (returns final text)
        assert call_count == 3  

    @pytest.mark.asyncio
    async def test_tasks_get_not_found(self, auth_client):
        response = await auth_client.post(
            "/a2a/tasks/get",
            json=make_rpc_request("tasks/get", {"id": "nonexistent-id"}),
        )
        assert response.status_code == 200  # HTTP always 200
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == -32001  # TASK_NOT_FOUND

    @pytest.mark.asyncio
    async def test_tasks_get_existing(self, auth_client):
        """Create a task then retrieve it."""
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "Analysis done."
        mock_part.function_call = None
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [mock_part]

        with patch(
            "agents.base.a2a_server.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            send_response = await auth_client.post(
                "/a2a/tasks/send",
                json=make_task_send_body("test task"),
            )

        task_id = send_response.json()["result"]["id"]

        get_response = await auth_client.post(
            "/a2a/tasks/get",
            json=make_rpc_request("tasks/get", {"id": task_id}),
        )
        assert get_response.status_code == 200
        body = get_response.json()
        assert "result" in body
        assert body["result"]["id"] == task_id

    @pytest.mark.asyncio
    async def test_tasks_cancel_not_found(self, auth_client):
        response = await auth_client.post(
            "/a2a/tasks/cancel",
            json=make_rpc_request("tasks/cancel", {"id": "fake-id"}),
        )
        assert response.status_code == 200
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == -32001

    @pytest.mark.asyncio
    async def test_tasks_send_no_text_in_message(self, auth_client):
        """Message with no text part → JSON-RPC error, HTTP 200."""
        body = make_rpc_request(
            "tasks/send",
            params={
                "message": {
                    "role": "user",
                    "parts": [],  # No parts
                }
            },
        )
        response = await auth_client.post("/a2a/tasks/send", json=body)
        assert response.status_code == 200
        resp_body = response.json()
        assert "error" in resp_body

    @pytest.mark.asyncio
    async def test_jsonrpc_envelope_preserved(self, auth_client):
        """Response id matches request id."""
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "done"
        mock_part.function_call = None
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [mock_part]

        with patch(
            "agents.base.a2a_server.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await auth_client.post(
                "/a2a/tasks/send",
                json=make_task_send_body("test", rpc_id=42),
            )

        body = response.json()
        assert body["id"] == 42
        assert body["jsonrpc"] == "2.0"