# CLAUDE_CONTEXT.md
#
# PURPOSE: Paste this entire file at the START of
# every new Claude conversation about this project.
# This replaces Claude's memory across sessions.
#
# KEEP THIS UPDATED after every work session.
# ══════════════════════════════════════════════════

## PROJECT IDENTITY
- Name: A2A Multi-Agent Marketplace System
- Repo: https://github.com/YOURUSERNAME/a2a-marketplace
- Goal: Portfolio project demonstrating A2A + MCP protocols
- Target: Flat Rock job application / ML Engineer interviews
- Deadline: August 15, 2025

## MY PROFILE (for Claude to calibrate explanations)
- Level: Advanced Python (async, decorators, class design)
- Built before: FastAPI, Docker, async Python, LLM projects
- Environment: Ubuntu 24.04.3 LTS (WSL2), Python 3.12.3
- Docker: Native WSL2, version 29.1.3 (NO Docker Desktop)
- A2A knowledge: Completed DeepLearning.AI A2A course
- Budget: Free tier only (Gemini API)
- Explanation style: Skip basics, explain protocol-specific
  details deeply, production-quality code always

## TECH STACK DECISIONS (already made, don't re-suggest)
- LLM: Google Gemini (free tier) — NOT OpenAI, NOT Anthropic
- Gemini SDK: google-genai 2.16.0 (NOT google-generativeai)
  Import: from google import genai
          from google.genai import types as genai_types
- MCP SDK: mcp 2.0.0
  Import: from mcp.server.mcpserver import MCPServer
  NOTE: No mcp.server.fastmcp module exists in 2.0.
        MCPServer IS the replacement for FastMCP.
- Agent Framework: LangGraph (orchestrator only, not agents)
- Web Framework: FastAPI (each agent is a microservice)
- Database: PostgreSQL + asyncpg + SQLAlchemy 2.0
- Cache: Redis
- Observability: OpenTelemetry
- Logging: structlog
- Validation: Pydantic v2
  Settings: SettingsConfigDict NOT class Config
  Fields: NO Field(env="VAR") — that is Pydantic v1 syntax
- Search: ddgs (NOT duckduckgo-search — package was renamed)
  Import: from ddgs import DDGS
- Container: Docker native WSL2 (NO Docker Desktop)

## GEMINI MODELS (LOCKED — DO NOT SUGGEST ALTERNATIVES)
- AGENT_MODEL=gemini-flash-lite-latest
- ORCHESTRATOR_MODEL=gemini-flash-latest
- Set in .env, read via settings.agent_model
  and settings.orchestrator_model
- DO NOT use: gemini-1.5-flash, gemini-2.5-flash,
  gemini-2.0-flash — these cause errors on this account

## CRITICAL SDK NOTES (learned from bugs, do not repeat)

### google-genai 2.x correct usage:
```python
from google import genai
from google.genai import types as genai_types

client = genai.Client(api_key=settings.google_api_key)
# SDK is synchronous — always run in thread pool:
response = await asyncio.to_thread(
    client.models.generate_content,
    model=settings.agent_model,
    contents=messages,
    config=genai_types.GenerateContentConfig(
        tools=[gemini_tools],
        system_instruction="...",
        temperature=0.1,
    )
)
```

### MCP 2.0 MCPServer correct usage:
```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    name="agent-name",
    title="Agent Title",
    description="...",
    instructions="...",
    version="1.0.0",
)

@mcp.tool()
async def tool_name(param: str, optional: int = 5) -> str:
    """Docstring becomes the tool description for LLM."""
    result = await actual_logic(param)
    return formatted_string_result

@mcp.resource("resource://agent-name/info")
async def get_info() -> str:
    return json.dumps({...})
```

### Pydantic v2 Settings correct usage:
```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    # Field name auto-maps: google_api_key → GOOGLE_API_KEY
    google_api_key: str = Field(default="")
    agent_model: str = Field(default="gemini-flash-lite-latest")

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
```

