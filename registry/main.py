# registry/main.py
"""
Agent Registry Service — port 9000.

Service discovery for the A2A marketplace.
Agents register on startup, orchestrator queries to find agents.

Background task: polls all active agents' /health endpoints
every 60 seconds and marks unresponsive ones inactive.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI, HTTPException, Path
from fastapi.responses import JSONResponse

from registry.database import (
    create_pool,
    deregister_agent,
    get_agent,
    get_agent_counts,
    init_db,
    list_agents,
    mark_agent_inactive,
    register_agent,
    update_heartbeat,
)
from registry.models import (
    AgentListResponse,
    AgentRecord,
    AgentRegistrationRequest,
    AgentStatus,
    HeartbeatRequest,
    HealthResponse,
    RegistrationResponse,
)
from shared.config import get_settings
from shared.logging_config import setup_logging

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── Health checker background task ────────────────────────────────────────────

async def health_check_loop(app: FastAPI) -> None:
    """
    Poll all active agents every 60 seconds.

    For each active agent:
    - GET {agent.health_check_url} with 5s timeout
    - 200 response → update last_seen (agent stays active)
    - Any failure → mark inactive

    Runs as asyncio background task started in lifespan.
    Cancelled automatically when lifespan exits.
    """
    logger.info("health_checker_started", interval_seconds=60)

    while True:
        await asyncio.sleep(60)

        try:
            pool = app.state.pool
            agents = await list_agents(pool, status=AgentStatus.ACTIVE)

            if not agents:
                continue

            logger.debug("health_check_round", checking=len(agents))

            async with httpx.AsyncClient(timeout=5.0) as client:
                for agent_row in agents:
                    name = agent_row["name"]
                    health_url = agent_row["health_check_url"]

                    try:
                        response = await client.get(health_url)
                        if response.status_code == 200:
                            await update_heartbeat(pool, name, AgentStatus.ACTIVE)
                            logger.debug("agent_healthy", agent=name)
                        else:
                            await mark_agent_inactive(pool, name)
                            logger.warning(
                                "agent_unhealthy",
                                agent=name,
                                status_code=response.status_code,
                            )
                    except (httpx.ConnectError, httpx.TimeoutException):
                        await mark_agent_inactive(pool, name)
                        logger.warning("agent_unreachable", agent=name)

        except Exception:
            # Never let the health checker crash — log and continue
            logger.exception("health_check_loop_error")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    logger.info("registry_starting", port=settings.registry_port)

    # Database setup
    pool = await create_pool(settings.postgres_url)
    await init_db(pool)
    app.state.pool = pool
    logger.info("database_connected")

    # Start background health checker
    checker_task = asyncio.create_task(health_check_loop(app))
    logger.info("health_checker_started")

    yield

    # Shutdown
    checker_task.cancel()
    try:
        await checker_task
    except asyncio.CancelledError:
        pass

    await pool.close()
    logger.info("registry_stopped")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Agent Registry",
    description="Service discovery for A2A Marketplace agents",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Public health check — also verifies DB connectivity."""
    try:
        counts = await get_agent_counts(app.state.pool)
        db_status = "connected"
    except Exception:
        counts = {"total": 0, "active": 0}
        db_status = "error"

    return HealthResponse(
        status="healthy",
        service="agent-registry",
        version="1.0.0",
        registered_agents=counts["total"],
        active_agents=counts["active"],
        database=db_status,
    )


@app.post("/agents/register", response_model=RegistrationResponse)
async def register(request: AgentRegistrationRequest) -> RegistrationResponse:
    """
    Register or re-register an agent.

    Idempotent — calling again on restart updates the existing record.
    No auth required — registry is internal network only.
    In production this would be mTLS between services.
    """
    try:
        row = await register_agent(app.state.pool, request)
        agent = AgentRecord.from_db_row(row)
        logger.info(
            "agent_registered",
            name=request.name,
            url=request.url,
            version=request.version,
        )
        return RegistrationResponse(
            success=True,
            message=f"Agent '{request.name}' registered successfully",
            agent=agent,
        )
    except Exception as exc:
        logger.exception("registration_failed", name=request.name)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/agents", response_model=AgentListResponse)
async def list_all_agents(
    status: AgentStatus | None = None,
) -> AgentListResponse:
    """
    List registered agents.

    Query param: ?status=active  (active | inactive | unknown)
    Omit status to get all agents.
    Orchestrator calls this with ?status=active to find available agents.
    """
    rows = await list_agents(app.state.pool, status=status)
    agents = [AgentRecord.from_db_row(row) for row in rows]
    active_count = sum(1 for a in agents if a.status == AgentStatus.ACTIVE)

    return AgentListResponse(
        agents=agents,
        total=len(agents),
        active_count=active_count,
    )


@app.get("/agents/{name}", response_model=AgentRecord)
async def get_one_agent(
    name: str = Path(description="Agent name e.g. 'web-search-agent'"),
) -> AgentRecord:
    """Get a specific agent by name."""
    row = await get_agent(app.state.pool, name)
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{name}' not found",
        )
    return AgentRecord.from_db_row(row)


@app.put("/agents/{name}/heartbeat")
async def heartbeat(
    name: str = Path(description="Agent name"),
    request: HeartbeatRequest = None,
) -> JSONResponse:
    """
    Agent heartbeat — updates last_seen timestamp.

    Called by agents every 30s to signal they are alive.
    Registry health checker marks agents inactive if last_seen
    is stale AND health check fails.
    """
    status = request.status if request else AgentStatus.ACTIVE
    row = await update_heartbeat(app.state.pool, name, status)

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{name}' not found — register first",
        )

    logger.debug("heartbeat_received", agent=name)
    return JSONResponse(content={"success": True, "agent": name})


@app.delete("/agents/{name}")
async def deregister(
    name: str = Path(description="Agent name"),
) -> JSONResponse:
    """
    Deregister agent on shutdown.

    Called by agents in their lifespan shutdown handler.
    Soft delete — marks inactive, preserves history.
    """
    existed = await deregister_agent(app.state.pool, name)

    if not existed:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{name}' not found",
        )

    logger.info("agent_deregistered", agent=name)
    return JSONResponse(
        content={"success": True, "message": f"Agent '{name}' deregistered"}
    )