# agents/web_search/main.py
"""
Web Search Agent — FastAPI A2A Service.

Serves:
1. /.well-known/agent.json  → A2A Agent Card (public)
2. /health                  → Health check
3. /a2a/tasks/send          → Receive and execute tasks
4. /a2a/tasks/get           → Retrieve task status
5. /a2a/tasks/cancel        → Cancel a running task
"""

from __future__ import annotations
import asyncio
import os
import httpx
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from google import genai
from google.genai import types as genai_types
import structlog

from shared.a2a_types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    AgentProvider,
    AgentAuthentication,
    Task,
    TaskStatus,
    TaskState,
    TaskSendParams,
    Message,
    Artifact,
    TextPart,
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCError,
    A2AErrorCode,
)
from shared.config import settings
from shared.logging_config import setup_logging
from agents.web_search.mcp_server import (
    get_gemini_tool_declarations,
    execute_mcp_tool,
)

# ── Setup ─────────────────────────────────────────────────────
setup_logging()
logger = structlog.get_logger(__name__)

# In-memory task store (Week 6: replace with Redis + PostgreSQL)
_task_store: dict[str, Task] = {}

# ── Security ──────────────────────────────────────────────────
security = HTTPBearer(auto_error=False)


def verify_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security)
) -> str:
    from shared.config import get_settings
    current_settings = get_settings()
    expected_token = current_settings.a2a_bearer_token

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication scheme. Use Bearer",
            headers={"WWW-Authenticate": "Bearer"}
        )
    if credentials.credentials != expected_token:
        raise HTTPException(
            status_code=401,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return credentials.credentials


# ── Agent Card ────────────────────────────────────────────────
# Read AGENT_SELF_URL at module load time.
# Set by Docker Compose / Cloud Run to the service's reachable URL.
# Falls back to localhost for local dev without Docker.
_self_url = (
    os.environ.get("AGENT_SELF_URL")
    or f"http://localhost:{settings.web_search_agent_port}"
)

AGENT_CARD = AgentCard(
    name="web-search-agent",
    description=(
        "Specialized agent for web research. "
        "Searches the web, fetches news, and reads URLs. "
        "Uses Gemini with MCP tools to synthesize results."
    ),
    url=_self_url,
    version="1.0.0",
    provider=AgentProvider(
        organization="A2A Marketplace",
        url="https://github.com/yourusername/a2a-marketplace"
    ),
    capabilities=AgentCapabilities(
        streaming=False,
        pushNotifications=False,
        stateTransitionHistory=True
    ),
    skills=[
        AgentSkill(
            id="web_search",
            name="Web Search",
            description=(
                "Search and summarize web content on any topic."
            ),
            tags=["search", "web", "research", "information"],
            examples=[
                "Search for quantum computing companies in Singapore",
                "Find information about recent AI developments",
            ],
            inputModes=["text"],
            outputModes=["text", "data"]
        ),
        AgentSkill(
            id="news_fetch",
            name="News Fetching",
            description="Fetch recent news articles on any topic",
            tags=["news", "current events", "recent"],
            examples=[
                "Get news about Singapore tech startups",
                "Find recent AI research news",
            ],
            inputModes=["text"],
            outputModes=["text"]
        ),
        AgentSkill(
            id="url_reader",
            name="URL Content Reader",
            description="Read and extract content from any URL",
            tags=["url", "webpage", "content"],
            examples=[
                "Read the content of https://example.com/article",
            ],
            inputModes=["text"],
            outputModes=["text"]
        ),
    ],
    authentication=AgentAuthentication(schemes=["bearer"]),
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
)


# ══════════════════════════════════════════════════════════════
# GEMINI AGENT WITH TOOL CALLING LOOP
# ══════════════════════════════════════════════════════════════

async def run_agent_with_tools(task_message: str) -> str:
    client = genai.Client(api_key=settings.google_api_key)

    gemini_tools = genai_types.Tool(
        function_declarations=get_gemini_tool_declarations()
    )

    system_instruction = (
        "You are a specialized web research agent. "
        "Your job is to find accurate, current information. "
        "Always use the available tools to search for information. "
        "Always cite your sources with URLs. "
        "Be concise but comprehensive in your responses. "
        "If search results are limited, use what you have "
        "and supplement with your knowledge, clearly noting "
        "which information came from search vs your training."
    )

    messages: list[genai_types.Content] = [
        genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=task_message)]
        )
    ]

    max_iterations = 5
    iteration = 0
    response = None
    all_tool_results: list[str] = []

    while iteration < max_iterations:
        iteration += 1

        logger.debug(
            "gemini_api_call",
            model=settings.agent_model,
            iteration=iteration
        )

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.agent_model,
            contents=messages,
            config=genai_types.GenerateContentConfig(
                tools=[gemini_tools],
                system_instruction=system_instruction,
                temperature=0.1,
            )
        )

        if not response.candidates:
            logger.warning("gemini_no_candidates", iteration=iteration)
            break

        candidate = response.candidates[0]
        response_content = candidate.content
        messages.append(response_content)

        function_calls = [
            part.function_call
            for part in response_content.parts
            if hasattr(part, 'function_call')
            and part.function_call is not None
        ]

        if not function_calls:
            logger.info("gemini_finished", iterations=iteration)
            break

        function_response_parts = []
        for fc in function_calls:
            tool_name = fc.name
            tool_args = dict(fc.args)

            logger.info("gemini_tool_call", tool=tool_name, iteration=iteration)

            result_text = await execute_mcp_tool(tool_name, tool_args)

            if not result_text.startswith("Error") and \
               "No search results" not in result_text:
                all_tool_results.append(result_text)

            function_response_parts.append(
                genai_types.Part(
                    function_response=genai_types.FunctionResponse(
                        name=tool_name,
                        response={"result": result_text}
                    )
                )
            )

        messages.append(
            genai_types.Content(
                role="user",
                parts=function_response_parts
            )
        )

    final_text = ""
    if response and response.candidates:
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text:
                final_text += part.text

    if not final_text and all_tool_results:
        logger.info(
            "using_fallback_synthesis",
            collected_results=len(all_tool_results)
        )
        combined_data = "\n\n---\n\n".join(all_tool_results)
        synthesis_prompt = (
            f"Based on the following search results, "
            f"answer this question: {task_message}\n\n"
            f"Search Results:\n{combined_data}\n\n"
            f"Provide a clear, concise answer with sources."
        )
        synthesis_response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.agent_model,
            contents=synthesis_prompt,
            config=genai_types.GenerateContentConfig(temperature=0.1)
        )
        if synthesis_response.candidates:
            for part in synthesis_response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    final_text += part.text

    if not final_text:
        final_text = (
            f"I searched for '{task_message}' but was unable "
            f"to retrieve results at this time due to search "
            f"rate limits. Please try again in a few seconds."
        )

    logger.info(
        "agent_task_complete",
        model=settings.agent_model,
        iterations=iteration,
        tool_results_collected=len(all_tool_results),
        response_length=len(final_text)
    )
    return final_text


