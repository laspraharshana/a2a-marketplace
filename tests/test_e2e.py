# tests/test_e2e.py
"""
End-to-End Integration Tests — Full System

PREREQUISITES (all must be running):
  sudo service postgresql start
  redis-server --daemonize yes
  docker compose up   OR   all services started manually

Run with:
  pytest tests/test_e2e.py -m integration -v
  pytest tests/test_e2e.py -m integration -v -s  (show logs)

Skip in normal pytest run:
  pytest tests/ -m "not integration"

WHAT THESE TESTS VERIFY:
  - All services are reachable and healthy
  - Agent Registry discovers all 4 agents
  - Web Search Agent performs real web search via A2A
  - Data Analysis Agent processes real data via A2A
  - Orchestrator coordinates multi-agent tasks
  - Full marketplace flow end-to-end
"""

from __future__ import annotations
import asyncio
import pytest
import httpx
from typing import Any

# ── Service URLs ──────────────────────────────────────────────
# These match your local dev setup (not Docker internal URLs)
REGISTRY_URL        = "http://localhost:9000"
ORCHESTRATOR_URL    = "http://localhost:8000"
WEB_SEARCH_URL      = "http://localhost:8001"
DATA_ANALYSIS_URL   = "http://localhost:8002"
DOCUMENT_URL        = "http://localhost:8003"
CODE_URL            = "http://localhost:8004"

# Auth token — must match .env A2A_BEARER_TOKEN
BEARER_TOKEN = "dev-bearer-token"
AUTH_HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}"}

