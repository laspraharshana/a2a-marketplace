# registry/database.py
"""
Database layer for Agent Registry.

Uses asyncpg directly — no SQLAlchemy ORM.
Single table: registered_agents

Connection pool lifecycle:
- Created in FastAPI lifespan startup
- Stored in app.state.pool
- Acquired per-request via context manager
- Closed in lifespan shutdown

All public functions take pool as first argument
so they are testable without FastAPI app context.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

from registry.models import AgentRegistrationRequest, AgentStatus

logger = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS registered_agents (
    id               SERIAL PRIMARY KEY,
    name             VARCHAR(255) UNIQUE NOT NULL,
    url              VARCHAR(500) NOT NULL,
    version          VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    status           VARCHAR(50) NOT NULL DEFAULT 'active',
    capabilities     TEXT[] DEFAULT '{}',
    agent_card       JSONB DEFAULT '{}',
    health_check_url VARCHAR(500) NOT NULL,
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    registered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_registered_agents_status
    ON registered_agents(status);

CREATE INDEX IF NOT EXISTS idx_registered_agents_name
    ON registered_agents(name);
"""

# ── Pool management ───────────────────────────────────────────────────────────

async def create_pool(postgres_url: str) -> asyncpg.Pool:
    """
    Create asyncpg connection pool.
    
    min_size=2: keep 2 connections warm — registry has low traffic
                but we want fast response on health checks.
    max_size=10: cap at 10 — registry does not need more.
    command_timeout=30: fail fast if DB is unresponsive.
    """
    pool = await asyncpg.create_pool(
        postgres_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    return pool


async def init_db(pool: asyncpg.Pool) -> None:
    """Create table and indexes if they do not exist."""
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)
    logger.info("Database initialized — registered_agents table ready")


# ── CRUD operations ───────────────────────────────────────────────────────────

async def register_agent(
    pool: asyncpg.Pool,
    request: AgentRegistrationRequest,
) -> dict[str, Any]:
    """
    Insert or update agent registration.
    
    Uses INSERT ... ON CONFLICT (name) DO UPDATE so re-registration
    on agent restart updates the record rather than failing.
    Returns the full row as a dict.
    """
    health_check_url = f"{request.url.rstrip('/')}/health"

    # asyncpg does not accept Python dicts for JSONB directly.
    # Must serialize to JSON string first.
    agent_card_json = json.dumps(request.agent_card)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO registered_agents
                (name, url, version, status, capabilities,
                 agent_card, health_check_url, last_seen, registered_at)
            VALUES
                ($1, $2, $3, $4, $5, $6::jsonb, $7, NOW(), NOW())
            ON CONFLICT (name) DO UPDATE SET
                url              = EXCLUDED.url,
                version          = EXCLUDED.version,
                status           = 'active',
                capabilities     = EXCLUDED.capabilities,
                agent_card       = EXCLUDED.agent_card,
                health_check_url = EXCLUDED.health_check_url,
                last_seen        = NOW()
            RETURNING *
            """,
            request.name,
            request.url,
            request.version,
            AgentStatus.ACTIVE.value,
            request.capabilities,
            agent_card_json,
            health_check_url,
        )
    return dict(row)


async def get_agent(
    pool: asyncpg.Pool,
    name: str,
) -> dict[str, Any] | None:
    """Fetch single agent by name. Returns None if not found."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM registered_agents WHERE name = $1",
            name,
        )
    return dict(row) if row else None


async def list_agents(
    pool: asyncpg.Pool,
    status: AgentStatus | None = None,
) -> list[dict[str, Any]]:
    """
    List all agents, optionally filtered by status.
    Returns list of dicts ordered by registered_at DESC.
    """
    async with pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                """
                SELECT * FROM registered_agents
                WHERE status = $1
                ORDER BY registered_at DESC
                """,
                status.value,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM registered_agents ORDER BY registered_at DESC"
            )
    return [dict(row) for row in rows]


async def update_heartbeat(
    pool: asyncpg.Pool,
    name: str,
    status: AgentStatus = AgentStatus.ACTIVE,
) -> dict[str, Any] | None:
    """
    Update last_seen and status for heartbeat.
    Returns updated row or None if agent not found.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE registered_agents
            SET last_seen = NOW(), status = $2
            WHERE name = $1
            RETURNING *
            """,
            name,
            status.value,
        )
    return dict(row) if row else None


async def deregister_agent(
    pool: asyncpg.Pool,
    name: str,
) -> bool:
    """
    Mark agent as inactive (soft delete).
    Returns True if agent existed, False if not found.
    
    We do not hard-delete — keeps history for debugging.
    Orchestrator filters by status=active anyway.
    """
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE registered_agents
            SET status = 'inactive', last_seen = NOW()
            WHERE name = $1
            """,
            name,
        )
    # result is "UPDATE N" — check N > 0
    return result.split()[-1] != "0"


async def mark_agent_inactive(
    pool: asyncpg.Pool,
    name: str,
) -> None:
    """Called by health checker when agent fails health check."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE registered_agents
            SET status = 'inactive'
            WHERE name = $1
            """,
            name,
        )


async def get_agent_counts(
    pool: asyncpg.Pool,
) -> dict[str, int]:
    """Return total and active agent counts for health endpoint."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'active') as active
            FROM registered_agents
            """
        )
    return {"total": row["total"], "active": row["active"]}