# registry/models.py
"""
Registry data models.

Two layers:
1. Pydantic models — API request/response validation
2. DB row helpers  — convert asyncpg Records to typed dicts

No SQLAlchemy ORM — raw asyncpg for simplicity and speed.
The single table schema is defined as a SQL string in database.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
import json


# ── Enums ─────────────────────────────────────────────────────────────────────

class AgentStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


# ── Request models (what agents send to registry) ─────────────────────────────

class AgentRegistrationRequest(BaseModel):
    """
    Sent by agent on startup to POST /agents/register.
    
    name must be unique — re-registration updates existing record.
    url is the base URL the orchestrator will send A2A tasks to.
    agent_card is the full /.well-known/agent.json payload stored
    as JSONB so orchestrator can retrieve capabilities without
    calling each agent individually.
    """
    name: str = Field(
        description="Unique agent identifier e.g. 'web-search-agent'",
    )
    url: str = Field(
        description="Base URL e.g. 'http://localhost:8001'",
    )
    version: str = Field(default="1.0.0")
    capabilities: list[str] = Field(
        default_factory=list,
        description="Skill tags e.g. ['web-search', 'news']",
    )
    agent_card: dict[str, Any] = Field(
        default_factory=dict,
        description="Full AgentCard payload for capability discovery",
    )


class HeartbeatRequest(BaseModel):
    """Sent by agent every 30s to PUT /agents/{name}/heartbeat."""
    status: AgentStatus = AgentStatus.ACTIVE


# ── Response models (what registry returns) ───────────────────────────────────

class AgentRecord(BaseModel):
    """
    Single agent entry returned by GET /agents and GET /agents/{name}.
    
    last_seen: updated on every heartbeat and health check pass.
    health_check_url: derived from url + /health on registration.
    """
    id: int
    name: str
    url: str
    version: str
    status: AgentStatus
    capabilities: list[str]
    agent_card: dict[str, Any]
    last_seen: datetime
    health_check_url: str
    registered_at: datetime

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> AgentRecord:
        """Convert asyncpg Record (or dict) to AgentRecord."""
        # asyncpg returns JSONB as string — must parse it
        agent_card = row["agent_card"] or "{}"
        if isinstance(agent_card, str):
            agent_card = json.loads(agent_card)

        return cls(
            id=row["id"],
            name=row["name"],
            url=row["url"],
            version=row["version"],
            status=AgentStatus(row["status"]),
            capabilities=row["capabilities"] or [],
            agent_card=agent_card,
            last_seen=row["last_seen"],
            health_check_url=row["health_check_url"],
            registered_at=row["registered_at"],
        )


class RegistrationResponse(BaseModel):
    """Returned by POST /agents/register."""
    success: bool
    message: str
    agent: AgentRecord


class AgentListResponse(BaseModel):
    """Returned by GET /agents."""
    agents: list[AgentRecord]
    total: int
    active_count: int


class HealthResponse(BaseModel):
    """Returned by GET /health."""
    status: str
    service: str
    version: str
    registered_agents: int
    active_agents: int
    database: str