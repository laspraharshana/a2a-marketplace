"""
Orchestrator — FastAPI microservice on port 8000.

The orchestrator is itself an A2A agent (has agent card, accepts tasks/send).

Additional endpoints beyond standard A2A:
  GET /agents          — list available agents from registry
  POST /orchestrate    — direct JSON API for easy testing

Flow for tasks/send:
  1. Fetch available agents from registry
  2. Run LangGraph orchestrator graph
  3. Graph: plan → execute agents → synthesize
  4. Return completed Task with synthesized answer
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import httpx
import structlog
import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from orchestrator.task_decomposer import run_orchestrator
from shared.a2a_types import (
    A2AErrorCode,
    AgentCapabilities,
    AgentCard,
    AgentProvider,
    AgentSkill,
    Artifact,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
)
from shared.config import settings
from shared.logging_config import setup_logging

log = structlog.get_logger(__name__)
setup_logging()


# ---------------------------------------------------------------------------
# Registry client helpers
# ---------------------------------------------------------------------------

async def fetch_available_agents() -> list[dict]:
    """
    Fetch active agents from the registry.
    Returns list of dicts with: name, url, description, skills.
    Empty list if registry is unreachable.
    """
    registry_url = f"http://localhost:{settings.registry_port}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{registry_url}/agents")
            if response.status_code != 200:
                log.warning("registry_fetch_failed", status=response.status_code)
                return []

            data = response.json()
            agents = data.get("agents", [])

            result = []
            for agent in agents:
                card = agent.get("agent_card", {})
                skills = card.get("skills", [])
                skill_names = [
                    s.get("name", s.get("id", ""))
                    for s in (skills if isinstance(skills, list) else [])
                ]
                result.append({
                    "name": agent.get("name", ""),
                    "url": agent.get("url", ""),
                    "description": card.get("description", ""),
                    "skills": skill_names,
                    "version": agent.get("version", "1.0.0"),
                })

            log.info("registry_agents_fetched", count=len(result))
            return result

    except Exception as e:
        log.warning("registry_fetch_error", error=str(e))
        return []


# ---------------------------------------------------------------------------
# Orchestrator agent card
# ---------------------------------------------------------------------------

AGENT_CARD = AgentCard(
    name="orchestrator",
    description=(
        "Multi-agent orchestrator that routes tasks to specialized agents "
        "(Web Search, Data Analysis, Document Processing, Code Analysis) "
        "and synthesizes their results into a coherent response."
    ),
    url=f"http://localhost:{settings.orchestrator_port}",
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
            id="orchestrate",
            name="Multi-Agent Orchestration",
            description=(
                "Decomposes complex queries, routes to specialized agents, "
                "and synthesizes results. Can combine web search, data analysis, "
                "document processing, and code analysis in a single workflow."
            ),
            examples=[
                "Search for recent AI papers and summarize the key findings",
                "Analyze this dataset and explain what patterns you find",
                "Find documentation for Python asyncio and explain with examples",
                "Review this code, run it, and suggest improvements",
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Task store (in-memory)
# ---------------------------------------------------------------------------

_task_store: dict[str, Task] = {}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

security = HTTPBearer(auto_error=False)


def verify_token(
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


# ---------------------------------------------------------------------------
# Core orchestration handler
# ---------------------------------------------------------------------------

async def handle_orchestrate(query: str, task_id: str) -> Task:
    """
    Run the full orchestration pipeline for a query.

    TaskStatus.message is Message | None in your a2a_types.py,
    so we never set it to a plain string.
    """
    # Update task to working state
    _task_store[task_id] = Task(
        id=task_id,
        status=TaskStatus(state=TaskState.WORKING),
    )

    # Get agents from registry
    available_agents = await fetch_available_agents()

    try:
        final_answer, calls_made = await run_orchestrator(
            query=query,
            available_agents=available_agents,
        )

        agent_summary = ", ".join(
            c["agent_name"] for c in calls_made if c["success"]
        ) or "direct synthesis"

        task = Task(
            id=task_id,
            status=TaskStatus(state=TaskState.COMPLETED),
            artifacts=[
                Artifact(
                    name="orchestrated_response",
                    parts=[TextPart(text=final_answer)],
                    metadata={
                        "agents_called": len(calls_made),
                        "agents_succeeded": sum(
                            1 for c in calls_made if c["success"]
                        ),
                        "agent_names": [c["agent_name"] for c in calls_made],
                        "agent_summary": agent_summary,
                    },
                )
            ],
        )

    except Exception as e:
        log.exception("orchestration_failed", task_id=task_id)
        task = Task(
            id=task_id,
            status=TaskStatus(state=TaskState.FAILED),
        )

    _task_store[task_id] = task
    return task


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("orchestrator_starting", port=settings.orchestrator_port)
    yield
    log.info("orchestrator_stopping")


app = FastAPI(
    title="A2A Orchestrator",
    version="1.0.0",
    lifespan=lifespan,
)


# -----------------------------------------------------------------------
# Public endpoints (no auth)
# -----------------------------------------------------------------------

@app.get("/.well-known/agent.json")
async def agent_card() -> JSONResponse:
    return JSONResponse(AGENT_CARD.model_dump(mode="json"))


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "healthy", "service": "orchestrator"})


@app.get("/agents")
async def list_agents() -> JSONResponse:
    """List agents currently available via registry."""
    agents = await fetch_available_agents()
    return JSONResponse({"agents": agents, "count": len(agents)})


# -----------------------------------------------------------------------
# Convenience endpoint for testing (not part of A2A spec)
# -----------------------------------------------------------------------

@app.post("/orchestrate")
async def orchestrate_direct(
    body: dict,
    token: str = Depends(verify_token),
) -> JSONResponse:
    """
    Direct orchestration endpoint — simpler than JSON-RPC for testing.

    Body: {"query": "your question here"}
    """
    query = body.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="'query' field required")

    task_id = str(uuid.uuid4())
    task = await handle_orchestrate(query, task_id)

    answer = ""
    if task.artifacts:
        for artifact in task.artifacts:
            for part in artifact.parts:
                if hasattr(part, "text") and part.text:
                    answer = part.text
                    break

    metadata = {}
    if task.artifacts and task.artifacts[0].metadata:
        metadata = task.artifacts[0].metadata

    return JSONResponse({
        "answer": answer,
        "task_id": task_id,
        "state": task.status.state.value,
        "agents_called": metadata.get("agent_names", []),
        "calls_made": metadata.get("agents_called", 0),
    })


# -----------------------------------------------------------------------
# A2A task endpoints (JSON-RPC, auth required)
# -----------------------------------------------------------------------

@app.post("/a2a/tasks/send")
async def tasks_send(
    body: dict,
    token: str = Depends(verify_token),
) -> JSONResponse:
    try:
        request = JSONRPCRequest(**body)
    except Exception:
        return JSONResponse(
            JSONRPCResponse(
                id=body.get("id"),
                error=JSONRPCError(
                    code=A2AErrorCode.INTERNAL_ERROR,
                    message="Invalid JSON-RPC request",
                ),
            ).model_dump(mode="json")
        )

    rpc_id = request.id
    params = request.params or {}

    try:
        message_data = params.get("message", {})
        parts = message_data.get("parts", [])
        query = " ".join(
            p.get("text", "") for p in parts if "text" in p
        ).strip()

        if not query:
            raise ValueError("No text in message parts")
    except Exception as e:
        return JSONResponse(
            JSONRPCResponse(
                id=rpc_id,
                error=JSONRPCError(
                    code=A2AErrorCode.INTERNAL_ERROR,
                    message=f"Could not parse message: {e}",
                ),
            ).model_dump(mode="json")
        )

    task_id = params.get("id") or str(uuid.uuid4())
    task = await handle_orchestrate(query, task_id)

    return JSONResponse(
        JSONRPCResponse(
            id=rpc_id,
            result=task.model_dump(mode="json"),
        ).model_dump(mode="json")
    )


@app.post("/a2a/tasks/get")
async def tasks_get(
    body: dict,
    token: str = Depends(verify_token),
) -> JSONResponse:
    try:
        request = JSONRPCRequest(**body)
    except Exception:
        return JSONResponse(
            JSONRPCResponse(
                id=body.get("id"),
                error=JSONRPCError(
                    code=A2AErrorCode.INTERNAL_ERROR,
                    message="Invalid JSON-RPC request",
                ),
            ).model_dump(mode="json")
        )

    params = request.params or {}
    task_id = params.get("id", "")
    task = _task_store.get(task_id)

    if task is None:
        return JSONResponse(
            JSONRPCResponse(
                id=request.id,
                error=JSONRPCError(
                    code=A2AErrorCode.TASK_NOT_FOUND,
                    message=f"Task {task_id} not found",
                ),
            ).model_dump(mode="json")
        )

    return JSONResponse(
        JSONRPCResponse(
            id=request.id,
            result=task.model_dump(mode="json"),
        ).model_dump(mode="json")
    )


@app.post("/a2a/tasks/cancel")
async def tasks_cancel(
    body: dict,
    token: str = Depends(verify_token),
) -> JSONResponse:
    try:
        request = JSONRPCRequest(**body)
    except Exception:
        return JSONResponse(
            JSONRPCResponse(
                id=body.get("id"),
                error=JSONRPCError(
                    code=A2AErrorCode.INTERNAL_ERROR,
                    message="Invalid JSON-RPC request",
                ),
            ).model_dump(mode="json")
        )

    params = request.params or {}
    task_id = params.get("id", "")
    task = _task_store.get(task_id)

    if task is None:
        return JSONResponse(
            JSONRPCResponse(
                id=request.id,
                error=JSONRPCError(
                    code=A2AErrorCode.TASK_NOT_FOUND,
                    message=f"Task {task_id} not found",
                ),
            ).model_dump(mode="json")
        )

    task = Task(
        id=task_id,
        status=TaskStatus(state=TaskState.CANCELED),
    )
    _task_store[task_id] = task

    return JSONResponse(
        JSONRPCResponse(
            id=request.id,
            result=task.model_dump(mode="json"),
        ).model_dump(mode="json")
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "orchestrator.main:app",
        host="0.0.0.0",
        port=settings.orchestrator_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )