"""
Orchestrator tests — 38 tests across 4 test classes.

TestA2AClient        (11) — OrchestratorA2AClient HTTP behavior
TestTaskDecomposer   (8)  — LangGraph graph nodes (mocked Gemini)
TestOrchestratorApp  (13) — FastAPI endpoints
TestIntegration      (7)  — @pytest.mark.integration (live agents)

All TaskState references use UPPERCASE members matching a2a_types.py:
  TaskState.COMPLETED, TaskState.WORKING, TaskState.FAILED, etc.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.a2a_client import (
    A2AClientError,
    A2ATaskError,
    OrchestratorA2AClient,
)
from orchestrator.main import app
from orchestrator.task_decomposer import (
    AgentCallResult,
    AgentCallSpec,
    OrchestratorState,
    execute_node,
    plan_node,
    run_orchestrator,
    synthesize_node,
)
from shared.a2a_types import Artifact, Task, TaskState, TaskStatus, TextPart
from shared.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task(
    state: TaskState = TaskState.COMPLETED,
    text: str = "result text",
    task_id: str | None = None,
) -> Task:
    return Task(
        id=task_id or str(uuid.uuid4()),
        status=TaskStatus(state=state),
        artifacts=[
            Artifact(name="result", parts=[TextPart(text=text)])
        ] if text else [],
    )


def make_jsonrpc_response(result: dict, rpc_id: str = "1") -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


# ---------------------------------------------------------------------------
# TestA2AClient (11 tests)
# ---------------------------------------------------------------------------

class TestA2AClient:

    @pytest.mark.asyncio
    async def test_send_task_success_immediate(self):
        """Agent returns completed task on tasks/send → no polling needed."""
        task = make_task(state=TaskState.COMPLETED, text="answer here")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = make_jsonrpc_response(
            task.model_dump(mode="json")
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=mock_response):
            async with OrchestratorA2AClient() as client:
                result = await client.send_task(
                    agent_url="http://localhost:8001",
                    message="search for something",
                )
        assert result.status.state == TaskState.COMPLETED

    @pytest.mark.asyncio
    async def test_send_task_polls_until_complete(self):
        """Agent returns 'working' on send, then 'completed' on get."""
        working_task = make_task(state=TaskState.WORKING, text="")
        done_task = make_task(state=TaskState.COMPLETED, text="final answer")

        send_response = MagicMock()
        send_response.status_code = 200
        send_response.json.return_value = make_jsonrpc_response(
            working_task.model_dump(mode="json")
        )

        get_response = MagicMock()
        get_response.status_code = 200
        get_response.json.return_value = make_jsonrpc_response(
            done_task.model_dump(mode="json")
        )

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return send_response
            return get_response

        with patch("httpx.AsyncClient.post", side_effect=mock_post):
            client = OrchestratorA2AClient(poll_interval=0.01)
            try:
                result = await client.send_task(
                    agent_url="http://localhost:8001",
                    message="test",
                )
            finally:
                await client.aclose()

        assert result.status.state == TaskState.COMPLETED
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_send_task_raises_on_failed_task(self):
        """Agent returns failed task → A2ATaskError raised."""
        failed_task = make_task(state=TaskState.FAILED, text="")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = make_jsonrpc_response(
            failed_task.model_dump(mode="json")
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=mock_response):
            async with OrchestratorA2AClient() as client:
                with pytest.raises(A2ATaskError):
                    await client.send_task("http://localhost:8001", "test")

    @pytest.mark.asyncio
    async def test_connection_error_raises_a2a_client_error(self):
        with patch("httpx.AsyncClient.post",
                   new_callable=AsyncMock,
                   side_effect=httpx.ConnectError("refused")):
            async with OrchestratorA2AClient() as client:
                with pytest.raises(A2AClientError) as exc_info:
                    await client.send_task("http://localhost:8001", "test")
        assert "connect" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_timeout_raises_a2a_client_error(self):
        with patch("httpx.AsyncClient.post",
                   new_callable=AsyncMock,
                   side_effect=httpx.TimeoutException("timed out")):
            async with OrchestratorA2AClient() as client:
                with pytest.raises(A2AClientError) as exc_info:
                    await client.send_task("http://localhost:8001", "test")
        assert "timed out" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_auth_failure_raises_a2a_client_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=mock_response):
            async with OrchestratorA2AClient() as client:
                with pytest.raises(A2AClientError) as exc_info:
                    await client.send_task("http://localhost:8001", "test")
        assert exc_info.value.code == 401

    @pytest.mark.asyncio
    async def test_jsonrpc_error_in_body_raises(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "1",
            "error": {"code": -32001, "message": "Task not found"},
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=mock_response):
            async with OrchestratorA2AClient() as client:
                with pytest.raises(A2AClientError):
                    await client.send_task("http://localhost:8001", "test")

    @pytest.mark.asyncio
    async def test_check_health_true(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock,
                   return_value=mock_response):
            async with OrchestratorA2AClient() as client:
                result = await client.check_health("http://localhost:8001")
        assert result is True

    @pytest.mark.asyncio
    async def test_check_health_false_on_error(self):
        with patch("httpx.AsyncClient.get",
                   new_callable=AsyncMock,
                   side_effect=httpx.ConnectError("refused")):
            async with OrchestratorA2AClient() as client:
                result = await client.check_health("http://localhost:8001")
        assert result is False

    def test_extract_text_result(self):
        task = make_task(text="extracted text")
        assert OrchestratorA2AClient.extract_text_result(task) == "extracted text"

    def test_extract_text_result_empty_artifacts(self):
        task = make_task(text="")
        assert OrchestratorA2AClient.extract_text_result(task) == ""


# ---------------------------------------------------------------------------
# TestTaskDecomposer (8 tests)
# ---------------------------------------------------------------------------

class TestTaskDecomposer:

    def _base_state(self, **overrides) -> OrchestratorState:
        state = OrchestratorState(
            user_query="What is the capital of France?",
            available_agents=[
                {
                    "name": "Web Search Agent",
                    "url": "http://localhost:8001",
                    "description": "Searches the web",
                    "skills": ["web search", "news"],
                }
            ],
            plan=[],
            completed_calls=[],
            final_answer="",
            iteration=0,
            error="",
        )
        state.update(overrides)
        return state

    @pytest.mark.asyncio
    async def test_plan_node_calls_gemini(self):
        mock_plan = [
            AgentCallSpec(
                agent_name="Web Search Agent",
                agent_url="http://localhost:8001",
                message="Search for capital of France",
                reason="Need web information",
            )
        ]
        with patch(
            "orchestrator.task_decomposer._call_gemini_plan",
            new_callable=AsyncMock,
            return_value=mock_plan,
        ):
            result = await plan_node(self._base_state())

        assert len(result["plan"]) == 1
        assert result["plan"][0]["agent_name"] == "Web Search Agent"
        assert result["iteration"] == 1

    @pytest.mark.asyncio
    async def test_plan_node_increments_iteration(self):
        with patch(
            "orchestrator.task_decomposer._call_gemini_plan",
            new_callable=AsyncMock,
            return_value=[],
        ):
            state = self._base_state(iteration=3)
            result = await plan_node(state)
        assert result["iteration"] == 4

    @pytest.mark.asyncio
    async def test_plan_node_stops_at_max_iterations(self):
        with patch(
            "orchestrator.task_decomposer._call_gemini_plan",
            new_callable=AsyncMock,
        ) as mock_plan:
            from orchestrator.task_decomposer import MAX_ITERATIONS
            state = self._base_state(iteration=MAX_ITERATIONS)
            result = await plan_node(state)

        assert result["plan"] == []
        mock_plan.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_node_calls_agents(self):
        completed_task = make_task(state=TaskState.COMPLETED, text="Paris")

        state = self._base_state(
            plan=[
                AgentCallSpec(
                    agent_name="Web Search Agent",
                    agent_url="http://localhost:8001",
                    message="Search capital of France",
                    reason="test",
                )
            ],
        )

        with patch(
            "orchestrator.task_decomposer.OrchestratorA2AClient",
        ) as MockClient, patch(
            # Patch the static method separately — it's called on the CLASS,
            # not the instance, so MockClient.extract_text_result needs explicit config.
            "orchestrator.task_decomposer.OrchestratorA2AClient.extract_text_result",
            return_value="Paris",
        ):
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.send_task = AsyncMock(return_value=completed_task)
            MockClient.return_value = instance

            result = await execute_node(state)

        assert len(result["completed_calls"]) == 1
        assert result["completed_calls"][0]["success"] is True
        assert result["completed_calls"][0]["result"] == "Paris"

    @pytest.mark.asyncio
    async def test_execute_node_handles_agent_failure(self):
        state = self._base_state(
            plan=[
                AgentCallSpec(
                    agent_name="Web Search Agent",
                    agent_url="http://localhost:8001",
                    message="Search something",
                    reason="test",
                )
            ],
        )

        with patch(
            "orchestrator.task_decomposer.OrchestratorA2AClient",
        ) as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.send_task = AsyncMock(
                side_effect=A2AClientError("Connection refused")
            )
            MockClient.return_value = instance

            result = await execute_node(state)

        assert len(result["completed_calls"]) == 1
        assert result["completed_calls"][0]["success"] is False
        assert "Connection refused" in result["completed_calls"][0]["error"]

    @pytest.mark.asyncio
    async def test_execute_node_accumulates_results(self):
        previous_result = AgentCallResult(
            agent_name="Web Search Agent",
            agent_url="http://localhost:8001",
            message="previous query",
            result="previous result",
            success=True,
            error="",
        )
        completed_task = make_task(text="new result")

        state = self._base_state(
            completed_calls=[previous_result],
            plan=[
                AgentCallSpec(
                    agent_name="Code Agent",
                    agent_url="http://localhost:8004",
                    message="analyze code",
                    reason="test",
                )
            ],
        )

        with patch(
            "orchestrator.task_decomposer.OrchestratorA2AClient",
        ) as MockClient, patch(
            "orchestrator.task_decomposer.OrchestratorA2AClient.extract_text_result",
            return_value="new result",
        ):
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.send_task = AsyncMock(return_value=completed_task)
            MockClient.return_value = instance

            result = await execute_node(state)

        assert len(result["completed_calls"]) == 2
        assert result["completed_calls"][0]["result"] == "previous result"  # preserved
        assert result["completed_calls"][1]["result"] == "new result"        # new

    @pytest.mark.asyncio
    async def test_synthesize_node_calls_gemini(self):
        state = self._base_state(
            completed_calls=[
                AgentCallResult(
                    agent_name="Web Search Agent",
                    agent_url="http://localhost:8001",
                    message="search query",
                    result="Paris is the capital of France.",
                    success=True,
                    error="",
                )
            ],
        )
        with patch(
            "orchestrator.task_decomposer._call_gemini_synthesize",
            new_callable=AsyncMock,
            return_value="The capital of France is Paris.",
        ):
            result = await synthesize_node(state)

        assert result["final_answer"] == "The capital of France is Paris."

    @pytest.mark.asyncio
    async def test_run_orchestrator_full_flow(self):
        mock_spec = AgentCallSpec(
            agent_name="Web Search Agent",
            agent_url="http://localhost:8001",
            message="search capital of France",
            reason="test",
        )
        completed_task = make_task(text="Paris is the capital")

        plan_calls = 0

        async def mock_plan(query, available_agents, completed_calls, iteration):
            nonlocal plan_calls
            plan_calls += 1
            if plan_calls == 1:
                return [mock_spec]
            return []

        with patch(
            "orchestrator.task_decomposer._call_gemini_plan",
            side_effect=mock_plan,
        ), patch(
            "orchestrator.task_decomposer._call_gemini_synthesize",
            new_callable=AsyncMock,
            return_value="France's capital is Paris.",
        ), patch(
            "orchestrator.task_decomposer.OrchestratorA2AClient",
        ) as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.send_task = AsyncMock(return_value=completed_task)
            MockClient.return_value = instance

            answer, calls = await run_orchestrator(
                query="What is the capital of France?",
                available_agents=[{
                    "name": "Web Search Agent",
                    "url": "http://localhost:8001",
                    "description": "web search",
                    "skills": ["search"],
                }],
            )

        assert answer == "France's capital is Paris."
        assert len(calls) == 1
        assert calls[0]["success"] is True


# ---------------------------------------------------------------------------
# TestOrchestratorApp (13 tests)
# ---------------------------------------------------------------------------

class TestOrchestratorApp:

    @pytest.mark.asyncio
    async def test_agent_card_public(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/.well-known/agent.json")
        assert response.status_code == 200
        assert response.json()["name"] == "Orchestrator Agent"

    @pytest.mark.asyncio
    async def test_health_public(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_list_agents_public(self):
        with patch(
            "orchestrator.main.fetch_available_agents",
            new_callable=AsyncMock,
            return_value=[
                {"name": "Web Search Agent", "url": "http://localhost:8001",
                 "description": "web search", "skills": ["search"]},
            ],
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/agents")
        assert response.status_code == 200
        assert response.json()["count"] == 1

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
    async def test_orchestrate_requires_auth(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/orchestrate",
                json={"query": "test query"},
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_tasks_send_success(self):
        with patch(
            "orchestrator.main.fetch_available_agents",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "orchestrator.main.run_orchestrator",
            new_callable=AsyncMock,
            return_value=("Paris is the capital of France.", []),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/a2a/tasks/send",
                    headers={"Authorization": f"Bearer {settings.a2a_bearer_token}"},
                    json={
                        "jsonrpc": "2.0", "id": "1", "method": "tasks/send",
                        "params": {
                            "message": {
                                "role": "user",
                                "parts": [{"text": "What is the capital of France?"}],
                            }
                        },
                    },
                )
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert data["result"]["status"]["state"] == "completed"

    @pytest.mark.asyncio
    async def test_orchestrate_direct_success(self):
        with patch(
            "orchestrator.main.fetch_available_agents",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "orchestrator.main.run_orchestrator",
            new_callable=AsyncMock,
            return_value=("The answer is 42.", []),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/orchestrate",
                    headers={"Authorization": f"Bearer {settings.a2a_bearer_token}"},
                    json={"query": "What is the answer?"},
                )
        assert response.status_code == 200
        assert response.json()["answer"] == "The answer is 42."

    @pytest.mark.asyncio
    async def test_orchestrate_missing_query(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/orchestrate",
                headers={"Authorization": f"Bearer {settings.a2a_bearer_token}"},
                json={},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_tasks_get_not_found(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/a2a/tasks/get",
                headers={"Authorization": f"Bearer {settings.a2a_bearer_token}"},
                json={"jsonrpc": "2.0", "id": "1", "method": "tasks/get",
                      "params": {"id": "nonexistent-task-id"}},
            )
        assert response.status_code == 200
        assert response.json()["error"]["code"] == -32001

    @pytest.mark.asyncio
    async def test_tasks_get_found(self):
        with patch(
            "orchestrator.main.fetch_available_agents",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "orchestrator.main.run_orchestrator",
            new_callable=AsyncMock,
            return_value=("test answer", []),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                send = await client.post(
                    "/a2a/tasks/send",
                    headers={"Authorization": f"Bearer {settings.a2a_bearer_token}"},
                    json={
                        "jsonrpc": "2.0", "id": "1", "method": "tasks/send",
                        "params": {"message": {"role": "user",
                                               "parts": [{"text": "test"}]}},
                    },
                )
                task_id = send.json()["result"]["id"]

                get = await client.post(
                    "/a2a/tasks/get",
                    headers={"Authorization": f"Bearer {settings.a2a_bearer_token}"},
                    json={"jsonrpc": "2.0", "id": "2", "method": "tasks/get",
                          "params": {"id": task_id}},
                )
        assert get.json()["result"]["id"] == task_id

    @pytest.mark.asyncio
    async def test_tasks_cancel(self):
        with patch(
            "orchestrator.main.fetch_available_agents",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "orchestrator.main.run_orchestrator",
            new_callable=AsyncMock,
            return_value=("test answer", []),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                send = await client.post(
                    "/a2a/tasks/send",
                    headers={"Authorization": f"Bearer {settings.a2a_bearer_token}"},
                    json={
                        "jsonrpc": "2.0", "id": "1", "method": "tasks/send",
                        "params": {"message": {"role": "user",
                                               "parts": [{"text": "test"}]}},
                    },
                )
                task_id = send.json()["result"]["id"]

                cancel = await client.post(
                    "/a2a/tasks/cancel",
                    headers={"Authorization": f"Bearer {settings.a2a_bearer_token}"},
                    json={"jsonrpc": "2.0", "id": "2", "method": "tasks/cancel",
                          "params": {"id": task_id}},
                )
        assert cancel.json()["result"]["status"]["state"] == "canceled"

    @pytest.mark.asyncio
    async def test_agent_card_url_has_port(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/.well-known/agent.json")
        assert "8000" in response.json()["url"]

    @pytest.mark.asyncio
    async def test_agent_card_provider(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/.well-known/agent.json")
        assert response.json()["provider"]["organization"] == "A2A Marketplace"


# ---------------------------------------------------------------------------
# TestIntegration (7 tests) — requires all services running
# ---------------------------------------------------------------------------

class TestIntegration:
    """
    Live integration tests. Run with:
      sudo service postgresql start
      python -m agents.web_search.main &
      python -m agents.code.main &
      python -m registry.main &
      python -m orchestrator.main &
      pytest tests/test_orchestrator.py -m integration -v
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_registry_reachable(self):
        from orchestrator.main import fetch_available_agents
        agents = await fetch_available_agents()
        assert isinstance(agents, list)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_web_search_agent_health(self):
        async with OrchestratorA2AClient() as client:
            healthy = await client.check_health("http://localhost:8001")
        assert healthy is True

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_send_task_to_web_search(self):
        async with OrchestratorA2AClient() as client:
            task = await client.send_task(
                agent_url="http://localhost:8001",
                message="What is the Python programming language?",
            )
        assert task.status.state == TaskState.COMPLETED
        text = OrchestratorA2AClient.extract_text_result(task)
        assert len(text) > 20

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_send_task_to_code_agent(self):
        async with OrchestratorA2AClient() as client:
            task = await client.send_task(
                agent_url="http://localhost:8004",
                message="Execute this code: print(2 + 2)",
            )
        assert task.status.state == TaskState.COMPLETED

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_orchestrator_with_registry(self):
        from orchestrator.main import fetch_available_agents
        from orchestrator.task_decomposer import run_orchestrator

        agents = await fetch_available_agents()
        answer, calls = await run_orchestrator(
            query="Execute this Python code: print('hello from orchestrator')",
            available_agents=agents,
        )
        assert len(answer) > 0

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_orchestrator_http_endpoint(self):
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"http://localhost:{settings.orchestrator_port}/orchestrate",
                headers={"Authorization": f"Bearer {settings.a2a_bearer_token}"},
                json={"query": "What is 2 + 2? Use the code agent to compute it."},
            )
        assert response.status_code == 200
        assert len(response.json()["answer"]) > 0

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_multi_agent_orchestration(self):
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"http://localhost:{settings.orchestrator_port}/orchestrate",
                headers={"Authorization": f"Bearer {settings.a2a_bearer_token}"},
                json={
                    "query": (
                        "Search for information about the Python GIL, "
                        "then analyze and explain this related code: "
                        "import threading; t = threading.Thread(target=print, args=['hi']); t.start()"
                    )
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data["answer"]) > 0
        assert data["calls_made"] >= 1