# Timeouts — real LLM calls take time
TASK_TIMEOUT   = 120.0   # seconds to wait for task completion
HEALTH_TIMEOUT = 10.0    # seconds for health checks


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def make_task_request(
    task_id: str,
    message: str,
    session_id: str | None = None
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 tasks/send request body."""
    params: dict[str, Any] = {
        "id": task_id,
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": message}]
        }
    }
    if session_id:
        params["sessionId"] = session_id

    return {
        "jsonrpc": "2.0",
        "id": f"req-{task_id}",
        "method": "tasks/send",
        "params": params
    }


async def send_task_and_wait(
    client: httpx.AsyncClient,
    base_url: str,
    task_id: str,
    message: str,
    timeout: float = TASK_TIMEOUT
) -> dict[str, Any]:
    """
    Send a task to an agent and wait for completion.
    Polls tasks/get until terminal state reached.
    Returns the completed Task dict.
    """
    # Send task
    response = await client.post(
        f"{base_url}/a2a/tasks/send",
        headers=AUTH_HEADERS,
        json=make_task_request(task_id, message),
        timeout=timeout
    )
    assert response.status_code == 200, (
        f"tasks/send failed: {response.status_code} {response.text}"
    )

    data = response.json()
    assert "error" not in data or data["error"] is None, (
        f"tasks/send returned error: {data.get('error')}"
    )

    task = data["result"]
    state = task["status"]["state"]

    # If already terminal (fast response), return immediately
    terminal_states = {"completed", "failed", "canceled"}
    if state in terminal_states:
        return task

    # Poll until terminal
    task_id_to_poll = task["id"]
    elapsed = 0.0
    poll_interval = 2.0

    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        get_response = await client.post(
            f"{base_url}/a2a/tasks/get",
            headers=AUTH_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": f"poll-{task_id_to_poll}",
                "method": "tasks/get",
                "params": {"id": task_id_to_poll}
            },
            timeout=10.0
        )

        if get_response.status_code != 200:
            continue

        poll_data = get_response.json()
        if "result" in poll_data and poll_data["result"]:
            task = poll_data["result"]
            state = task["status"]["state"]
            if state in terminal_states:
                return task

    pytest.fail(
        f"Task {task_id} did not complete within {timeout}s. "
        f"Last state: {state}"
    )


def extract_artifact_text(task: dict[str, Any]) -> str:
    """Extract text content from first task artifact."""
    artifacts = task.get("artifacts", [])
    assert len(artifacts) > 0, "Task has no artifacts"

    parts = artifacts[0].get("parts", [])
    assert len(parts) > 0, "Artifact has no parts"

    text = parts[0].get("text", "")
    assert text, "Artifact text is empty"
    return text

@pytest.fixture(autouse=True)
async def rate_limit_delay():
    """Space out tests to avoid Gemini free tier 15 RPM limit."""
    yield
    await asyncio.sleep(5)


# ══════════════════════════════════════════════════════════════
# SCENARIO 1: SERVICE HEALTH CHECKS
# Verify all services are running before deeper tests
# ══════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestServiceHealth:
    """All services must be healthy before E2E tests run."""

    @pytest.mark.asyncio
    async def test_registry_healthy(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{REGISTRY_URL}/health",
                timeout=HEALTH_TIMEOUT
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_web_search_agent_healthy(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{WEB_SEARCH_URL}/health",
                timeout=HEALTH_TIMEOUT
            )
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_data_analysis_agent_healthy(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{DATA_ANALYSIS_URL}/health",
                timeout=HEALTH_TIMEOUT
            )
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_document_agent_healthy(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{DOCUMENT_URL}/health",
                timeout=HEALTH_TIMEOUT
            )
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_code_agent_healthy(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{CODE_URL}/health",
                timeout=HEALTH_TIMEOUT
            )
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_orchestrator_healthy(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{ORCHESTRATOR_URL}/health",
                timeout=HEALTH_TIMEOUT
            )
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


# ══════════════════════════════════════════════════════════════
# SCENARIO 2: AGENT CARDS AND REGISTRY
# Verify A2A agent discovery works
# ══════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestAgentDiscovery:
    """Agent Cards and Registry discovery."""

    @pytest.mark.asyncio
    async def test_all_agent_cards_served(self):
        """Every agent must serve a valid Agent Card."""
        agents = [
            (WEB_SEARCH_URL, "web-search-agent"),
            (DATA_ANALYSIS_URL, "data-analysis-agent"),
            (DOCUMENT_URL, "document-agent"),
            (CODE_URL, "code-agent"),
        ]
        async with httpx.AsyncClient() as client:
            for url, expected_name in agents:
                response = await client.get(
                    f"{url}/.well-known/agent.json",
                    timeout=HEALTH_TIMEOUT
                )
                assert response.status_code == 200, (
                    f"Agent card failed for {url}"
                )
                card = response.json()
                assert card["name"] == expected_name, (
                    f"Expected {expected_name}, got {card['name']}"
                )
                assert len(card["skills"]) > 0
                assert "capabilities" in card

    @pytest.mark.asyncio
    async def test_registry_lists_agents(self):
        """
        Registry must list registered agents.
        Agents register on startup via BaseA2AAgent.
        Wait a moment for registration to complete.
        """
        await asyncio.sleep(3)  # Allow registration heartbeats

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{REGISTRY_URL}/agents",
                timeout=HEALTH_TIMEOUT
            )
        assert response.status_code == 200
        data = response.json()

        agents = data.get("agents", [])
        agent_names = [a["name"] for a in agents]

        # All 4 specialist agents should be registered
        expected = [
            "web-search-agent",
            "data-analysis-agent",
            "document-agent",
            "code-agent"
        ]
        for expected_name in expected:
            assert expected_name in agent_names, (
                f"{expected_name} not in registry. "
                f"Registered: {agent_names}"
            )

    @pytest.mark.asyncio
    async def test_orchestrator_discovers_agents(self):
        """Orchestrator must see agents via registry."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{ORCHESTRATOR_URL}/agents",
                headers=AUTH_HEADERS,
                timeout=HEALTH_TIMEOUT
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data.get("agents", [])) >= 1


