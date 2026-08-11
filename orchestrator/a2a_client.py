"""
A2A Protocol HTTP client.

Handles all agent-to-agent communication:
  - Sends tasks/send, tasks/get, tasks/cancel JSON-RPC requests
  - Fetches agent cards from /.well-known/agent.json
  - Polls task status until completion (tasks can be async)

Design:
  - One shared httpx.AsyncClient per OrchestratorA2AClient instance
  - Caller must use as async context manager OR call aclose()
  - All methods raise A2AClientError on protocol/network failures
  - Never raises on task-level failures (failed/canceled tasks
    return via A2ATaskError — caller decides what to do)
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import structlog

from shared.a2a_types import AgentCard, Task, TaskState
from shared.config import settings

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class A2AClientError(Exception):
    """Raised on network errors or JSON-RPC protocol errors."""

    def __init__(self, message: str, code: int = 0, agent_url: str = ""):
        super().__init__(message)
        self.code = code
        self.agent_url = agent_url


class A2ATaskError(A2AClientError):
    """Raised when a task reaches failed/canceled state."""

    def __init__(self, message: str, task: Task):
        super().__init__(message)
        self.task = task


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OrchestratorA2AClient:
    """
    Async HTTP client for A2A protocol communication.

    Usage:
        async with OrchestratorA2AClient() as client:
            task = await client.send_task(
                agent_url="http://localhost:8001",
                message="Search for Python async patterns",
            )
    """

    def __init__(
        self,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
        max_poll_attempts: int = 60,
    ):
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._max_poll_attempts = max_poll_attempts
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {settings.a2a_bearer_token}",
                "Content-Type": "application/json",
                "User-Agent": "A2A-Orchestrator/1.0",
            },
        )

    async def __aenter__(self) -> "OrchestratorA2AClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -----------------------------------------------------------------------
    # Core JSON-RPC transport
    # -----------------------------------------------------------------------

    async def _rpc(
        self,
        agent_url: str,
        method: str,
        params: dict,
        rpc_id: str | None = None,
    ) -> dict:
        """
        Send a JSON-RPC 2.0 request and return the result dict.

        Raises:
            A2AClientError: network error, non-200 HTTP,
                            or JSON-RPC error response.
        """
        rpc_id = rpc_id or str(uuid.uuid4())
        endpoint = f"{agent_url.rstrip('/')}/a2a/tasks/{method.split('/')[-1]}"

        payload = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": method,
            "params": params,
        }

        log.debug("a2a_rpc_request", agent=agent_url, method=method, id=rpc_id)

        try:
            response = await self._client.post(endpoint, json=payload)
        except httpx.TimeoutException:
            raise A2AClientError(
                f"Request to {agent_url} timed out ({self._timeout}s)",
                agent_url=agent_url,
            )
        except httpx.ConnectError:
            raise A2AClientError(
                f"Cannot connect to agent at {agent_url}. Is it running?",
                agent_url=agent_url,
            )
        except httpx.RequestError as e:
            raise A2AClientError(str(e), agent_url=agent_url)

        if response.status_code == 401:
            raise A2AClientError(
                f"Authentication failed for {agent_url}. Check A2A_BEARER_TOKEN.",
                code=401,
                agent_url=agent_url,
            )

        if response.status_code != 200:
            raise A2AClientError(
                f"Unexpected HTTP {response.status_code} from {agent_url}",
                code=response.status_code,
                agent_url=agent_url,
            )

        try:
            body = response.json()
        except Exception:
            raise A2AClientError(
                f"Invalid JSON response from {agent_url}",
                agent_url=agent_url,
            )

        # JSON-RPC error in response body
        if "error" in body and body["error"] is not None:
            err = body["error"]
            raise A2AClientError(
                f"JSON-RPC error from {agent_url}: {err.get('message', err)}",
                code=err.get("code", 0),
                agent_url=agent_url,
            )

        if "result" not in body:
            raise A2AClientError(
                f"JSON-RPC response missing 'result' from {agent_url}",
                agent_url=agent_url,
            )

        log.debug("a2a_rpc_response", agent=agent_url, method=method)
        return body["result"]

    # -----------------------------------------------------------------------
    # Agent card
    # -----------------------------------------------------------------------

    async def get_agent_card(self, agent_url: str) -> AgentCard:
        """
        Fetch agent card from /.well-known/agent.json.
        No auth required — agent card is public.
        """
        url = f"{agent_url.rstrip('/')}/.well-known/agent.json"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            return AgentCard(**response.json())
        except httpx.RequestError as e:
            raise A2AClientError(str(e), agent_url=agent_url)
        except Exception as e:
            raise A2AClientError(
                f"Failed to parse agent card from {agent_url}: {e}",
                agent_url=agent_url,
            )

    # -----------------------------------------------------------------------
    # Task operations
    # -----------------------------------------------------------------------

    async def send_task(
        self,
        agent_url: str,
        message: str,
        task_id: str | None = None,
    ) -> Task:
        """
        Send a task to an agent and wait for completion.

        1. Calls tasks/send → gets initial Task
        2. If already terminal → returns immediately
        3. Otherwise polls tasks/get until terminal state

        Returns:
            Task in completed state.

        Raises:
            A2AClientError: Network or protocol error.
            A2ATaskError: Task reached failed/canceled state.
        """
        task_id = task_id or str(uuid.uuid4())

        log.info(
            "a2a_send_task",
            agent=agent_url,
            task_id=task_id,
            message_preview=message[:80],
        )

        result = await self._rpc(
            agent_url=agent_url,
            method="tasks/send",
            params={
                "id": task_id,
                "message": {
                    "role": "user",
                    "parts": [{"text": message}],
                },
            },
            rpc_id=task_id,
        )

        task = Task(**result)

        # Already terminal — agents that process synchronously return
        # completed/failed immediately from tasks/send
        if task.status.state in _TERMINAL_STATES:
            log.info(
                "a2a_task_immediate",
                task_id=task_id,
                state=task.status.state.value,
            )
            return self._check_task_state(task, agent_url)

        # Poll until terminal state
        return await self._poll_task(agent_url, task_id)

    async def get_task(self, agent_url: str, task_id: str) -> Task:
        """Fetch current task state (single poll, no waiting)."""
        result = await self._rpc(
            agent_url=agent_url,
            method="tasks/get",
            params={"id": task_id},
        )
        return Task(**result)

    async def cancel_task(self, agent_url: str, task_id: str) -> Task:
        """Request task cancellation."""
        result = await self._rpc(
            agent_url=agent_url,
            method="tasks/cancel",
            params={"id": task_id},
        )
        return Task(**result)

    # -----------------------------------------------------------------------
    # Health check
    # -----------------------------------------------------------------------

    async def check_health(self, agent_url: str) -> bool:
        """
        Ping agent /health endpoint.
        Returns True if healthy, False if unreachable.
        Never raises.
        """
        try:
            url = f"{agent_url.rstrip('/')}/health"
            response = await self._client.get(url)
            return response.status_code == 200
        except Exception:
            return False

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _poll_task(self, agent_url: str, task_id: str) -> Task:
        """Poll tasks/get until task reaches a terminal state."""
        for attempt in range(self._max_poll_attempts):
            await asyncio.sleep(self._poll_interval)

            task = await self.get_task(agent_url, task_id)

            log.debug(
                "a2a_poll",
                task_id=task_id,
                state=task.status.state.value,
                attempt=attempt + 1,
            )

            if task.status.state in _TERMINAL_STATES:
                return self._check_task_state(task, agent_url)

            if task.status.state == TaskState.INPUT_REQUIRED:
                log.warning("a2a_task_input_required", task_id=task_id)
                try:
                    await self.cancel_task(agent_url, task_id)
                except A2AClientError:
                    pass
                raise A2AClientError(
                    f"Task {task_id} requires interactive input — "
                    "orchestrator cannot continue",
                    agent_url=agent_url,
                )

        # Exhausted polls
        raise A2AClientError(
            f"Task {task_id} did not complete after "
            f"{self._max_poll_attempts} polls ({self._max_poll_attempts}s)",
            agent_url=agent_url,
        )

    def _check_task_state(self, task: Task, agent_url: str) -> Task:
        """Return task if completed, raise A2ATaskError if failed/canceled."""
        if task.status.state == TaskState.COMPLETED:
            return task

        # Extract error message — TaskStatus.message is Message | None
        error_msg = f"Task {task.id} {task.status.state.value}"
        if task.status.message and task.status.message.parts:
            for part in task.status.message.parts:
                if hasattr(part, "text") and part.text:
                    error_msg = part.text
                    break

        raise A2ATaskError(
            f"Agent at {agent_url} returned {task.status.state.value}: {error_msg}",
            task=task,
        )

    # -----------------------------------------------------------------------
    # Convenience: extract text from completed task
    # -----------------------------------------------------------------------

    @staticmethod
    def extract_text_result(task: Task) -> str:
        """
        Extract first text artifact from a completed task.
        Returns empty string if no text artifact found.
        """
        if not task.artifacts:
            return ""
        for artifact in task.artifacts:
            for part in artifact.parts:
                if hasattr(part, "text") and part.text:
                    return part.text
        return ""


# Terminal state set — used for comparisons throughout
_TERMINAL_STATES = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}