### FastAPI Auth correct usage:
```python
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# auto_error=False is REQUIRED — we handle errors manually
security = HTTPBearer(auto_error=False)

def verify_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security)
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Use Bearer scheme")
    if credentials.credentials != settings.a2a_bearer_token:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return credentials.credentials
```

### datetime deprecation fix:
```python
# WRONG (deprecated):
from datetime import datetime
default_factory=datetime.utcnow

# CORRECT:
from datetime import datetime, timezone
default_factory=lambda: datetime.now(timezone.utc)
```

### ddgs rate limiting fix:
```python
from ddgs import DDGS  # NOT from duckduckgo_search import DDGS

# Add delay between queries to avoid rate limiting
await asyncio.sleep(0.5)

# Handle empty results gracefully
def _sync_search():
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=n))
    except Exception:
        return []
```

### Fallback synthesis pattern (when DDG rate limits):
```python
# Track all tool results across iterations
all_tool_results: list[str] = []

# In tool execution loop:
if not result_text.startswith("Error") and \
   "No search results" not in result_text:
    all_tool_results.append(result_text)

# After loop, if no final text from Gemini:
if not final_text and all_tool_results:
    combined = "\n\n---\n\n".join(all_tool_results)
    synthesis_prompt = (
        f"Based on these search results, answer: {task}\n\n"
        f"Results:\n{combined}\n\nProvide clear answer with sources."
    )
    # Call Gemini once more WITHOUT tools to force text response
    synthesis_response = await asyncio.to_thread(
        client.models.generate_content,
        model=settings.agent_model,
        contents=synthesis_prompt,
        config=genai_types.GenerateContentConfig(temperature=0.1)
    )
```

### Test auth override pattern:
```python
from agents.web_search.main import app, verify_bearer_token

def override_verify_bearer_token() -> str:
    return "test-token"

@pytest_asyncio.fixture
async def auth_client(self):
    app.dependency_overrides[verify_bearer_token] = \
        override_verify_bearer_token
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()  # ALWAYS clean up after test
```

### A2A endpoint structure (every agent uses this):
```python
# 4 endpoints every A2A agent must have:
GET  /.well-known/agent.json  # PUBLIC — no auth — Agent Card
GET  /health                   # PUBLIC — no auth
POST /a2a/tasks/send           # AUTH required
POST /a2a/tasks/get            # AUTH required
POST /a2a/tasks/cancel         # AUTH required

# All task endpoints use JSON-RPC 2.0 envelope:
# Request body:  JSONRPCRequest(jsonrpc="2.0", id, method, params)
# Response body: JSONRPCResponse(jsonrpc="2.0", id, result, error)
# RULE: HTTP status is always 200 for task endpoints
#       Errors go in response body as JSONRPCError
#       ONLY auth failures use HTTP 401
```

## ARCHITECTURE OVERVIEW
Services and their ports:
- Agent Registry:        localhost:9000
- Orchestrator Agent:    localhost:8000
- Web Search Agent:      localhost:8001  ✅ COMPLETE
- Data Analysis Agent:   localhost:8002
- Document Agent:        localhost:8003
- Code Agent:            localhost:8004
- PostgreSQL:            localhost:5432
- Redis:                 localhost:6379

## CURRENT BUILD PHASE
Phase: Week 2 — START
Currently building: Base A2A agent class → Data Analysis Agent
Last completed: Web Search Agent (Week 1)
                25/25 tests passing
                Live Gemini API + tool calling confirmed working

## COMPLETED COMPONENTS

### Infrastructure
- [x] pyproject.toml with all dependencies
- [x] .env and .env.example (clean key=value only, no shell cmds)
- [x] .gitignore
- [x] shared/a2a_types.py
- [x] shared/config.py
- [x] shared/logging_config.py

### Agent Registry
- [ ] registry/models.py
- [ ] registry/database.py
- [ ] registry/main.py

### Base Agent Framework
- [ ] agents/base/a2a_server.py
- [ ] agents/base/agent_card.py

