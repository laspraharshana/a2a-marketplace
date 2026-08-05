# tests/test_registry.py
"""
Agent Registry test suite.

Structure:
  TestRegistryModels      (6 tests)  — Pydantic model validation, no DB
  TestDatabaseLayer       (9 tests)  — real PostgreSQL, isolated test DB
  TestRegistryEndpoints   (12 tests) — mock DB, test HTTP behavior
  TestIntegration         (4 tests)  — full stack, marked integration

Run all:         pytest tests/test_registry.py -v
Run unit only:   pytest tests/test_registry.py -v -m "not integration"
Run integration: pytest tests/test_registry.py -v -m integration
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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

settings = get_settings()

# ── Shared test data ──────────────────────────────────────────────────────────

SAMPLE_AGENT_ROW: dict[str, Any] = {
    "id": 1,
    "name": "web-search-agent",
    "url": "http://localhost:8001",
    "version": "1.0.0",
    "status": "active",
    "capabilities": ["web-search", "news", "fetch-url"],
    "agent_card": {
        "name": "Web Search Agent",
        "description": "Searches the web",
        "url": "http://localhost:8001",
        "version": "1.0.0",
    },
    "health_check_url": "http://localhost:8001/health",
    "last_seen": datetime.now(timezone.utc),
    "registered_at": datetime.now(timezone.utc),
}

SAMPLE_REGISTRATION_REQUEST = AgentRegistrationRequest(
    name="web-search-agent",
    url="http://localhost:8001",
    version="1.0.0",
    capabilities=["web-search", "news", "fetch-url"],
    agent_card={
        "name": "Web Search Agent",
        "description": "Searches the web",
    },
)


# ─────────────────────────────────────────────
# TestRegistryModels
# ─────────────────────────────────────────────

class TestRegistryModels:
    """Pydantic model validation — no database needed."""

    def test_agent_registration_request_valid(self):
        req = AgentRegistrationRequest(
            name="test-agent",
            url="http://localhost:8001",
            version="1.0.0",
            capabilities=["search"],
            agent_card={"name": "Test"},
        )
        assert req.name == "test-agent"
        assert req.url == "http://localhost:8001"
        assert "search" in req.capabilities

    def test_agent_registration_request_defaults(self):
        """version, capabilities, agent_card all have defaults."""
        req = AgentRegistrationRequest(
            name="minimal-agent",
            url="http://localhost:9999",
        )
        assert req.version == "1.0.0"
        assert req.capabilities == []
        assert req.agent_card == {}

    def test_agent_record_from_db_row(self):
        record = AgentRecord.from_db_row(SAMPLE_AGENT_ROW)
        assert record.id == 1
        assert record.name == "web-search-agent"
        assert record.status == AgentStatus.ACTIVE
        assert record.health_check_url == "http://localhost:8001/health"
        assert isinstance(record.last_seen, datetime)

    def test_agent_status_enum_values(self):
        assert AgentStatus.ACTIVE == "active"
        assert AgentStatus.INACTIVE == "inactive"
        assert AgentStatus.UNKNOWN == "unknown"

    def test_heartbeat_request_default_status(self):
        req = HeartbeatRequest()
        assert req.status == AgentStatus.ACTIVE

    def test_agent_list_response_counts(self):
        records = [
            AgentRecord.from_db_row(SAMPLE_AGENT_ROW),
            AgentRecord.from_db_row({
                **SAMPLE_AGENT_ROW,
                "id": 2,
                "name": "data-analysis-agent",
                "status": "inactive",
            }),
        ]
        response = AgentListResponse(
            agents=records,
            total=2,
            active_count=1,
        )
        assert response.total == 2
        assert response.active_count == 1


# ─────────────────────────────────────────────
# TestDatabaseLayer
# ─────────────────────────────────────────────

# Reusable sample row builder
def make_db_row(**overrides) -> dict[str, Any]:
    base = dict(SAMPLE_AGENT_ROW)
    base.update(overrides)
    return base


class TestDatabaseLayer:
    """
    Test database CRUD functions against real PostgreSQL.

    Uses a dedicated test table prefix to avoid polluting
    the real registered_agents table.

    Strategy: create real pool, run real SQL, clean up after each test.
    """

    @pytest_asyncio.fixture(autouse=True)
    async def db_pool(self):
        """Real asyncpg pool for each test. Cleans up test rows after."""
        import asyncpg
        from registry.database import create_pool, init_db

        pool = await create_pool(settings.postgres_url)
        await init_db(pool)  # Ensures table exists

        yield pool

        # Clean up all test rows after each test
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM registered_agents WHERE name LIKE 'test-%'"
            )
        await pool.close()

    @pytest.mark.asyncio
    async def test_register_new_agent(self, db_pool):
        from registry.database import register_agent

        request = AgentRegistrationRequest(
            name="test-web-search",
            url="http://localhost:8001",
            version="1.0.0",
            capabilities=["search"],
            agent_card={"name": "Test Web Search"},
        )
        row = await register_agent(db_pool, request)

        assert row["name"] == "test-web-search"
        assert row["url"] == "http://localhost:8001"
        assert row["status"] == "active"
        assert row["health_check_url"] == "http://localhost:8001/health"

    @pytest.mark.asyncio
    async def test_register_idempotent(self, db_pool):
        """Re-registering same name updates existing row."""
        from registry.database import register_agent

        request = AgentRegistrationRequest(
            name="test-idempotent",
            url="http://localhost:8001",
            version="1.0.0",
        )
        row1 = await register_agent(db_pool, request)

        # Re-register with new version
        request2 = AgentRegistrationRequest(
            name="test-idempotent",
            url="http://localhost:8001",
            version="2.0.0",
        )
        row2 = await register_agent(db_pool, request2)

        # Same id, updated version
        assert row1["id"] == row2["id"]
        assert row2["version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_get_agent_exists(self, db_pool):
        from registry.database import get_agent, register_agent

        await register_agent(db_pool, AgentRegistrationRequest(
            name="test-get-agent",
            url="http://localhost:8002",
        ))

        row = await get_agent(db_pool, "test-get-agent")
        assert row is not None
        assert row["name"] == "test-get-agent"

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, db_pool):
        from registry.database import get_agent

        row = await get_agent(db_pool, "test-nonexistent-agent")
        assert row is None

    @pytest.mark.asyncio
    async def test_list_agents_all(self, db_pool):
        from registry.database import list_agents, register_agent

        await register_agent(db_pool, AgentRegistrationRequest(
            name="test-list-agent-1", url="http://localhost:8001",
        ))
        await register_agent(db_pool, AgentRegistrationRequest(
            name="test-list-agent-2", url="http://localhost:8002",
        ))

        rows = await list_agents(db_pool)
        names = [r["name"] for r in rows]
        assert "test-list-agent-1" in names
        assert "test-list-agent-2" in names

    @pytest.mark.asyncio
    async def test_list_agents_filter_active(self, db_pool):
        from registry.database import (
            deregister_agent,
            list_agents,
            register_agent,
        )

        await register_agent(db_pool, AgentRegistrationRequest(
            name="test-active-agent", url="http://localhost:8001",
        ))
        await register_agent(db_pool, AgentRegistrationRequest(
            name="test-inactive-agent", url="http://localhost:8002",
        ))
        await deregister_agent(db_pool, "test-inactive-agent")

        active_rows = await list_agents(db_pool, status=AgentStatus.ACTIVE)
        active_names = [r["name"] for r in active_rows]
        assert "test-active-agent" in active_names
        assert "test-inactive-agent" not in active_names

    @pytest.mark.asyncio
    async def test_update_heartbeat(self, db_pool):
        from registry.database import (
            get_agent,
            register_agent,
            update_heartbeat,
        )

        await register_agent(db_pool, AgentRegistrationRequest(
            name="test-heartbeat-agent", url="http://localhost:8001",
        ))

        before = await get_agent(db_pool, "test-heartbeat-agent")
        await asyncio.sleep(0.05)  # Small delay so last_seen changes
        await update_heartbeat(db_pool, "test-heartbeat-agent")
        after = await get_agent(db_pool, "test-heartbeat-agent")

        assert after["last_seen"] >= before["last_seen"]
        assert after["status"] == "active"

    @pytest.mark.asyncio
    async def test_deregister_agent(self, db_pool):
        from registry.database import deregister_agent, get_agent, register_agent

        await register_agent(db_pool, AgentRegistrationRequest(
            name="test-deregister-agent", url="http://localhost:8001",
        ))

        existed = await deregister_agent(db_pool, "test-deregister-agent")
        assert existed is True

        row = await get_agent(db_pool, "test-deregister-agent")
        assert row["status"] == "inactive"  # Soft delete — row still exists

    @pytest.mark.asyncio
    async def test_deregister_nonexistent(self, db_pool):
        from registry.database import deregister_agent

        existed = await deregister_agent(db_pool, "test-never-existed")
        assert existed is False

    @pytest.mark.asyncio
    async def test_get_agent_counts(self, db_pool):
        from registry.database import (
            deregister_agent,
            get_agent_counts,
            register_agent,
        )

        await register_agent(db_pool, AgentRegistrationRequest(
            name="test-count-active", url="http://localhost:8001",
        ))
        await register_agent(db_pool, AgentRegistrationRequest(
            name="test-count-inactive", url="http://localhost:8002",
        ))
        await deregister_agent(db_pool, "test-count-inactive")

        counts = await get_agent_counts(db_pool)
        # At least our test agents exist
        assert counts["total"] >= 2
        assert counts["active"] >= 1
        assert counts["active"] < counts["total"]


# ─────────────────────────────────────────────
# TestRegistryEndpoints
# ─────────────────────────────────────────────

# Mock pool fixture for endpoint tests — no real DB needed
def make_mock_pool() -> MagicMock:
    pool = MagicMock()
    return pool


class TestRegistryEndpoints:
    """
    Test HTTP endpoints with mocked database layer.
    Pool injected directly into app.state — no lifespan override.

    Patches registry.main.* database functions directly
    so FastAPI app runs without a real PostgreSQL connection.
    """

    @pytest_asyncio.fixture
    async def client(self):
        """
        HTTP client with pool injected directly into app.state.
        No lifespan override needed — we set state manually and
        mock all DB functions so the pool is never actually used.
        """
        from registry.main import app

        # Inject a mock pool directly — bypasses lifespan entirely
        app.state.pool = MagicMock()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac

        # Clean up state after test
        del app.state.pool

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        with patch(
            "registry.main.get_agent_counts",
            new_callable=AsyncMock,
            return_value={"total": 3, "active": 2},
        ) as mock_counts:
            response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "agent-registry"
        assert data["database"] == "connected"
        mock_counts.assert_called_once()  # Verify mock was actually used
        assert data["registered_agents"] == 3
        assert data["active_agents"] == 2

    @pytest.mark.asyncio
    async def test_health_db_error(self, client):
        """Health endpoint handles DB error gracefully."""
        with patch(
            "registry.main.get_agent_counts",
            new_callable=AsyncMock,
            side_effect=Exception("DB connection failed"),
        ):
            response = await client.get("/health")

        assert response.status_code == 200  # Still healthy at HTTP level
        data = response.json()
        assert data["database"] == "error"

    @pytest.mark.asyncio
    async def test_register_agent_success(self, client):
        with patch(
            "registry.main.register_agent",
            new_callable=AsyncMock,
            return_value=SAMPLE_AGENT_ROW,
        ):
            response = await client.post(
                "/agents/register",
                json={
                    "name": "web-search-agent",
                    "url": "http://localhost:8001",
                    "version": "1.0.0",
                    "capabilities": ["web-search"],
                    "agent_card": {},
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "web-search-agent" in data["message"]
        assert data["agent"]["name"] == "web-search-agent"

    @pytest.mark.asyncio
    async def test_register_agent_db_error(self, client):
        with patch(
            "registry.main.register_agent",
            new_callable=AsyncMock,
            side_effect=Exception("Unique constraint violation"),
        ):
            response = await client.post(
                "/agents/register",
                json={
                    "name": "bad-agent",
                    "url": "http://localhost:9999",
                },
            )

        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_list_agents_all(self, client):
        second_row = {**SAMPLE_AGENT_ROW, "id": 2, "name": "data-analysis-agent"}
        with patch(
            "registry.main.list_agents",
            new_callable=AsyncMock,
            return_value=[SAMPLE_AGENT_ROW, second_row],
        ):
            response = await client.get("/agents")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["agents"]) == 2

    @pytest.mark.asyncio
    async def test_list_agents_filter_by_status(self, client):
        with patch(
            "registry.main.list_agents",
            new_callable=AsyncMock,
            return_value=[SAMPLE_AGENT_ROW],
        ) as mock_list:
            response = await client.get("/agents?status=active")

        assert response.status_code == 200
        # Verify status filter was passed to DB function
        mock_list.assert_called_once()
        call_kwargs = mock_list.call_args
        assert AgentStatus.ACTIVE in call_kwargs.args or \
               call_kwargs.kwargs.get("status") == AgentStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, client):
        with patch(
            "registry.main.list_agents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await client.get("/agents")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["active_count"] == 0
        assert data["agents"] == []

    @pytest.mark.asyncio
    async def test_get_agent_found(self, client):
        with patch(
            "registry.main.get_agent",
            new_callable=AsyncMock,
            return_value=SAMPLE_AGENT_ROW,
        ):
            response = await client.get("/agents/web-search-agent")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "web-search-agent"
        assert data["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, client):
        with patch(
            "registry.main.get_agent",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get("/agents/nonexistent-agent")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_heartbeat_success(self, client):
        with patch(
            "registry.main.update_heartbeat",
            new_callable=AsyncMock,
            return_value=SAMPLE_AGENT_ROW,
        ):
            response = await client.put(
                "/agents/web-search-agent/heartbeat",
                json={"status": "active"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["agent"] == "web-search-agent"

    @pytest.mark.asyncio
    async def test_heartbeat_agent_not_found(self, client):
        with patch(
            "registry.main.update_heartbeat",
            new_callable=AsyncMock,
            return_value=None,  # Agent not in DB
        ):
            response = await client.put(
                "/agents/ghost-agent/heartbeat",
                json={"status": "active"},
            )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_deregister_success(self, client):
        with patch(
            "registry.main.deregister_agent",
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await client.delete("/agents/web-search-agent")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_deregister_not_found(self, client):
        with patch(
            "registry.main.deregister_agent",
            new_callable=AsyncMock,
            return_value=False,
        ):
            response = await client.delete("/agents/ghost-agent")

        assert response.status_code == 404


# ─────────────────────────────────────────────
# TestIntegration
# ─────────────────────────────────────────────

@pytest.mark.integration
class TestIntegration:
    """
    Full stack integration tests against real PostgreSQL.

    These tests:
    - Start the actual FastAPI app (no mocks)
    - Hit real endpoints
    - Write to real database
    - Clean up after themselves

    Run with: pytest tests/test_registry.py -m integration -v
    Skipped automatically if PostgreSQL is unreachable.
    """

    @pytest_asyncio.fixture
    async def live_client(self):
        """
        Real FastAPI app with real PostgreSQL pool injected directly.
        No lifespan override — pool set on app.state directly.
        Table initialized once, test rows cleaned up after yield.
        """
        from registry.database import create_pool, init_db
        from registry.main import app

        # Create real pool and init table
        pool = await create_pool(settings.postgres_url)
        await init_db(pool)

        # Inject directly — same pattern as TestRegistryEndpoints
        app.state.pool = pool

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac

        # Clean up test rows
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM registered_agents WHERE name LIKE 'integration-%'"
            )

        await pool.close()

        # Clean up state
        if hasattr(app.state, "pool"):
            del app.state.pool

    @pytest.mark.asyncio
    async def test_full_registration_flow(self, live_client):
        """Register → get → heartbeat → deregister."""
        # Register
        reg_response = await live_client.post(
            "/agents/register",
            json={
                "name": "integration-test-agent",
                "url": "http://localhost:8099",
                "version": "1.0.0",
                "capabilities": ["test"],
                "agent_card": {"name": "Integration Test Agent"},
            },
        )
        assert reg_response.status_code == 200
        assert reg_response.json()["success"] is True

        # Get
        get_response = await live_client.get("/agents/integration-test-agent")
        assert get_response.status_code == 200
        assert get_response.json()["status"] == "active"

        # Heartbeat
        hb_response = await live_client.put(
            "/agents/integration-test-agent/heartbeat",
            json={"status": "active"},
        )
        assert hb_response.status_code == 200

        # Deregister
        del_response = await live_client.delete("/agents/integration-test-agent")
        assert del_response.status_code == 200

        # Verify soft delete — still exists but inactive
        final_response = await live_client.get("/agents/integration-test-agent")
        assert final_response.status_code == 200
        assert final_response.json()["status"] == "inactive"

    @pytest.mark.asyncio
    async def test_list_only_active(self, live_client):
        """Verify status filter works end-to-end."""
        # Register two agents
        for name in ["integration-active-1", "integration-active-2"]:
            await live_client.post(
                "/agents/register",
                json={"name": name, "url": f"http://localhost:8099"},
            )

        # Deregister one
        await live_client.delete("/agents/integration-active-2")

        # List active only
        response = await live_client.get("/agents?status=active")
        assert response.status_code == 200
        names = [a["name"] for a in response.json()["agents"]]
        assert "integration-active-1" in names
        assert "integration-active-2" not in names

    @pytest.mark.asyncio
    async def test_re_registration_reactivates(self, live_client):
        """Agent that was inactive becomes active on re-registration."""
        # Register then deregister
        await live_client.post(
            "/agents/register",
            json={"name": "integration-reactivate", "url": "http://localhost:8099"},
        )
        await live_client.delete("/agents/integration-reactivate")

        # Verify inactive
        resp = await live_client.get("/agents/integration-reactivate")
        assert resp.json()["status"] == "inactive"

        # Re-register — should become active again
        await live_client.post(
            "/agents/register",
            json={"name": "integration-reactivate", "url": "http://localhost:8099"},
        )
        resp = await live_client.get("/agents/integration-reactivate")
        assert resp.json()["status"] == "active"

    @pytest.mark.asyncio
    async def test_health_shows_correct_counts(self, live_client):
        """Health endpoint reflects real DB state."""
        # Register a fresh agent
        await live_client.post(
            "/agents/register",
            json={"name": "integration-health-check", "url": "http://localhost:8099"},
        )

        response = await live_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["database"] == "connected"
        assert data["registered_agents"] >= 1
        assert data["active_agents"] >= 1