# ── Registry integration ──────────────────────────────────────

async def _register_with_registry() -> None:
    capabilities: list[str] = []
    for skill in AGENT_CARD.skills:
        capabilities.extend(skill.tags)

    payload = {
        "name": AGENT_CARD.name,
        "url": AGENT_CARD.url,           # correct — AGENT_CARD.url = _self_url
        "version": AGENT_CARD.version,
        "capabilities": list(set(capabilities)),
        "agent_card": AGENT_CARD.model_dump(mode="json"),  # correct — url already set
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{settings.registry_url}/agents/register",
                json=payload,
            )
            if resp.status_code == 200:
                logger.info(
                    "registered_with_registry",
                    registry=settings.registry_url,
                    url=AGENT_CARD.url,
                )
            else:
                logger.warning(
                    "registry_registration_failed",
                    status=resp.status_code,
                )
    except Exception as e:
        logger.warning("registry_unavailable", error=str(e))


async def _deregister_from_registry() -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.delete(
                f"{settings.registry_url}/agents/{AGENT_CARD.name}"
            )
            logger.info("deregistered_from_registry")
    except Exception as e:
        logger.warning("deregister_failed", error=str(e))


async def _heartbeat_loop() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.put(
                    f"{settings.registry_url}/agents"
                    f"/{AGENT_CARD.name}/heartbeat",
                    json={"status": "active"},
                )
                logger.debug("heartbeat_sent")
        except Exception:
            logger.debug("heartbeat_failed")