### Web Search Agent ✅ COMPLETE
- [x] agents/web_search/tools.py
- [x] agents/web_search/mcp_server.py
- [x] agents/web_search/main.py
- [x] tests/test_web_search_mcp.py (25/25 passing)
- [ ] agents/web_search/Dockerfile  ← Week 6

### Data Analysis Agent
- [ ] agents/data_analysis/tools.py
- [ ] agents/data_analysis/mcp_server.py
- [ ] agents/data_analysis/main.py
- [ ] agents/data_analysis/Dockerfile

### Document Agent
- [ ] agents/document/tools.py
- [ ] agents/document/mcp_server.py
- [ ] agents/document/main.py
- [ ] agents/document/Dockerfile

### Code Agent
- [ ] agents/code/tools.py
- [ ] agents/code/mcp_server.py
- [ ] agents/code/main.py
- [ ] agents/code/Dockerfile

### Orchestrator
- [ ] orchestrator/a2a_client.py
- [ ] orchestrator/task_decomposer.py
- [ ] orchestrator/agent.py
- [ ] orchestrator/main.py
- [ ] orchestrator/Dockerfile

### Infrastructure Files
- [ ] docker-compose.yml
- [ ] docker-compose.dev.yml
- [ ] alembic migrations

### Observability
- [ ] shared/telemetry.py
- [ ] OpenTelemetry integration in all services

### Tests
- [x] tests/test_web_search_mcp.py (25 tests)
- [ ] tests/test_registry.py
- [ ] tests/test_data_analysis.py
- [ ] tests/test_orchestrator.py
- [ ] tests/test_e2e.py

### Polish
- [ ] README.md (portfolio quality)
- [ ] docs/demo_scenarios.md
- [ ] Demo video

## KEY DESIGN DECISIONS LOG

2026-08-01 - MCP transport: HTTP not stdio
             Reason: Agents are Docker microservices.
             stdio only works for subprocess spawning.
             HTTP works for container-to-container comms.

2026-08-01 - A2A transport: HTTP + JSON-RPC 2.0
             Reason: A2A spec requirement.
             All task endpoints use JSONRPCResponse envelope.

2026-08-02 - MCP tool execution: internal bridge pattern
             Reason: Gemini calls tools internally via
             function calling API, not external MCP client.
             execute_mcp_tool() bridges Gemini ↔ MCP tools.
             MCPServer instance kept for spec compliance
             and future Claude Desktop integration.

2026-08-02 - FastAPI auth: HTTPBearer(auto_error=False)
             Reason: Gives consistent 401 for all auth failures.
             Manual error handling required.
             Tests use dependency_overrides to bypass auth.

2026-08-03 - Gemini models locked (see GEMINI MODELS section)
             Reason: Only these work on this free tier account.

2026-08-03 - ddgs replaces duckduckgo-search
             Reason: Original package renamed upstream.

2026-08-03 - Fallback synthesis pattern added
             Reason: DDG rate limits after first query.
             Gemini exhausts 5 iterations with empty results.
             Fix: collect results, force synthesis at end.

## CURRENT BLOCKERS / OPEN QUESTIONS
- Google Custom Search API key returns 403
  (Search key and Gemini key were mixed up)
  Currently using ddgs fallback only — works fine
  for development. Fix CSE key in Week 6 polish.

## FILES CLAUDE SHOULD KNOW ABOUT

### shared/a2a_types.py
- Full A2A protocol type system (Pydantic models)
- Key types: Task, AgentCard, Message, Artifact
- Part types: TextPart, DataPart, FilePart (Union = Part)
- Enums: TaskState (submitted/working/input-required/
         completed/failed/canceled)
- JSON-RPC: JSONRPCRequest, JSONRPCResponse, JSONRPCError
- A2AErrorCode: TASK_NOT_FOUND=-32001, INTERNAL_ERROR=-32603
- TaskStatus.timestamp uses datetime.now(timezone.utc)
- AgentCard: name, description, url, version, provider,
  capabilities, skills, authentication