# ══════════════════════════════════════════════════════════════
# SCENARIO 3: WEB SEARCH AGENT — DIRECT A2A CALL
# ══════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestWebSearchAgentE2E:
    """Direct A2A calls to Web Search Agent."""

    @pytest.mark.asyncio
    async def test_web_search_returns_results(self):
        """
        Send a search task directly to Web Search Agent.
        Verify real content is returned.
        """
        async with httpx.AsyncClient() as client:
            task = await send_task_and_wait(
                client,
                WEB_SEARCH_URL,
                "e2e-search-001",
                "Search for Python programming language overview",
                timeout=60.0
            )

        assert task["status"]["state"] == "completed"
        text = extract_artifact_text(task)

        # Response should mention Python
        assert len(text) > 100, "Response too short"
        assert "python" in text.lower() or "Python" in text

    @pytest.mark.asyncio
    async def test_web_search_news_query(self):
        """News search returns recent articles."""
        async with httpx.AsyncClient() as client:
            task = await send_task_and_wait(
                client,
                WEB_SEARCH_URL,
                "e2e-news-001",
                "Get recent news about artificial intelligence",
                timeout=60.0
            )

        assert task["status"]["state"] == "completed"
        text = extract_artifact_text(task)
        assert len(text) > 50


# ══════════════════════════════════════════════════════════════
# SCENARIO 4: DATA ANALYSIS AGENT — DIRECT A2A CALL
# ══════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestDataAnalysisAgentE2E:
    """Direct A2A calls to Data Analysis Agent."""

    @pytest.mark.asyncio
    async def test_statistical_analysis(self):
        """
        Ask Data Analysis Agent to run stats on data.
        Verifies Python execution and statistical tools work.
        """
        async with httpx.AsyncClient() as client:
            task = await send_task_and_wait(
                client,
                DATA_ANALYSIS_URL,
                "e2e-stats-001",
                (
                    "Calculate statistics for this dataset: "
                    "[23, 45, 12, 67, 34, 89, 56, 78, 90, 11]. "
                    "Find mean, median, and standard deviation."
                ),
                timeout=60.0
            )

        assert task["status"]["state"] == "completed"
        text = extract_artifact_text(task)

        # Response should contain numerical analysis
        assert len(text) > 50
        # At least one of these terms should appear
        has_stats = any(
            term in text.lower()
            for term in ["mean", "median", "average",
                         "standard", "statistics"]
        )
        assert has_stats, f"No statistical terms in: {text[:200]}"

    @pytest.mark.asyncio
    async def test_python_code_execution(self):
        """Data Analysis Agent can run Python code."""
        async with httpx.AsyncClient() as client:
            task = await send_task_and_wait(
                client,
                DATA_ANALYSIS_URL,
                "e2e-python-001",
                (
                    "Run this Python code and show the output: "
                    "numbers = [1, 2, 3, 4, 5]; "
                    "print(f'Sum: {sum(numbers)}'); "
                    "print(f'Average: {sum(numbers)/len(numbers)}')"
                ),
                timeout=60.0
            )

        assert task["status"]["state"] == "completed"
        text = extract_artifact_text(task)
        assert len(text) > 20


# ══════════════════════════════════════════════════════════════
# SCENARIO 5: CODE AGENT — DIRECT A2A CALL
# ══════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestCodeAgentE2E:
    """Direct A2A calls to Code Agent."""

    @pytest.mark.asyncio
    async def test_code_explanation(self):
        """Code Agent explains Python code."""
        async with httpx.AsyncClient() as client:
            task = await send_task_and_wait(
                client,
                CODE_URL,
                "e2e-explain-001",
                (
                    "Explain what this Python code does: "
                    "def fibonacci(n): "
                    "  if n <= 1: return n; "
                    "  return fibonacci(n-1) + fibonacci(n-2)"
                ),
                timeout=60.0
            )

        assert task["status"]["state"] == "completed"
        text = extract_artifact_text(task)
        assert len(text) > 50
        assert "fibonacci" in text.lower() or "recursive" in text.lower()

    @pytest.mark.asyncio
    async def test_code_analysis(self):
        """Code Agent analyzes code complexity."""
        async with httpx.AsyncClient() as client:
            task = await send_task_and_wait(
                client,
                CODE_URL,
                "e2e-analyze-001",
                (
                    "Analyze this Python function: "
                    "def add(a, b): return a + b"
                ),
                timeout=60.0
            )

        assert task["status"]["state"] == "completed"
        text = extract_artifact_text(task)
        assert len(text) > 20


