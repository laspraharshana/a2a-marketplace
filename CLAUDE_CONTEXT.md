# CLAUDE_CONTEXT.md

## PROJECT IDENTITY
- Name: A2A Multi-Agent Marketplace System
- Repo: https://github.com/YOURUSERNAME/a2a-marketplace
- Goal: Portfolio project demonstrating A2A + MCP protocols
- Target: Flat Rock job application / ML Engineer interviews
- Deadline: August 15, 2026

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
- Database: PostgreSQL + asyncpg (NO SQLAlchemy ORM)
  Raw asyncpg pool directly — simpler, faster for this scale
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

### BaseA2AAgent auth dependency pattern:
```python
# build_app() creates auth_dependency as instance-bound closure.
# Tests override via: app.dependency_overrides[_agent.auth_dependency]
# NOT a module-level function — each agent instance has its own reference.

def auth_dependency(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    return verify_bearer_token(credentials)

agent.auth_dependency = auth_dependency  # stored on instance

# In test fixture:
app.dependency_overrides[_agent.auth_dependency] = lambda: "test-token"
app.dependency_overrides.clear()  # ALWAYS clean up after test
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

### model_dump(mode="json") required for datetime serialization:
```python
# JSONResponse uses stdlib json.dumps — no datetime handler.
# Pydantic model_dump() returns datetime objects by default.
# WRONG:
return JSONRPCResponse(
    id=rpc_id,
    result=task.model_dump(),
).model_dump()

# CORRECT — mode="json" converts datetime → ISO string:
return JSONRPCResponse(
    id=rpc_id,
    result=task.model_dump(mode="json"),
).model_dump(mode="json")
# Apply to ALL .model_dump() calls that go into JSONResponse
```

### asyncio.to_thread requires sync functions:
```python
# WRONG — async wrapper sent to thread pool:
async def _run():
    exec(code)
await asyncio.to_thread(_run)  # coroutine never awaited, silent failure

# CORRECT — sync function directly:
def _run_sync():
    exec(code)
await asyncio.to_thread(_run_sync)
```

### Python sandbox __import__ blocking:
```python
# Dict restriction on __builtins__ alone does NOT block imports.
# Must explicitly add __import__ blocker:
def _blocked_import(name: str, *args, **kwargs):
    raise ImportError(f"Import of '{name}' is blocked in sandbox")

_SAFE_BUILTINS = {
    "__import__": _blocked_import,  # REQUIRED — blocks all imports
    "abs": abs,
    # ... rest of safe builtins
}
# Pre-load safe modules into exec namespace instead:
exec_globals = {
    "__builtins__": _SAFE_BUILTINS,
    "numpy": np, "np": np,
    "pandas": pd, "pd": pd,
    "math": math,
    # etc.
}
```

### asyncpg JSONB behavior:
```python
# asyncpg returns JSONB columns as JSON strings, NOT dicts.
# Must json.loads() after fetching from DB.
# Use isinstance guard so unit tests (which pass dicts) still work:

agent_card = row["agent_card"] or "{}"
if isinstance(agent_card, str):
    agent_card = json.loads(agent_card)

# Also: when inserting JSONB, must serialize to string first:
agent_card_json = json.dumps(request.agent_card)
await conn.execute("INSERT ... ($1::jsonb)", agent_card_json)
```

### FastAPI app.state in tests:
```python
# WRONG — lifespan override silently fails after app creation:
app.router.lifespan_context = mock_lifespan  # has no effect

# CORRECT — inject state directly before requests:
app.state.pool = MagicMock()      # unit tests (no real DB)
app.state.pool = real_pool        # integration tests (real DB)

# Clean up after yield:
if hasattr(app.state, "pool"):
    del app.state.pool
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

### A2A endpoint structure (every agent uses this):
```python
# 5 endpoints every A2A agent must have:
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

### AgentCard field names (exact — no typos):
```python
# provider uses "organization" not "name":
provider={"organization": "A2A Marketplace", "url": "http://localhost"}