### shared/config.py
- Pydantic v2 SettingsConfigDict (no deprecation warnings)
- Key fields: google_api_key, agent_model,
  orchestrator_model, google_search_api_key,
  google_search_engine_id, postgres_url, redis_url,
  all port numbers, jwt_secret_key, a2a_bearer_token,
  environment, log_level, agent_name
- Singleton via @lru_cache on get_settings()
- Module-level: settings = get_settings()

### shared/logging_config.py
- structlog configuration
- Dev: human-readable ConsoleRenderer
- Prod: JSON output
- Call setup_logging() once at app startup

### agents/web_search/tools.py
- from ddgs import DDGS (not duckduckgo_search)
- search_web(): Google CSE → ddgs fallback chain
- get_news(): ddgs.news() with error handling
- fetch_url(): httpx + BeautifulSoup HTML extraction
- Returns dataclasses: SearchResult, NewsResult, FetchResult
- asyncio.sleep(0.5) between ddgs queries

### agents/web_search/mcp_server.py
- MCPServer instance: mcp = MCPServer("web-search-agent")
- Three @mcp.tool() decorators: search_web_tool,
  get_news_tool, fetch_url_tool
- get_gemini_tool_declarations() → list[dict]
  Note: uses "parameters" key (not "inputSchema")
- execute_mcp_tool(name, args) → str (Gemini bridge)
- Resource: resource://web-search/capabilities

### agents/web_search/main.py
- FastAPI app with lifespan context manager
- AGENT_CARD = AgentCard(...) defined at module level
- HTTPBearer(auto_error=False) for auth
- run_agent_with_tools(): full Gemini tool loop
  with all_tool_results tracking and fallback synthesis
- _task_store: dict[str, Task] — in-memory (Week 6 → Redis)
- Task lifecycle: received → WORKING → COMPLETED

### tests/test_web_search_mcp.py
- 25 tests, all passing
- TestMCPSchemas (7 tests): schema structure
- TestToolExecution (7 tests): mocked tool logic
- TestA2AEndpoints (11 tests): HTTP endpoints
- client fixture: unauthenticated (for rejection tests)
- auth_client fixture: uses dependency_overrides

## WEEK 2 PLAN
Build in this order:
1. agents/base/a2a_server.py
   Reusable base class so Data Analysis, Document,
   Code agents don't repeat Web Search boilerplate.
   Extract: auth, task store, lifespan, common endpoints.

2. agents/data_analysis/
   Tools: run_python_code, create_chart, statistical_analysis
   Uses: pandas, matplotlib, numpy

3. registry/
   Agent Registry service (FastAPI + PostgreSQL)
   Agents register on startup, orchestrator queries it.

4. Connect Web Search Agent to registry on startup.

## SESSION NOTES

### Session 1 — Week 1 (2026-08-01 to 2026-08-03)
Built: Complete project scaffold, all shared modules,
       Web Search Agent (tools + MCP + A2A), 25 tests.

Issues resolved this session:
- setuptools flat-layout error → [tool.setuptools.packages.find]
- google-generativeai deprecated → google-genai 2.x
- mcp.server.fastmcp missing → mcp.server.mcpserver.MCPServer
- Pydantic v2 Field(env=) warnings → SettingsConfigDict
- gemini-1.5-flash 404 → gemini-flash-lite-latest
- gemini-2.5-flash not available → gemini-flash-lite-latest
- duckduckgo-search renamed → ddgs
- DDG rate limit → fallback synthesis pattern
- Auth 403 vs 401 → HTTPBearer(auto_error=False)
- .env corrupted with shell commands → rewrote clean file
- Google CSE 403 → using ddgs only (CSE fix deferred)
- "no summary generated" → all_tool_results + synthesis call

Status: 25/25 tests passing, live API confirmed working.

### Session 2 — Week 2 (next session)
Starting with: Base agent class (agents/base/a2a_server.py)