# ══════════════════════════════════════════════════════════════
# SCENARIO 6: ORCHESTRATOR — MULTI-AGENT COORDINATION
# The crown jewel — tests the full marketplace
# ══════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestOrchestratorE2E:
    """
    Full orchestration tests.
    These exercise the entire system end-to-end.
    """

    @pytest.mark.asyncio
    async def test_orchestrate_simple_search(self):
        """
        Orchestrator handles a simple search query.
        Verifies: registry → agent discovery → delegation → response.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{ORCHESTRATOR_URL}/orchestrate",
                headers=AUTH_HEADERS,
                json={
                    "query": (
                        "Search for what Python programming language is "
                        "and give me a one paragraph summary"
                    )
                },
                timeout=TASK_TIMEOUT
            )

        assert response.status_code == 200
        data = response.json()

        assert "answer" in data
        assert len(data["answer"]) > 100, (
            f"Answer too short: {data['answer']}"
        )
        assert data.get("state") == "completed"

    @pytest.mark.asyncio
    async def test_orchestrate_via_a2a_protocol(self):
        """
        Send task to orchestrator via standard A2A protocol
        (not the convenience /orchestrate endpoint).
        Verifies A2A compliance of orchestrator itself.
        """
        async with httpx.AsyncClient() as client:
            task = await send_task_and_wait(
                client,
                ORCHESTRATOR_URL,
                "e2e-orch-a2a-001",
                "Search for the history of artificial intelligence",
                timeout=TASK_TIMEOUT
            )

        assert task["status"]["state"] == "completed"
        text = extract_artifact_text(task)
        assert len(text) > 100

    @pytest.mark.asyncio
    async def test_orchestrate_multi_agent_compound_query(self):
        """
        Complex query requiring multiple agents.
        Orchestrator must decompose, delegate, synthesize.

        Expected flow:
        WebSearch → find data
        DataAnalysis → process numbers (if applicable)
        Synthesize → coherent answer
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{ORCHESTRATOR_URL}/orchestrate",
                headers=AUTH_HEADERS,
                json={
                    "query": (
                        "Search for top 3 programming languages in 2024, "
                        "then analyze which one has the highest job market demand "
                        "based on what you find"
                    )
                },
                timeout=TASK_TIMEOUT
            )

        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert len(data["answer"]) > 150

        # Should have used at least one agent
        calls_made = data.get("calls_made", 0)
        assert calls_made >= 1, (
            f"Orchestrator made {calls_made} agent calls — expected >= 1"
        )

    @pytest.mark.asyncio
    async def test_orchestrate_code_analysis_query(self):
        """
        Query that should route to Code Agent.
        Tests orchestrator's agent selection logic.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{ORCHESTRATOR_URL}/orchestrate",
                headers=AUTH_HEADERS,
                json={
                    "query": (
                        "Explain what this Python code does and "
                        "analyze its complexity: "
                        "def bubble_sort(arr): "
                        "  n = len(arr); "
                        "  for i in range(n): "
                        "    for j in range(0, n-i-1): "
                        "      if arr[j] > arr[j+1]: "
                        "        arr[j], arr[j+1] = arr[j+1], arr[j]"
                    )
                },
                timeout=TASK_TIMEOUT
            )

        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert len(data["answer"]) > 50


# ══════════════════════════════════════════════════════════════
# SCENARIO 7: A2A PROTOCOL COMPLIANCE
# Verify the protocol spec is correctly implemented
# ══════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestA2AProtocolCompliance:
    """
    Verify A2A protocol implementation across all agents.
    Tests protocol correctness, not business logic.
    """

    @pytest.mark.asyncio
    async def test_json_rpc_envelope_structure(self):
        """Response must be valid JSON-RPC 2.0 envelope."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{WEB_SEARCH_URL}/a2a/tasks/send",
                headers=AUTH_HEADERS,
                json=make_task_request(
                    "e2e-proto-001",
                    "Quick test"
                ),
                timeout=TASK_TIMEOUT
            )

        assert response.status_code == 200
        data = response.json()

        # JSON-RPC 2.0 required fields
        assert data["jsonrpc"] == "2.0"
        assert "id" in data
        assert "result" in data or "error" in data

        # If result, must have Task structure
        if data.get("result"):
            result = data["result"]
            assert "id" in result
            assert "status" in result
            assert "state" in result["status"]

    @pytest.mark.asyncio
    async def test_task_not_found_error_code(self):
        """
        tasks/get for non-existent task must return
        A2A error code -32001 (TASK_NOT_FOUND).
        HTTP status must be 200 (error in body).
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{WEB_SEARCH_URL}/a2a/tasks/get",
                headers=AUTH_HEADERS,
                json={
                    "jsonrpc": "2.0",
                    "id": "proto-test",
                    "method": "tasks/get",
                    "params": {"id": "task-does-not-exist-xyz"}
                },
                timeout=10.0
            )

        assert response.status_code == 200  # Always 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32001

    @pytest.mark.asyncio
    async def test_auth_required_on_all_task_endpoints(self):
        """All task endpoints must reject unauthenticated requests."""
        endpoints = [
            ("POST", f"{WEB_SEARCH_URL}/a2a/tasks/send"),
            ("POST", f"{WEB_SEARCH_URL}/a2a/tasks/get"),
            ("POST", f"{WEB_SEARCH_URL}/a2a/tasks/cancel"),
            ("POST", f"{DATA_ANALYSIS_URL}/a2a/tasks/send"),
            ("POST", f"{CODE_URL}/a2a/tasks/send"),
        ]

        async with httpx.AsyncClient() as client:
            for method, url in endpoints:
                response = await client.post(
                    url,
                    # No auth header
                    json={"jsonrpc": "2.0", "method": "test",
                          "params": {}},
                    timeout=10.0
                )
                assert response.status_code == 401, (
                    f"Expected 401 at {url}, got {response.status_code}"
                )

    @pytest.mark.asyncio
    async def test_agent_cards_are_public(self):
        """Agent cards must be accessible without authentication."""
        urls = [
            f"{WEB_SEARCH_URL}/.well-known/agent.json",
            f"{DATA_ANALYSIS_URL}/.well-known/agent.json",
            f"{DOCUMENT_URL}/.well-known/agent.json",
            f"{CODE_URL}/.well-known/agent.json",
        ]
        async with httpx.AsyncClient() as client:
            for url in urls:
                response = await client.get(url, timeout=10.0)
                assert response.status_code == 200, (
                    f"Agent card not public at {url}"
                )

    @pytest.mark.asyncio
    async def test_task_state_is_terminal_on_completion(self):
        """
        Completed task must have state in terminal states.
        Terminal: completed, failed, canceled.
        """
        terminal = {"completed", "failed", "canceled"}

        async with httpx.AsyncClient() as client:
            task = await send_task_and_wait(
                client,
                WEB_SEARCH_URL,
                "e2e-terminal-001",
                "Search for Python",
                timeout=60.0
            )

        assert task["status"]["state"] in terminal, (
            f"Non-terminal state: {task['status']['state']}"
        )