# AgentSkill is a Pydantic model — use attribute access not dict:
skill_ids = [s.id for s in card.skills]   # CORRECT
skill_ids = [s["id"] for s in card.skills]  # WRONG — TypeError
```

### Port field names in settings (exact — no typos):
```python
settings.web_search_agent_port     # → 8001
settings.data_analysis_agent_port  # → 8002
settings.document_agent_port       # → 8003
settings.code_agent_port           # → 8004
settings.orchestrator_port         # → 8000
settings.registry_port             # → 9000
```

### Gemini tool declarations format:
```python
# Key is "parameters" (Gemini format), NOT "inputSchema" (MCP format)
{
    "name": "tool_name",
    "description": "...",
    "parameters": {          # NOT "inputSchema"
        "type": "object",
        "properties": {...},
        "required": [...],
    }
}
```

### pytest integration marks — register in pyproject.toml:
```toml
[tool.pytest.ini_options]
markers = [
    "integration: marks tests requiring live services (PostgreSQL etc.)",
]
```

### TaskState enum — UPPERCASE members (CRITICAL):
```python
# shared/a2a_types.py defines TaskState as UPPERCASE:
TaskState.SUBMITTED       # "submitted"
TaskState.WORKING         # "working"
TaskState.INPUT_REQUIRED  # "input-required"
TaskState.COMPLETED       # "completed"
TaskState.FAILED          # "failed"
TaskState.CANCELED        # "canceled"

# WRONG (lowercase — AttributeError at collection time):
TaskState.completed
TaskState.working

# Wire values (JSON) are lowercase — the .value is lowercase string.
# task.status.state.value == "completed"  ← string comparison
# task.status.state == TaskState.COMPLETED  ← enum comparison
```

### TaskStatus.message is Message | None, NOT str:
```python
# WRONG — message is a Message object, not a plain string:
TaskStatus(state=TaskState.WORKING, message="Fetching agents...")

# CORRECT — omit message or pass a Message object:
TaskStatus(state=TaskState.WORKING)
# or:
TaskStatus(
    state=TaskState.WORKING,
    message=Message(role="agent", parts=[TextPart(text="Fetching agents...")])
)
```

### Mock patch paths — use where name is USED not DEFINED:
```python
# WRONG — patches the definition module, not the consumer's binding:
patch("agents.document.tools.extract_text", ...)

# CORRECT — patches the name as imported into mcp_server's namespace:
patch("agents.document.mcp_server.extract_text", ...)

# Rule: if mcp_server.py does `from agents.document.tools import extract_text`
# then the live reference is agents.document.mcp_server.extract_text
# Patching the source module has NO effect on already-imported names.
```

### Patching static methods when the class is also patched:
```python
# WRONG — static method called on MockClass returns another MagicMock:
with patch("module.MyClass") as MockClass:
    MockClass.return_value = instance  # instance.method works
    # BUT MyClass.static_method() → unconfigured MagicMock

# CORRECT — patch the static method explicitly as a second target:
with patch("module.MyClass") as MockClass, \
     patch("module.MyClass.static_method", return_value="expected"):
    MockClient.return_value = instance
    # Now MyClass.static_method() → "expected"