# ══════════════════════════════════════════════════════════════
# FASTAPI APPLICATION
# ══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "web_search_agent_starting",
        url=AGENT_CARD.url,
        environment=settings.environment,
    )
    await _register_with_registry()
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    try:
        yield
    finally:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        await _deregister_from_registry()
        logger.info("web_search_agent_stopping")


app = FastAPI(
    title="Web Search Agent",
    description="A2A-compatible web search specialist agent",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/.well-known/agent.json", include_in_schema=False)
async def get_agent_card() -> dict:
    return AGENT_CARD.model_dump(exclude_none=True)


@app.get("/health")
async def health_check() -> dict:
    return {
        "status": "healthy",
        "agent": "web-search-agent",
        "version": "1.0.0"
    }


@app.post("/a2a/tasks/send")
async def send_task(
    request: JSONRPCRequest,
    _token: str = Depends(verify_bearer_token)
) -> JSONRPCResponse:
    try:
        params = TaskSendParams(**request.params)

        task_text = ""
        for part in params.message.parts:
            if isinstance(part, dict) and part.get("type") == "text":
                task_text += part.get("text", "")
            elif hasattr(part, 'text'):
                task_text += part.text

        logger.info("task_received", task_id=params.id, preview=task_text[:100])

        task = Task(
            id=params.id,
            sessionId=params.sessionId,
            status=TaskStatus(
                state=TaskState.WORKING,
                message=Message(
                    role="agent",
                    parts=[TextPart(type="text", text="Searching the web...")]
                )
            ),
            history=[params.message]
        )
        _task_store[task.id] = task

        result_text = await run_agent_with_tools(task_text)

        task.status = TaskStatus(state=TaskState.COMPLETED)
        task.artifacts = [
            Artifact(
                name="search_results",
                description="Web search results and synthesis",
                parts=[TextPart(type="text", text=result_text)]
            )
        ]
        _task_store[task.id] = task

        logger.info("task_completed", task_id=task.id)

        return JSONRPCResponse(
            id=request.id,
            result=task.model_dump(exclude_none=True)
        )

    except Exception as e:
        logger.error("task_failed", error=str(e), exc_info=True)
        return JSONRPCResponse(
            id=request.id,
            error=JSONRPCError(
                code=A2AErrorCode.INTERNAL_ERROR,
                message=str(e)
            )
        )


@app.post("/a2a/tasks/get")
async def get_task(
    request: JSONRPCRequest,
    _token: str = Depends(verify_bearer_token)
) -> JSONRPCResponse:
    task_id = request.params.get("id")
    task = _task_store.get(task_id)
    if not task:
        return JSONRPCResponse(
            id=request.id,
            error=JSONRPCError(
                code=A2AErrorCode.TASK_NOT_FOUND,
                message=f"Task {task_id} not found"
            )
        )
    return JSONRPCResponse(
        id=request.id,
        result=task.model_dump(exclude_none=True)
    )


@app.post("/a2a/tasks/cancel")
async def cancel_task(
    request: JSONRPCRequest,
    _token: str = Depends(verify_bearer_token)
) -> JSONRPCResponse:
    task_id = request.params.get("id")
    task = _task_store.get(task_id)
    if not task:
        return JSONRPCResponse(
            id=request.id,
            error=JSONRPCError(
                code=A2AErrorCode.TASK_NOT_FOUND,
                message=f"Task {task_id} not found"
            )
        )
    task.status = TaskStatus(state=TaskState.CANCELED)
    _task_store[task_id] = task
    return JSONRPCResponse(
        id=request.id,
        result=task.model_dump(exclude_none=True)
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "agents.web_search.main:app",
        host="0.0.0.0",
        port=settings.web_search_agent_port,
        reload=settings.environment == "development",
        log_level=settings.log_level.lower()
    )