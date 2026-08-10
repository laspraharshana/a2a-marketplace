"""
Code Agent tests — 41 tests across 4 test classes.

TestMCPSchemas      (7)  — tool declaration structure
TestToolExecution   (14) — tool logic with mocks
TestBaseAgent       (6)  — BaseA2AAgent integration
TestA2AEndpoints    (13) — HTTP endpoint behavior

Patch paths: agents.code.mcp_server.<fn> not agents.code.tools.<fn>
Same reason as document agent — from-import creates local binding.

execute_code is different: uses subprocess internally.
Test via mock on agents.code.mcp_server.execute_code (the imported fn).
Do NOT patch subprocess.run directly — too deep, mock the tool fn instead.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agents.code.main import _agent, app
from agents.code.mcp_server import (
    execute_mcp_tool,
    get_gemini_tool_declarations,
)
from agents.code.tools import (
    AnalysisResult,
    ExecutionResult,
    ExplanationResult,
    analyze_code,
    execute_code,
    explain_code,
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
def simple_source() -> str:
    return textwrap.dedent("""\
        def add(a, b):
            \"\"\"Add two numbers.\"\"\"
            return a + b

        def multiply(a, b):
            \"\"\"Multiply two numbers.\"\"\"
            return a * b
    """)


@pytest.fixture
def complex_source() -> str:
    """Source with nested conditionals — higher cyclomatic complexity."""
    return textwrap.dedent("""\
        def process(data, mode, flag):
            if mode == 'a':
                if flag:
                    for item in data:
                        if item > 0:
                            print(item)
                        else:
                            print(-item)
                else:
                    return None
            elif mode == 'b':
                while data:
                    item = data.pop()
                    if item:
                        yield item
            else:
                raise ValueError('unknown mode')
    """)


import textwrap  # noqa: E402 — used in fixtures above


# ---------------------------------------------------------------------------
# TestMCPSchemas (7 tests)
# ---------------------------------------------------------------------------

class TestMCPSchemas:
    def test_tool_declarations_returns_list(self):
        decls = get_gemini_tool_declarations()
        assert isinstance(decls, list)

    def test_tool_declarations_count(self):
        assert len(get_gemini_tool_declarations()) == 3

    def test_tool_names(self):
        names = [d["name"] for d in get_gemini_tool_declarations()]
        assert "analyze_code_tool" in names
        assert "execute_code_tool" in names
        assert "explain_code_tool" in names

    def test_uses_parameters_not_input_schema(self):
        for decl in get_gemini_tool_declarations():
            assert "parameters" in decl
            assert "inputSchema" not in decl

    def test_each_tool_has_description(self):
        for decl in get_gemini_tool_declarations():
            assert len(decl["description"]) > 10

    def test_analyze_code_required_params(self):
        decls = {d["name"]: d for d in get_gemini_tool_declarations()}
        params = decls["analyze_code_tool"]["parameters"]
        assert "source" in params["required"]
        assert "language" in params["properties"]

    def test_execute_code_required_params(self):
        decls = {d["name"]: d for d in get_gemini_tool_declarations()}
        params = decls["execute_code_tool"]["parameters"]
        assert "source" in params["required"]
        assert "stdin_input" in params["properties"]
        assert "timeout" in params["properties"]


# ---------------------------------------------------------------------------
# TestToolExecution (14 tests)
# ---------------------------------------------------------------------------

class TestToolExecution:

    # --- analyze_code ---

    @pytest.mark.asyncio
    async def test_analyze_code_success(self, simple_source):
        mock_result = AnalysisResult(
            success=True,
            language="python",
            function_count=2,
            class_count=0,
            import_count=0,
            line_count=8,
            avg_complexity=1.0,
            max_complexity=1.0,
            complexity_grade="A",
            functions=[
                {"name": "add", "line": 1, "args": ["a", "b"],
                 "is_async": False, "has_docstring": True,
                 "decorator_count": 0, "complexity": 1, "complexity_grade": "A"},
                {"name": "multiply", "line": 5, "args": ["a", "b"],
                 "is_async": False, "has_docstring": True,
                 "decorator_count": 0, "complexity": 1, "complexity_grade": "A"},
            ],
            classes=[],
            imports=[],
            issues=[],
        )
        with patch(
            "agents.code.mcp_server.analyze_code",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "analyze_code_tool", {"source": simple_source}
            )
        result = json.loads(result_json)
        assert result["success"] is True
        assert result["metrics"]["function_count"] == 2
        assert result["metrics"]["complexity_grade"] == "A"
        assert len(result["functions"]) == 2

    @pytest.mark.asyncio
    async def test_analyze_code_syntax_error(self):
        mock_result = AnalysisResult(
            success=False,
            error="Syntax error at line 1: invalid syntax",
        )
        with patch(
            "agents.code.mcp_server.analyze_code",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "analyze_code_tool", {"source": "def broken("}
            )
        result = json.loads(result_json)
        assert result["success"] is False
        assert "Syntax error" in result["error"]

    @pytest.mark.asyncio
    async def test_analyze_code_default_language(self):
        """Default language is 'python'."""
        mock_result = AnalysisResult(success=True, language="python")
        with patch(
            "agents.code.mcp_server.analyze_code",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            await execute_mcp_tool("analyze_code_tool", {"source": "x = 1"})
        mock_fn.assert_called_once_with("x = 1", "python")

    # --- execute_code ---

    @pytest.mark.asyncio
    async def test_execute_code_success(self):
        mock_result = ExecutionResult(
            success=True,
            stdout="Hello, World!\n",
            stderr="",
            exit_code=0,
            timed_out=False,
            execution_time_ms=45.2,
        )
        with patch(
            "agents.code.mcp_server.execute_code",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "execute_code_tool",
                {"source": 'print("Hello, World!")'},
            )
        result = json.loads(result_json)
        assert result["success"] is True
        assert result["stdout"] == "Hello, World!\n"
        assert result["exit_code"] == 0
        assert result["timed_out"] is False

    @pytest.mark.asyncio
    async def test_execute_code_timeout(self):
        mock_result = ExecutionResult(
            success=False,
            stdout="",
            stderr="Execution timed out after 10 seconds",
            exit_code=-1,
            timed_out=True,
            execution_time_ms=10001.0,
        )
        with patch(
            "agents.code.mcp_server.execute_code",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "execute_code_tool",
                {"source": "while True: pass"},
            )
        result = json.loads(result_json)
        assert result["success"] is False
        assert result["timed_out"] is True

    @pytest.mark.asyncio
    async def test_execute_code_runtime_error(self):
        mock_result = ExecutionResult(
            success=False,
            stdout="",
            stderr="Traceback (most recent call last):\n  ...\nZeroDivisionError: division by zero\n",
            exit_code=1,
            timed_out=False,
            execution_time_ms=12.0,
        )
        with patch(
            "agents.code.mcp_server.execute_code",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "execute_code_tool",
                {"source": "print(1/0)"},
            )
        result = json.loads(result_json)
        assert result["success"] is False
        assert "ZeroDivisionError" in result["stderr"]
        assert result["exit_code"] == 1

    @pytest.mark.asyncio
    async def test_execute_code_default_args(self):
        """Default stdin_input is '' and timeout is 10."""
        mock_result = ExecutionResult(success=True, stdout="ok\n")
        with patch(
            "agents.code.mcp_server.execute_code",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            await execute_mcp_tool("execute_code_tool", {"source": "print('ok')"})
        mock_fn.assert_called_once_with("print('ok')", "", 10)

    # --- explain_code ---

    @pytest.mark.asyncio
    async def test_explain_code_success(self, simple_source):
        mock_result = ExplanationResult(
            success=True,
            explanation="This module provides two arithmetic utility functions.",
            complexity_summary="Simple functions with linear complexity.",
            suggestions=["Add type hints", "Add error handling"],
        )
        with patch(
            "agents.code.mcp_server.explain_code",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "explain_code_tool", {"source": simple_source}
            )
        result = json.loads(result_json)
        assert result["success"] is True
        assert "arithmetic" in result["explanation"]
        assert len(result["suggestions"]) == 2

    @pytest.mark.asyncio
    async def test_explain_code_failure(self):
        mock_result = ExplanationResult(success=False, error="API error")
        with patch(
            "agents.code.mcp_server.explain_code",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result_json = await execute_mcp_tool(
                "explain_code_tool", {"source": "x = 1"}
            )
        result = json.loads(result_json)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_explain_code_default_detail_level(self):
        """Default detail_level is 'standard'."""
        mock_result = ExplanationResult(success=True, explanation="ok")
        with patch(
            "agents.code.mcp_server.explain_code",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            await execute_mcp_tool("explain_code_tool", {"source": "x = 1"})
        mock_fn.assert_called_once_with("x = 1", "standard")

    # --- routing ---

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        result = json.loads(await execute_mcp_tool("no_such_tool", {}))
        assert "error" in result
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_source_returns_error(self):
        result = json.loads(await execute_mcp_tool("analyze_code_tool", {}))
        assert "error" in result

    # --- tools.py direct unit tests (no mocking needed) ---

    @pytest.mark.asyncio
    async def test_analyze_code_real_ast(self, simple_source):
        """Direct call to tools.py — exercises real AST parsing."""
        result = await analyze_code(simple_source)
        assert result.success is True
        assert result.function_count == 2
        assert result.class_count == 0
        # Both functions have docstrings → no issues
        assert result.issues == []

    @pytest.mark.asyncio
    async def test_analyze_code_missing_docstring(self):
        source = "def no_doc(x):\n    return x\n"
        result = await analyze_code(source)
        assert result.success is True
        assert any("no_doc" in issue for issue in result.issues)

    @pytest.mark.asyncio
    async def test_analyze_code_syntax_error_direct(self):
        result = await analyze_code("def broken(:")
        assert result.success is False
        assert "Syntax error" in result.error

    @pytest.mark.asyncio
    async def test_execute_code_real_subprocess(self):
        """Real subprocess execution — verifies sandbox works end-to-end."""
        result = await execute_code("print('sandbox_ok')")
        assert result.success is True
        assert "sandbox_ok" in result.stdout
        assert result.exit_code == 0
        assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# TestBaseAgent (6 tests)
# ---------------------------------------------------------------------------

class TestBaseAgent:
    def test_agent_card_exists(self):
        assert _agent.agent_card is not None

    def test_agent_card_name(self):
        assert _agent.agent_card.name == "Code Agent"

    def test_agent_card_skills_count(self):
        assert len(_agent.agent_card.skills) == 3

    def test_agent_card_skill_ids(self):
        skill_ids = [s.id for s in _agent.agent_card.skills]
        assert "analyze-code" in skill_ids
        assert "execute-code" in skill_ids
        assert "explain-code" in skill_ids

    def test_get_tool_declarations_returns_three(self):
        assert len(_agent.get_tool_declarations()) == 3

    def test_system_prompt_not_empty(self):
        prompt = _agent.get_system_prompt()
        assert len(prompt) > 50
        assert "analyze_code_tool" in prompt


# ---------------------------------------------------------------------------
# TestA2AEndpoints (13 tests)
# ---------------------------------------------------------------------------

class TestA2AEndpoints:

    @pytest.mark.asyncio
    async def test_agent_card_public(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/.well-known/agent.json")
        assert response.status_code == 200
        assert response.json()["name"] == "Code Agent"

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
        mock_response.text = "The code looks good. Complexity grade A."
        mock_response.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(
                text="The code looks good. Complexity grade A.",
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
                        "jsonrpc": "2.0", "id": "test-1", "method": "tasks/send",
                        "params": {"message": {"role": "user",
                                               "parts": [{"text": "Analyze this code: x=1"}]}},
                    },
                )
        assert response.status_code == 200
        assert response.json()["result"]["status"]["state"] == "completed"

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
                                               "parts": [{"text": "run x=1"}]}},
                    },
                )
        assert len(response.json()["result"]["id"]) > 0

    @pytest.mark.asyncio
    async def test_tasks_get_not_found(self, auth_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/a2a/tasks/get",
                headers={"Authorization": "Bearer test-token"},
                json={"jsonrpc": "2.0", "id": "1", "method": "tasks/get",
                      "params": {"id": "no-such-task"}},
            )
        assert response.status_code == 200
        assert response.json()["error"]["code"] == -32001

    @pytest.mark.asyncio
    async def test_tasks_get_found(self, auth_client):
        mock_response = MagicMock()
        mock_response.text = "Analysis complete."
        mock_response.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(
                text="Analysis complete.", function_call=None,
            )]))
        ]
        with patch("agents.base.a2a_server.asyncio.to_thread",
                   new_callable=AsyncMock, return_value=mock_response):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                send = await client.post(
                    "/a2a/tasks/send",
                    headers={"Authorization": "Bearer test-token"},
                    json={"jsonrpc": "2.0", "id": "1", "method": "tasks/send",
                          "params": {"message": {"role": "user",
                                                 "parts": [{"text": "test"}]}}},
                )
                task_id = send.json()["result"]["id"]
                get = await client.post(
                    "/a2a/tasks/get",
                    headers={"Authorization": "Bearer test-token"},
                    json={"jsonrpc": "2.0", "id": "2", "method": "tasks/get",
                          "params": {"id": task_id}},
                )
        assert get.json()["result"]["id"] == task_id

    @pytest.mark.asyncio
    async def test_tasks_cancel_not_found(self, auth_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/a2a/tasks/cancel",
                headers={"Authorization": "Bearer test-token"},
                json={"jsonrpc": "2.0", "id": "1", "method": "tasks/cancel",
                      "params": {"id": "no-such-task"}},
            )
        assert response.status_code == 200
        assert "error" in response.json()

    @pytest.mark.asyncio
    async def test_tool_call_round_trip(self, auth_client):
        """
        Gemini → execute_code_tool function call → tool result → Gemini final.
        call_count == 3 (Gemini call 1, tool's to_thread, Gemini call 2).
        """
        round1 = MagicMock()
        round1.text = None
        round1.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(
                text=None,
                function_call=MagicMock(
                    name="execute_code_tool",
                    args={"source": "print(2 + 2)"},
                ),
            )]))
        ]

        round2 = MagicMock()
        round2.text = "The code prints 4, which is the result of 2 + 2."
        round2.candidates = [
            MagicMock(content=MagicMock(parts=[MagicMock(
                text="The code prints 4, which is the result of 2 + 2.",
                function_call=None,
            )]))
        ]

        tool_response = json.dumps({
            "success": True,
            "stdout": "4\n",
            "stderr": "",
            "exit_code": 0,
            "timed_out": False,
            "execution_time_ms": 38.5,
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
                        "params": {"message": {"role": "user",
                                               "parts": [{"text": "Run print(2+2)"}]}},
                    },
                )

        assert response.status_code == 200
        assert call_count == 3
        task = response.json()["result"]
        assert task["status"]["state"] == "completed"
        assert "4" in task["artifacts"][0]["parts"][0]["text"]

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
        assert "8004" in response.json()["url"]

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