# Real case: OrchestratorA2AClient.extract_text_result is a @staticmethod
# called on the CLASS inside execute_node — must patch it separately.
```

### Orchestrator auth — uses verify_token, not _agent.auth_dependency:
```python
# Orchestrator main.py defines verify_token as a module-level function
# (not instance-bound like BaseA2AAgent agents).
# Tests use settings.a2a_bearer_token directly in headers:
headers={"Authorization": f"Bearer {settings.a2a_bearer_token}"}
# NOT dependency_overrides — just send the real token.
```

## ARCHITECTURE OVERVIEW
Services and their ports:
- Agent Registry:        localhost:9000  ✅ COMPLETE
- Orchestrator Agent:    localhost:8000  ✅ COMPLETE
- Web Search Agent:      localhost:8001  ✅ COMPLETE
- Data Analysis Agent:   localhost:8002  ✅ COMPLETE
- Document Agent:        localhost:8003  ✅ COMPLETE
- Code Agent:            localhost:8004  ✅ COMPLETE
- PostgreSQL:            localhost:5432  ✅ INSTALLED (local WSL2)
- Redis:                 localhost:6379

PostgreSQL credentials:
  user: a2a
  password: a2a_password
  database: a2a_marketplace
  url: postgresql://a2a:a2a_password@localhost:5432/a2a_marketplace
  Start: sudo service postgresql start

## CURRENT BUILD PHASE
Phase: Week 4 — Docker + E2E 
Last completed: Week 3 — all agents + orchestrator done

Week 3 completed:
- Document Agent (agents/document/) — 41/41 tests
- Code Agent (agents/code/) — 41/41 tests
- Orchestrator (orchestrator/) — 32/32 unit tests
  - a2a_client.py: HTTP A2A transport layer
  - task_decomposer.py: LangGraph plan→execute→synthesize graph
  - main.py: FastAPI on port 8000, /orchestrate convenience endpoint

Running test total: 212 tests, all passing
  25  tests/test_web_search_mcp.py
  40  tests/test_data_analysis.py
  33  tests/test_registry.py
  41  tests/test_document.py
  41  tests/test_code.py
  32  tests/test_orchestrator.py  (unit only, 7 integration deselected)

## COMPLETED COMPONENTS

### Infrastructure
- [x] pyproject.toml with all dependencies
- [x] .env and .env.example (clean key=value only, no shell cmds)
- [x] .gitignore
- [x] shared/a2a_types.py
- [x] shared/config.py
- [x] shared/logging_config.py

### Agent Registry ✅ COMPLETE
- [x] registry/models.py
- [x] registry/database.py
- [x] registry/main.py
- [x] tests/test_registry.py (33/33 passing)

### Base Agent Framework ✅ COMPLETE
- [x] agents/base/a2a_server.py
- [N/A] agents/base/agent_card.py — eliminated (YAGNI)
        AgentCard lives in shared/a2a_types.py

### Web Search Agent ✅ COMPLETE
- [x] agents/web_search/tools.py
- [x] agents/web_search/mcp_server.py
- [x] agents/web_search/main.py
- [x] tests/test_web_search_mcp.py (25/25 passing)
- [ ] agents/web_search/Dockerfile  ← Week 4

### Data Analysis Agent ✅ COMPLETE
- [x] agents/data_analysis/tools.py
- [x] agents/data_analysis/mcp_server.py
- [x] agents/data_analysis/main.py
- [x] tests/test_data_analysis.py (40/40 passing)
- [ ] agents/data_analysis/Dockerfile  ← Week 4

### Document Agent ✅ COMPLETE
- [x] agents/document/tools.py
- [x] agents/document/mcp_server.py
- [x] agents/document/main.py
- [x] tests/test_document.py (41/41 passing)
- [ ] agents/document/Dockerfile  ← Week 4

### Code Agent ✅ COMPLETE
- [x] agents/code/tools.py
- [x] agents/code/mcp_server.py
- [x] agents/code/main.py
- [x] tests/test_code.py (41/41 passing)
- [ ] agents/code/Dockerfile  ← Week 4

### Orchestrator ✅ COMPLETE
- [x] orchestrator/a2a_client.py
- [x] orchestrator/task_decomposer.py
- [x] orchestrator/main.py
- [x] tests/test_orchestrator.py (32/32 unit passing, 7 integration pending)
- [ ] orchestrator/Dockerfile  ← Week 4

### Infrastructure Files
- [ ] docker-compose.yml  ← Week 4
- [ ] docker-compose.dev.yml  ← Week 4
- [ ] alembic migrations  ← Week 4 (optional, low priority)

### Observability
- [ ] shared/telemetry.py  ← Week 4 (low priority)
- [ ] OpenTelemetry integration in all services

### Tests
- [x] tests/test_web_search_mcp.py (25 tests)
- [x] tests/test_data_analysis.py (40 tests)
- [x] tests/test_registry.py (33 tests)
- [x] tests/test_document.py (41 tests)
- [x] tests/test_code.py (41 tests)
- [x] tests/test_orchestrator.py (32 unit + 7 integration)
- [ ] tests/test_e2e.py  ← Week 4

### Polish
- [x] README.md (portfolio quality)  
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

2026-08-02 - BaseA2AAgent auth_dependency as instance attribute
             Reason: Each agent's build_app() creates a closure
             stored on the instance. Tests reference it as
             _agent.auth_dependency for dependency_overrides.
             Avoids module-level function collision between agents.

2026-08-03 - Gemini models locked (see GEMINI MODELS section)
             Reason: Only these work on this free tier account.

2026-08-03 - ddgs replaces duckduckgo-search
             Reason: Original package renamed upstream.

2026-08-03 - Fallback synthesis pattern added
             Reason: DDG rate limits after first query.
             Gemini exhausts iterations with empty results.
             Fix: collect results, force synthesis at end.

2026-08-04 - Raw asyncpg over SQLAlchemy ORM
             Reason: Registry has ~5 queries total.
             asyncpg is faster, simpler, less abstraction.
             SQLAlchemy async adds session complexity for no gain.

2026-08-04 - JSONB returned as string by asyncpg
             Reason: asyncpg does not auto-decode JSONB to dict.
             Fix: json.loads() in from_db_row() with isinstance
             guard so unit tests (dict input) still pass.

2026-08-04 - app.state injection pattern for tests
             Reason: app.router.lifespan_context replacement
             silently fails in this Starlette version.
             Fix: set app.state.pool directly in fixtures.

2026-08-04 - Soft delete for agent deregistration
             Reason: Preserves history for debugging.
             Orchestrator filters by status=active.
             Re-registration reactivates via ON CONFLICT DO UPDATE.

2026-08-05 - Code Agent uses subprocess not exec()
             Reason: Code Agent's purpose is running arbitrary
             user code. exec() with blocked imports defeats that.
             subprocess.run() gives process isolation, hard timeout,
             memory cap via resource.setrlimit (Linux/WSL2).

2026-08-05 - Document summarize_document calls Gemini directly
             Reason: Summarization IS the LLM task, not a step
             toward another response. Nested LLM call is intentional.
             Same pattern as explain_code in Code Agent.

2026-08-05 - Orchestrator uses LangGraph for state machine
             Reason: Need to coordinate multiple agents across time,
             tracking what's been done and what's left.
             LangGraph: plan→execute→synthesize loop with MAX_ITERATIONS=5.
             Agents themselves are stateless — only orchestrator has graph.

2026-08-05 - Orchestrator TaskStatus.message left as None
             Reason: TaskStatus.message is Message | None (not str).
             Setting it requires constructing a full Message object.
             For orchestrator simplicity, omit message field entirely.

2026-08-05 - OrchestratorA2AClient.extract_text_result is @staticmethod
             Reason: Called on the class directly in execute_node.
             In tests, must patch it separately when MockClient patches
             the class — MockClass.extract_text_result returns MagicMock
             unless explicitly configured.

## CURRENT BLOCKERS / OPEN QUESTIONS
- Google Custom Search API key returns 403 : RESOLVED ✅ 
  (Search key and Gemini key were mixed up)
  Currently using ddgs fallback only — works fine
  for development. Fix CSE key in Week 4 polish.
- Integration tests (7 in test_orchestrator.py) require all
  services running simultaneously — deferred to Week 4 E2E session.

## FILES CLAUDE SHOULD KNOW ABOUT

### shared/a2a_types.py
- Full A2A protocol type system (Pydantic models)
- TaskState: UPPERCASE members (SUBMITTED, WORKING, INPUT_REQUIRED,
             COMPLETED, FAILED, CANCELED) — values are lowercase strings
- TaskStatus.message: Message | None — NOT a plain string
- TaskStatus.timestamp: datetime.now(timezone.utc)
- Part types: TextPart, DataPart, FilePart (Union = Part)
- JSON-RPC: JSONRPCRequest, JSONRPCResponse, JSONRPCError
- A2AErrorCode: TASK_NOT_FOUND=-32001, INTERNAL_ERROR=-32603
- AgentCard: name, description, url, version, provider,
  capabilities, skills, authentication
- AgentProvider: organization (not name), url
- AgentSkill: Pydantic model — use .id not ["id"]
- Artifact: artifactId (auto UUID), name, parts, metadata

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

### agents/base/a2a_server.py
- BaseA2AAgent: abstract base for all agents
- Abstract methods: get_tool_declarations(),
  execute_tool(), get_system_prompt()
- Class variable: agent_card (AgentCard instance)
- Gemini tool loop: run_agent_with_tools()
  with fallback synthesis pattern
- Task store: _task_store dict (in-memory, Week 4 → Redis)
- Task lifecycle methods: _create_task, _update_task_working,
  _complete_task, _fail_task, _cancel_task, _get_task
- JSON-RPC handlers: handle_tasks_send, handle_tasks_get,
  handle_tasks_cancel (all use model_dump(mode="json"))
- Registry integration: register_with_registry(),
  deregister_from_registry(), start_heartbeat_loop()
- build_app() → FastAPI: creates auth_dependency closure,
  stores on self, builds all 5 endpoints
- Auth: auth_dependency instance attribute (not module-level)
  Tests: app.dependency_overrides[_agent.auth_dependency]

### registry/models.py
- AgentStatus enum: active, inactive, unknown
- AgentRegistrationRequest: name, url, version,
  capabilities, agent_card
- AgentRecord: full DB row model with from_db_row() classmethod
  from_db_row() handles asyncpg JSONB string → dict conversion
- RegistrationResponse, AgentListResponse, HealthResponse

### registry/database.py
- Raw asyncpg — no SQLAlchemy
- create_pool(): min_size=2, max_size=10, command_timeout=30
- init_db(): CREATE TABLE IF NOT EXISTS registered_agents
  with SERIAL PK, UNIQUE(name), TEXT[], JSONB, TIMESTAMPTZ
- register_agent(): INSERT ... ON CONFLICT (name) DO UPDATE
- get_agent(), list_agents(), update_heartbeat()
- deregister_agent(): soft delete (status=inactive)
- mark_agent_inactive(): called by health checker
- get_agent_counts(): total + active counts

### registry/main.py
- FastAPI app on port 9000
- health_check_loop(): background task, polls agents every 60s
  httpx GET to health_check_url, marks failures inactive
- Lifespan: creates pool, inits DB, starts health checker task
- All endpoints: no auth (internal network assumption)
- Endpoints: register, list, get, heartbeat, deregister, health

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
- FastAPI app via BaseA2AAgent.build_app()
- WebSearchAgent(BaseA2AAgent) with agent_card class variable
- Module level: _agent = WebSearchAgent(); app = _agent.build_app()

### agents/data_analysis/tools.py
- run_python_code(): sandboxed exec with _blocked_import
  _SAFE_BUILTINS includes __import__ blocker
  _SAFE_MODULES pre-loaded: numpy, pandas, math, statistics etc.
  _run_sync() is sync function (not async) for asyncio.to_thread
  stdout captured via io.StringIO redirect
- statistical_analysis(): pure stdlib statistics module
  handles flat list or list-of-dicts with column param
  returns count, mean, median, std_dev, percentiles, IQR, skewness
- create_chart(): matplotlib Agg backend (no display needed)
  types: bar, line, scatter, histogram, pie
  returns base64 PNG string (no file I/O)
  plt.close(fig) after every chart to prevent memory leak

### agents/data_analysis/mcp_server.py
- MCPServer instance: mcp = MCPServer("data-analysis-agent")
- Three @mcp.tool() decorators
- get_gemini_tool_declarations() → list[dict]
- execute_mcp_tool(name, args) → str

### agents/data_analysis/main.py
- DataAnalysisAgent(BaseA2AAgent)
- Uses settings.data_analysis_agent_port (not data_analysis_port)
- Module level: _agent = DataAnalysisAgent(); app = _agent.build_app()

### agents/document/tools.py
- extract_text(): PDF/DOCX/TXT/URL → ExtractionResult
  pypdf for PDF (io.BytesIO, thread pool)
  python-docx for DOCX (io.BytesIO, thread pool)
  httpx async for URLs, BeautifulSoup HTML cleaning
  Auto-detects type from extension or URL scheme
- summarize_document(): calls Gemini directly (nested LLM call)
  4 styles: concise, detailed, bullet, executive
  Parses KEY_POINTS_JSON marker from response
  Truncates to 12k chars before sending to Gemini
- extract_entities(): regex heuristics (no spaCy/NER)
  Types: emails, urls, dates, numbers, names, organizations

### agents/document/mcp_server.py
- MCPServer instance: mcp = MCPServer("document-agent")
- extract_text_tool: caps text at 8000 chars in response,
  sets text_truncated=True if full_text_length > 8000
- summarize_document_tool, extract_entities_tool
- Patch target for tests: agents.document.mcp_server.<fn>
  NOT agents.document.tools.<fn>

### agents/document/main.py
- DocumentAgent(BaseA2AAgent), port 8003
- 3 skills: extract-text, summarize, extract-entities

### agents/code/tools.py
- analyze_code(): ast.parse() + radon cc_visit()
  Returns function/class/import counts, complexity per function
  _complexity_grade(): A(1-5) B(6-10) C(11-15) D(16-20) E(21-25) F(26+)
  Degrades gracefully if radon not installed
- execute_code(): subprocess.run() with sys.executable
  Hard timeout via subprocess timeout= param
  Memory cap via resource.setrlimit RLIMIT_AS (Linux/WSL2)
  preexec_fn=_set_memory_limit passed to subprocess.run
  NOT exec() — purpose is running arbitrary code
- explain_code(): Gemini direct call, 3 detail levels
  Parses COMPLEXITY_SUMMARY and SUGGESTIONS_JSON markers

### agents/code/mcp_server.py
- MCPServer instance: mcp = MCPServer("code-agent")
- analyze_code_tool, execute_code_tool, explain_code_tool
- Patch target for tests: agents.code.mcp_server.<fn>

### agents/code/main.py
- CodeAgent(BaseA2AAgent), port 8004
- 3 skills: analyze-code, execute-code, explain-code

### orchestrator/a2a_client.py
- OrchestratorA2AClient: async context manager
- send_task(): sends tasks/send, polls until terminal state
  Terminal states: COMPLETED, FAILED, CANCELED
  Non-terminal: SUBMITTED, WORKING, INPUT_REQUIRED
  INPUT_REQUIRED → cancel + raise A2AClientError
- get_task(), cancel_task(), check_health()
- extract_text_result(): @staticmethod, extracts text from Task
  Called as OrchestratorA2AClient.extract_text_result(task)
  Must patch separately when MockClient patches the class
- _TERMINAL_STATES = {TaskState.COMPLETED, TaskState.FAILED,
                      TaskState.CANCELED}
- Exceptions: A2AClientError (network/protocol),
              A2ATaskError (task failed/canceled, has .task attribute)

### orchestrator/task_decomposer.py
- LangGraph StateGraph with 3 nodes: plan, execute, synthesize
- OrchestratorState TypedDict: user_query, available_agents,
  plan, completed_calls, final_answer, iteration, error
- AgentCallSpec TypedDict: agent_name, agent_url, message, reason
- AgentCallResult TypedDict: agent_name, agent_url, message,
  result, success, error
- MAX_ITERATIONS = 5 (safety limit on plan→execute loop)
- plan_node: calls _call_gemini_plan → returns AgentCallSpec list
  Empty list = "DONE" = route to synthesize
- execute_node: asyncio.gather() all specs concurrently
  Accumulates results across iterations (does not replace)
  Failures recorded as AgentCallResult(success=False) — not raised
- synthesize_node: calls _call_gemini_synthesize → final answer
- orchestrator_graph: module-level compiled graph (built once)
- run_orchestrator(query, available_agents) → (answer, calls)

### orchestrator/main.py
- FastAPI on port 8000
- verify_token(): module-level function (not instance-bound)
  Tests send real token in headers — no dependency_overrides
- fetch_available_agents(): httpx GET to registry /agents
  Returns [] on any error (orchestrator degrades gracefully)
- handle_orchestrate(query, task_id): core pipeline
  Sets TaskStatus(state=TaskState.WORKING) — no message field
  Calls run_orchestrator() → builds Task(state=TaskState.COMPLETED)
- Extra endpoints: GET /agents, POST /orchestrate
  /orchestrate: {"query": "..."} → {"answer", "task_id",
                "state", "agents_called", "calls_made"}
- Standard A2A: tasks/send, tasks/get, tasks/cancel

### tests/test_web_search_mcp.py
- 25 tests, all passing
- TestMCPSchemas (7), TestToolExecution (7), TestA2AEndpoints (11)
- auth_client: app.dependency_overrides[verify_bearer_token]

### tests/test_data_analysis.py
- 40 tests, all passing
- TestMCPSchemas (7), TestToolExecution (14),
  TestBaseAgent (6), TestA2AEndpoints (13)
- auth_client: app.dependency_overrides[_agent.auth_dependency]
- Gemini mock: patch("agents.base.a2a_server.asyncio.to_thread")
- call_count == 3 for two-round tool test (not 2):
  call1=Gemini, call2=tool's asyncio.to_thread, call3=Gemini

### tests/test_registry.py
- 33 tests (29 unit + 4 integration)
- TestRegistryModels (6), TestDatabaseLayer (10),
  TestRegistryEndpoints (13), TestIntegration (4)
- app.state.pool = MagicMock() for unit tests
- live_client fixture for integration: create_pool() + init_db()

### tests/test_document.py
- 41 tests, all passing
- TestMCPSchemas (7), TestToolExecution (14),
  TestBaseAgent (6), TestA2AEndpoints (13)
- Patch target: agents.document.mcp_server.extract_text
  NOT agents.document.tools.extract_text

### tests/test_code.py
- 41 tests, all passing
- TestMCPSchemas (7), TestToolExecution (14),
  TestBaseAgent (6), TestA2AEndpoints (13)
- test_execute_code_real_subprocess: real subprocess, no mock
- Patch target: agents.code.mcp_server.<fn>

### tests/test_orchestrator.py
- 39 total (32 unit selected, 7 integration deselected)
- TestA2AClient (11): mock httpx.AsyncClient.post/get
- TestTaskDecomposer (8): mock _call_gemini_plan/synthesize
- TestOrchestratorApp (13): mock fetch_available_agents +
  run_orchestrator, send real bearer token in headers
- TestIntegration (7): @pytest.mark.integration, live services
- extract_text_result patching:
  patch("orchestrator.task_decomposer.OrchestratorA2AClient")
  + patch("orchestrator.task_decomposer.OrchestratorA2AClient
          .extract_text_result", return_value="text")

## WEEK 4 PLAN
Build in this order (priority order):

1. docker-compose.yml — all 6 services + postgres + redis.
   Each agent gets its own container.
   Shared network: a2a-network.
   Healthchecks on all services.

2. Dockerfiles — one per service (6 total + registry).
   Base: python:3.12-slim
   Non-root user, .venv copied in, uvicorn CMD.

3. tests/test_e2e.py — full flow with all services running.
   @pytest.mark.integration, requires docker-compose up.
   Prerequisites: sudo service postgresql start,
                  docker compose up
   3-4 scenarios:
   - search + summarize compound query
   - code analyze + execute pipeline
   - document extract + data analysis
   - multi-agent orchestrated query
   Run with: pytest tests/test_e2e.py -m integration -v
  

4. shared/telemetry.py — OpenTelemetry basic setup.
   trace_id propagation in A2A headers.
   Low priority — add after Docker works.

5. docs/demo_scenarios.md — scripted interview demo.
   Step-by-step commands that show the system working.
   Screenshots or expected outputs included.

### Docker + WSL2 service startup order:
```bash
# ALWAYS start in this order:
sudo service postgresql start   # DB first
redis-server --daemonize yes    # Cache second  
python -m registry.main &       # Registry third
# Then agents (any order)
python -m agents.web_search.main &
python -m agents.data_analysis.main &
python -m agents.document.main &
python -m agents.code.main &
# Orchestrator last (needs registry)
python -m orchestrator.main &

