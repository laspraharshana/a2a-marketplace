# agents/base/a2a_server.py
"""
Base A2A Agent Server.

Provides reusable FastAPI application factory with:
- Standard A2A endpoints (agent.json, health, tasks/*)
- JSON-RPC 2.0 envelope handling
- Bearer token authentication
- In-memory task store (Week 6 → Redis)
- Gemini tool-calling loop with fallback synthesis
- MCP bridge pattern

Subclasses provide:
- agent_card: AgentCard
- get_tool_declarations() -> list[dict]
- execute_tool(name, args) -> str
- get_system_prompt() -> str
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google import genai
from google.genai import types as genai_types

from shared.a2a_types import (
    A2AErrorCode,
    AgentCard,
    Artifact,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    Message,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
)
from shared.config import get_settings
from shared.logging_config import setup_logging

logger = structlog.get_logger(__name__)
settings = get_settings()

# ─────────────────────────────────────────────
# Auth (same pattern as Web Search Agent)
# ─────────────────────────────────────────────

security = HTTPBearer(auto_error=False)


def verify_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Use Bearer scheme")
    if credentials.credentials != settings.a2a_bearer_token:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return credentials.credentials


# ─────────────────────────────────────────────
# Base Agent Class
# ─────────────────────────────────────────────

class BaseA2AAgent(ABC):
    """
    Abstract base for all A2A agents.

    Implements the full A2A + JSON-RPC protocol layer.
    Subclasses only need to define tools and system prompt.

    Design: composition over inheritance for the FastAPI app.
    build_app() returns a configured FastAPI instance.
    This lets each agent call build_app() at module level
    so Uvicorn can import it directly.
    """

    # Subclasses set this at class level
    agent_card: AgentCard

    def __init__(self) -> None:
        self._task_store: dict[str, Task] = {}
        self._client = genai.Client(api_key=settings.google_api_key)
        self._log = structlog.get_logger(self.__class__.__name__)

    # ── Abstract interface ────────────────────────────────────────────

    @abstractmethod
    def get_tool_declarations(self) -> list[dict[str, Any]]:
        """
        Return Gemini-compatible tool declarations.
        Format: [{"name": str, "description": str, "parameters": {...}}]
        Note: key is "parameters" not "inputSchema" (Gemini format).
        """
        ...

    @abstractmethod
    async def execute_tool(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        """
        Execute a named tool and return string result.
        Called by the Gemini tool-calling loop.
        Errors should be returned as strings, not raised,
        so Gemini can incorporate them into its response.
        """
        ...

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system instruction for this agent's Gemini calls."""
        ...

    # ── Gemini tool-calling loop ──────────────────────────────────────

    async def run_agent_with_tools(self, task: str) -> str:
        """
        Full Gemini agentic loop with tool calling and fallback synthesis.

        Protocol:
        1. Send task + tools to Gemini
        2. If Gemini returns function_call parts → execute tools, loop
        3. If Gemini returns text → done
        4. After max_iterations, synthesize from collected tool results
        5. If no tool results either → return structured error message

        The fallback synthesis handles DDG rate limits and other cases
        where Gemini exhausts iterations without producing final text.
        """
        tool_declarations = self.get_tool_declarations()
        gemini_tools = genai_types.Tool(
            function_declarations=tool_declarations
        )

        messages: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": task}]}]
        all_tool_results: list[str] = []
        max_iterations = 6

        for iteration in range(max_iterations):
            self._log.debug(
                "gemini_iteration",
                iteration=iteration,
                message_count=len(messages),
            )

            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=settings.agent_model,
                contents=messages,
                config=genai_types.GenerateContentConfig(
                    tools=[gemini_tools],
                    system_instruction=self.get_system_prompt(),
                    temperature=0.1,
                ),
            )

            # Check for final text response
            final_text = self._extract_text(response)
            if final_text:
                self._log.info("agent_completed", iterations=iteration + 1)
                return final_text

            # Check for tool calls
            tool_calls = self._extract_tool_calls(response)
            if not tool_calls:
                # Gemini returned neither text nor tool calls
                self._log.warning("empty_gemini_response", iteration=iteration)
                break

            # Execute all tool calls (Gemini may batch multiple)
            tool_results_this_round: list[dict[str, Any]] = []
            for tool_call in tool_calls:
                tool_name = tool_call.name
                tool_args = dict(tool_call.args) if tool_call.args else {}

                self._log.info("executing_tool", tool=tool_name, args=tool_args)
                result_text = await self.execute_tool(tool_name, tool_args)

                # Collect non-error results for fallback synthesis
                if not result_text.startswith("Error") and \
                   "No results" not in result_text:
                    all_tool_results.append(f"[{tool_name}]: {result_text}")

                tool_results_this_round.append({
                    "tool_name": tool_name,
                    "result": result_text,
                })

            # Append model response + tool results to conversation
            messages.append({"role": "model", "parts": response.candidates[0].content.parts})
            messages.append({
                "role": "user",
                "parts": [
                    {
                        "function_response": {
                            "name": r["tool_name"],
                            "response": {"result": r["result"]},
                        }
                    }
                    for r in tool_results_this_round
                ],
            })

        # ── Fallback synthesis ────────────────────────────────────────
        if all_tool_results:
            self._log.info(
                "fallback_synthesis",
                collected_results=len(all_tool_results),
            )
            combined = "\n\n---\n\n".join(all_tool_results)
            synthesis_prompt = (
                f"Based on these tool results, answer the request:\n"
                f"Request: {task}\n\n"
                f"Tool Results:\n{combined}\n\n"
                f"Provide a clear, comprehensive answer."
            )
            synthesis_response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=settings.agent_model,
                contents=synthesis_prompt,
                config=genai_types.GenerateContentConfig(temperature=0.1),
            )
            synthesis_text = self._extract_text(synthesis_response)
            if synthesis_text:
                return synthesis_text

        return (
            f"Agent could not complete task after {max_iterations} iterations. "
            f"Task: {task}"
        )

    def _extract_text(self, response: Any) -> str:
        """Extract plain text from Gemini response, empty string if none."""
        try:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    return part.text.strip()
        except (AttributeError, IndexError):
            pass
        return ""

    def _extract_tool_calls(self, response: Any) -> list[Any]:
        """Extract function_call parts from Gemini response."""
        tool_calls = []
        try:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    tool_calls.append(part.function_call)
        except (AttributeError, IndexError):
            pass
        return tool_calls

    # ── Task store (in-memory, Week 6 → Redis) ───────────────────────

    def _create_task(self, request_id: str, message: Message) -> Task:
        task_id = str(uuid.uuid4())
        task = Task(
            id=task_id,
            status=TaskStatus(
                state=TaskState.SUBMITTED,
                timestamp=datetime.now(timezone.utc),
            ),
            history=[message],
        )
        self._task_store[task_id] = task
        return task

    def _get_task(self, task_id: str) -> Task | None:
        return self._task_store.get(task_id)

    def _update_task_working(self, task_id: str) -> None:
        task = self._task_store.get(task_id)
        if task:
            task.status = TaskStatus(
                state=TaskState.WORKING,
                timestamp=datetime.now(timezone.utc),
            )

    def _complete_task(self, task_id: str, result_text: str) -> None:
        task = self._task_store.get(task_id)
        if task:
            task.status = TaskStatus(
                state=TaskState.COMPLETED,
                timestamp=datetime.now(timezone.utc),
            )
            task.artifacts = [
                Artifact(
                    parts=[TextPart(type="text", text=result_text)],
                    index=0,
                )
            ]

    def _fail_task(self, task_id: str, error_msg: str) -> None:
        task = self._task_store.get(task_id)
        if task:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                timestamp=datetime.now(timezone.utc),
                message=error_msg,
            )

    def _cancel_task(self, task_id: str) -> bool:
        task = self._task_store.get(task_id)
        if not task:
            return False
        if task.status.state in (TaskState.COMPLETED, TaskState.FAILED):
            return False  # Cannot cancel terminal tasks
        task.status = TaskStatus(
            state=TaskState.CANCELED,
            timestamp=datetime.now(timezone.utc),
        )
        return True

    # ── Request handlers (extracted for testability) ──────────────────

    async def handle_tasks_send(self, body: dict[str, Any]) -> dict[str, Any]:
        """
        Handle tasks/send JSON-RPC method.
        Creates task, runs agent, returns completed task.
        """
        rpc_id = body.get("id")
        params = body.get("params", {})

        # Extract message from params
        # A2A spec: params.message is the Message object
        try:
            msg_data = params.get("message", {})
            message = Message(**msg_data)
        except Exception as exc:
            return JSONRPCResponse(
                id=rpc_id,
                error=JSONRPCError(
                    code=A2AErrorCode.INVALID_PARAMS,
                    message=f"Invalid message format: {exc}",
                ),
            ).model_dump(mode="json")

        # Extract task text from message parts
        task_text = ""
        for part in message.parts:
            if hasattr(part, "text"):
                task_text = part.text
                break

        if not task_text:
            return JSONRPCResponse(
                id=rpc_id,
                error=JSONRPCError(
                    code=A2AErrorCode.INVALID_PARAMS,
                    message="No text content found in message parts",
                ),
            ).model_dump(mode="json")

        # Create task
        task = self._create_task(str(rpc_id), message)
        self._update_task_working(task.id)

        self._log.info(
            "task_received",
            task_id=task.id,
            preview=task_text[:80],
        )

        # Run agent
        try:
            result = await self.run_agent_with_tools(task_text)
            self._complete_task(task.id, result)
            self._log.info("task_completed", task_id=task.id)
        except Exception as exc:
            self._log.exception("task_failed", task_id=task.id, error=str(exc))
            self._fail_task(task.id, str(exc))

        return JSONRPCResponse(
            id=rpc_id,
            result=self._task_store[task.id].model_dump(mode="json"),
        ).model_dump(mode="json")

    async def handle_tasks_get(self, body: dict[str, Any]) -> dict[str, Any]:
        """Handle tasks/get JSON-RPC method."""
        rpc_id = body.get("id")
        params = body.get("params", {})
        task_id = params.get("id")

        if not task_id:
            return JSONRPCResponse(
                id=rpc_id,
                error=JSONRPCError(
                    code=A2AErrorCode.INVALID_PARAMS,
                    message="Missing task id in params",
                ),
            ).model_dump(mode="json")

        task = self._get_task(task_id)
        if not task:
            return JSONRPCResponse(
                id=rpc_id,
                error=JSONRPCError(
                    code=A2AErrorCode.TASK_NOT_FOUND,
                    message=f"Task {task_id} not found",
                ),
            ).model_dump()

        return JSONRPCResponse(
            id=rpc_id,
            result=task.model_dump(mode="json"),
        ).model_dump(mode="json")

    async def handle_tasks_cancel(self, body: dict[str, Any]) -> dict[str, Any]:
        """Handle tasks/cancel JSON-RPC method."""
        rpc_id = body.get("id")
        params = body.get("params", {})
        task_id = params.get("id")

        if not task_id:
            return JSONRPCResponse(
                id=rpc_id,
                error=JSONRPCError(
                    code=A2AErrorCode.INVALID_PARAMS,
                    message="Missing task id in params",
                ),
            ).model_dump()

        task = self._get_task(task_id)
        if not task:
            return JSONRPCResponse(
                id=rpc_id,
                error=JSONRPCError(
                    code=A2AErrorCode.TASK_NOT_FOUND,
                    message=f"Task {task_id} not found",
                ),
            ).model_dump()

        cancelled = self._cancel_task(task_id)
        if not cancelled:
            return JSONRPCResponse(
                id=rpc_id,
                error=JSONRPCError(
                    code=A2AErrorCode.INTERNAL_ERROR,
                    message=f"Task {task_id} cannot be cancelled "
                            f"(state: {task.status.state})",
                ),
            ).model_dump()

        return JSONRPCResponse(
            id=rpc_id,
            result=self._task_store[task_id].model_dump(mode="json"),
        ).model_dump(mode="json")

    # ── FastAPI app factory ───────────────────────────────────────────

    def build_app(self) -> FastAPI:
        agent = self

        # Create a bound auth function unique to this agent instance.
        # Tests override: app.dependency_overrides[agent_instance.auth_dependency]
        def auth_dependency(
            credentials: HTTPAuthorizationCredentials | None = Depends(security),
        ) -> str:
            return verify_bearer_token(credentials)

        # Store on instance so tests can reference it
        agent.auth_dependency = auth_dependency

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            setup_logging()
            agent._log.info("agent_starting", name=agent.agent_card.name)
            yield
            agent._log.info("agent_stopping", name=agent.agent_card.name)

        app = FastAPI(
            title=agent.agent_card.name,
            description=agent.agent_card.description,
            version=agent.agent_card.version,
            lifespan=lifespan,
        )

        @app.get("/.well-known/agent.json", include_in_schema=False)
        async def get_agent_card() -> dict[str, Any]:
            return agent.agent_card.model_dump()

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {
                "status": "healthy",
                "agent": agent.agent_card.name,
                "version": agent.agent_card.version,
            }

        @app.post("/a2a/tasks/send")
        async def tasks_send(
            request: Request,
            _token: str = Depends(auth_dependency),
        ) -> JSONResponse:
            body = await request.json()
            result = await agent.handle_tasks_send(body)
            return JSONResponse(content=result)

        @app.post("/a2a/tasks/get")
        async def tasks_get(
            request: Request,
            _token: str = Depends(auth_dependency),
        ) -> JSONResponse:
            body = await request.json()
            result = await agent.handle_tasks_get(body)
            return JSONResponse(content=result)

        @app.post("/a2a/tasks/cancel")
        async def tasks_cancel(
            request: Request,
            _token: str = Depends(auth_dependency),
        ) -> JSONResponse:
            body = await request.json()
            result = await agent.handle_tasks_cancel(body)
            return JSONResponse(content=result)

        return app