# In Docker Compose: use depends_on + healthcheck
# to enforce this order automatically.
```

## SESSION NOTES

### Session 1 — Week 1 (2026-08-01 to 2026-08-03)
Built: Complete project scaffold, all shared modules,
       Web Search Agent (tools + MCP + A2A), 25 tests.

Issues resolved:
- setuptools flat-layout error → [tool.setuptools.packages.find]
- google-generativeai deprecated → google-genai 2.x
- mcp.server.fastmcp missing → mcp.server.mcpserver.MCPServer
- Pydantic v2 Field(env=) warnings → SettingsConfigDict
- gemini-1.5-flash 404 → gemini-flash-lite-latest
- duckduckgo-search renamed → ddgs
- DDG rate limit → fallback synthesis pattern
- Auth 403 vs 401 → HTTPBearer(auto_error=False)
- .env corrupted with shell commands → rewrote clean file
- Google CSE 403 → using ddgs only (CSE fix deferred)
- "no summary generated" → all_tool_results + synthesis call

Status: 25/25 tests passing, live API confirmed working.

### Session 2 — Week 2 (2026-08-04 to 2026-08-05)
Built: BaseA2AAgent, Data Analysis Agent, Agent Registry,
       registry auto-registration in base class.

Issues resolved:
- settings.data_analysis_port → settings.data_analysis_agent_port
- AgentCard provider {"name"} → {"organization"}
- asyncio.to_thread(_async_fn) → asyncio.to_thread(_sync_fn)
- __builtins__ dict alone doesn't block imports →
  add __import__: _blocked_import to _SAFE_BUILTINS
- AgentSkill["id"] → AgentSkill.id (Pydantic model not dict)
- model_dump() datetime not serializable →
  model_dump(mode="json") everywhere JSONResponse is used
- asyncpg JSONB returns str not dict → json.loads() in from_db_row
- app.router.lifespan_context replacement silently fails →
  app.state.pool = pool directly in test fixtures
- call_count == 2 wrong → call_count == 3 (tool also uses to_thread)

Status: 98/98 tests passing.

### Session 3 — Week 3 (2026-08-05 to 2026-08-06)
Built: Document Agent, Code Agent, Orchestrator.

Issues resolved:
- patch("agents.document.tools.extract_text") has no effect →
  must patch agents.document.mcp_server.extract_text
  (patch where name is USED not DEFINED)
- TaskState.completed AttributeError at collection time →
  TaskState uses UPPERCASE: TaskState.COMPLETED
- TaskStatus(message="string") Pydantic error →
  message field is Message | None, not str
  Fix: omit message field in orchestrator
- OrchestratorA2AClient.extract_text_result (staticmethod)
  returns MagicMock when class is patched →
  must patch staticmethod separately as second patch target

Status: 212/212 tests passing (32 orchestrator unit tests).
  25  test_web_search_mcp.py
  40  test_data_analysis.py
  33  test_registry.py
  41  test_document.py
  41  test_code.py
  32  test_orchestrator.py (unit only)