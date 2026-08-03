<div align="center">

# ⚡ A2A Multi-Agent Marketplace

### 🧠 A production-grade multi-agent system where AI agents **discover** 🔎, **negotiate** 🤝, and **collaborate** 🚀 using Google's Agent-to-Agent (A2A) protocol and Anthropic's Model Context Protocol (MCP).

<br/>

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Google Gemini](https://img.shields.io/badge/Gemini-Flash-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://ai.google.dev)
[![MCP](https://img.shields.io/badge/MCP-2.0-FF6B35?style=for-the-badge&logo=anthropic&logoColor=white)](https://modelcontextprotocol.io)
[![Docker](https://img.shields.io/badge/Docker-Native_WSL2-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)
[![Tests](https://img.shields.io/badge/Tests-25%2F25_Passing-22C55E?style=for-the-badge&logo=pytest&logoColor=white)](./tests)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](./LICENSE)

<br/>

**[📖 Overview](#-overview)** · **[🏗️ Architecture](#️-architecture)** · **[🔌 Protocols](#-protocols)** · **[🤖 Agents](#-specialist-agents)** · **[⚡ Quick Start](#-quick-start)** · **[📡 API Reference](#-api-reference)** · **[🎬 Demo](#-demo-scenarios)**

</div>

<br/>

---

## 📖 Overview

> [!NOTE]
> This project implements two of the most important emerging protocols in the AI industry — side by side, in production form.

| Protocol | ⚙️ By | 🎯 Purpose |
|:---|:---|:---|
| 🌐 **A2A** — Agent-to-Agent | Google · April 2025 | Standardizes how AI agents **discover** and **communicate** with each other |
| 🧩 **MCP** — Model Context Protocol | Anthropic | Standardizes how agents **access tools**, resources, and APIs |

Instead of one monolithic AI trying to do everything, this system orchestrates a **marketplace of specialist agents** — each expert at one domain — that collaborate to solve complex, multi-step tasks.

```text
👤 User: "Research quantum computing companies in Singapore,
          analyze their funding trends, and create a visualization"

🧭 Orchestrator → discovers agents → decomposes task → delegates → synthesizes
     │
     ├──► 🔎 WebSearch Agent    → finds companies and news
     ├──► 📊 DataAnalysis Agent → processes funding data
     ├──► 📄 Document Agent     → extracts PDF reports
     └──► 💻 Code Agent         → generates visualizations
```

<br/>

---

## 🏗️ Architecture

```text
+----------------------------------------------------------------------------+
|                        A2A MULTI-AGENT MARKETPLACE                         |
|                                                                            |
|  +-----------------------------------------------------------------------+ |
|  |                        AGENT REGISTRY  ·  :9000                       | |
|  |                      FastAPI + PostgreSQL + Redis                     | |
|  |         Stores Agent Cards | Health Status | Capability Index         | |
|  +-----------------------------------------------------------------------+ |
|                                                                            |
|                                 | HTTP Discovery                           |
|  +-----------------------------------------------------------------------+ |
|  |                      ORCHESTRATOR AGENT  ·  :8000                     | |
|  |                        LangGraph + Gemini Flash                       | |
|  |                                                                       | |
|  |            1 Receive task   2 Query Registry   3 Decompose            | |
|  |            4 Delegate via A2A   5 Aggregate   6 Synthesize            | |
|  +-----------------------------------------------------------------------+ |
|        A2A               A2A               A2A               A2A           |
|  +--------------+  +--------------+  +--------------+  +--------------+    |
|  |  WebSearch   |  |     Data     |  |   Document   |  |     Code     |    |
|  | Agent :8001  |  |   Analysis   |  | Agent :8003  |  | Agent :8004  |    |
|  |              |  | Agent :8002  |  |              |  |              |    |
|  |              |  |              |  |              |  |              |    |
|  |  MCP tools:  |  |  MCP tools:  |  |  MCP tools:  |  |  MCP tools:  |    |
|  | search_web   |  | run_python   |  | read_pdf     |  | write_code   |    |
|  | get_news     |  | create_chart |  | extract      |  | debug        |    |
|  | fetch_url    |  | stats        |  | summarize    |  | test_code    |    |
|  |              |  |              |  |              |  |              |    |
|  |    Gemini    |  |    Gemini    |  |    Gemini    |  |    Gemini    |    |
|  |  Flash Lite  |  |  Flash Lite  |  |  Flash Lite  |  |  Flash Lite  |    |
|  +--------------+  +--------------+  +--------------+  +--------------+    |
|                                                                            |
|  +-----------------------------------------------------------------------+ |
|  |                             INFRASTRUCTURE                            | |
|  |         PostgreSQL :5432   |   Redis :6379   |   OpenTelemetry        | |
|  +-----------------------------------------------------------------------+ |
+----------------------------------------------------------------------------+
```

### 📁 Directory Structure

```text
a2a-marketplace/
│
├── 📁 shared/                      # Shared across all services
│   ├── a2a_types.py                # A2A protocol Pydantic models
│   ├── config.py                   # Pydantic v2 settings
│   ├── logging_config.py           # Structured logging (structlog)
│   └── telemetry.py                # OpenTelemetry setup
│
├── 📁 agents/
│   ├── 📁 base/                    # Reusable A2A base class
│   │   └── a2a_server.py
│   │
│   ├── 📁 web_search/              # ✅ Complete
│   │   ├── tools.py                # search_web, get_news, fetch_url
│   │   ├── mcp_server.py           # MCPServer 2.0 tool definitions
│   │   └── main.py                 # FastAPI A2A service
│   │
│   ├── 📁 data_analysis/           # 🚧 pandas + matplotlib
│   ├── 📁 document/                # 📋 PDF + DOCX processing
│   └── 📁 code/                    # 📋 Code generation + execution
│
├── 📁 orchestrator/                # LangGraph orchestration
│   ├── a2a_client.py               # A2A protocol HTTP client
│   ├── task_decomposer.py          # LLM-powered task planning
│   ├── agent.py                    # LangGraph agent logic
│   └── main.py                     # FastAPI service
│
├── 📁 registry/                    # Agent discovery service
│   ├── models.py                   # SQLAlchemy models
│   ├── database.py                 # Async DB setup
│   └── main.py                     # Registry FastAPI service
│
├── 📁 tests/                       # 25+ tests, all passing ✅
│   ├── test_web_search_mcp.py      # ✅ 25/25 passing
│   ├── test_registry.py
│   ├── test_orchestrator.py
│   └── test_e2e.py
│
├── 🐳 docker-compose.yml           # Full system orchestration
├── 🐳 docker-compose.dev.yml       # Development overrides
└── 📦 pyproject.toml               # Single dependency source
```

<br/>

---

## 🔌 Protocols

### 🧩 MCP — Model Context Protocol

```text
HOW MCP WORKS IN THIS SYSTEM
─────────────────────────────────────────────

  ✨ Gemini LLM
      │
      │  "I need to search the web"
      ▼
  🧩 MCP Tool Declarations
  ┌──────────────────────────────────────┐
  │  search_web_tool(query, max=5)       │
  │  get_news_tool(topic, max=5)         │
  │  fetch_url_tool(url)                 │
  └──────────────────────────────────────┘
      │
      │  function_call { name, args }
      ▼
  ⚙️ execute_mcp_tool(name, args)
      │
      ▼
  🔧 Actual Tool Execution → Result String
      │
      ▼
  FunctionResponse back to Gemini
      │
      ▼
  💬 Final synthesized text response
```

Each specialist agent exposes its capabilities as **MCP tools** using `MCPServer` from the `mcp` SDK 2.0. Tools are defined with type-hinted Python functions — the SDK generates JSON schemas automatically.

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("web-search-agent", version="1.0.0")

@mcp.tool()
async def search_web_tool(query: str, max_results: int = 5) -> str:
    """Search the web for current information on any topic."""
    results = await search_web(query=query, max_results=max_results)
    return format_results(results)
```

<br/>

### 🌐 A2A — Agent-to-Agent Protocol

```text
HOW A2A WORKS IN THIS SYSTEM
─────────────────────────────────────────────

  🧭 Orchestrator                    🔎 WebSearch Agent
      │                                    │
      │   GET /.well-known/agent.json      │
      │ ──────────────────────────────────►│  ← 🪪 Agent Card (capabilities)
      │ ◄────────────────────────────────── │
      │                                    │
      │   POST /a2a/tasks/send             │
      │   JSONRPCRequest {                 │
      │     method: "tasks/send"           │
      │     params: { message: ... }       │
      │   }                                │
      │ ──────────────────────────────────►│
      │                                    │  ← 🔧 Agent runs tools
      │   JSONRPCResponse {                │  ← ✨ Gemini synthesizes
      │     result: Task {                 │
      │       status: "completed"          │
      │       artifacts: [...]             │
      │     }                              │
      │   }                                │
      │ ◄────────────────────────────────── │
```

Every agent serves an **Agent Card** at `/.well-known/agent.json` — a machine-readable manifest describing capabilities, skills, and authentication requirements. The orchestrator reads these cards to make intelligent delegation decisions.

```json
{
  "name": "WebSearchAgent",
  "version": "1.0.0",
  "capabilities": {
    "streaming": false,
    "stateTransitionHistory": true
  },
  "skills": [
    {
      "id": "web_search",
      "name": "Web Search",
      "description": "Search and summarize web content on any topic",
      "tags": ["search", "web", "research"],
      "inputModes": ["text"],
      "outputModes": ["text", "data"]
    }
  ],
  "authentication": { "schemes": ["bearer"] }
}
```

<br/>

---

## 🤖 Specialist Agents

### 🔎 Web Search Agent · `:8001` ✅

> Searches the web, fetches news, and reads URLs using a multi-provider fallback chain.

| 🛠️ Tool | 📋 Description | 🔌 Provider |
|:---|:---|:---|
| `search_web_tool` | General web search with snippet extraction | Google CSE → ddgs |
| `get_news_tool` | Recent news articles with dates and sources | ddgs News |
| `fetch_url_tool` | Full page content extraction, HTML stripped | httpx + BeautifulSoup |

**⛓️ Fallback Chain:**
```text
🥇 Google Custom Search API (100/day free)
         ↓ (on failure)
🥈 DuckDuckGo via ddgs (unlimited, no key)
         ↓ (on rate limit)
🥉 Fallback synthesis from cached results
```

<br/>

### 📊 Data Analysis Agent · `:8002` 🚧

> Runs Python code, generates charts, and performs statistical analysis on structured data.

| 🛠️ Tool | 📋 Description |
|:---|:---|
| `run_python_tool` | Execute Python in a sandboxed environment |
| `create_chart_tool` | Generate matplotlib visualizations |
| `statistical_analysis_tool` | Descriptive stats, correlations, trends |

<br/>

### 📄 Document Agent · `:8003` 📋

> Reads and extracts structured information from PDF and DOCX files.

| 🛠️ Tool | 📋 Description |
|:---|:---|
| `read_pdf_tool` | Extract text from PDF files |
| `extract_data_tool` | Structured data extraction from documents |
| `summarize_tool` | AI-powered document summarization |

<br/>

### 💻 Code Agent · `:8004` 📋

> Writes, debugs, and tests code across multiple programming languages.

| 🛠️ Tool | 📋 Description |
|:---|:---|
| `write_code_tool` | Generate code from natural language specs |
| `debug_code_tool` | Identify and fix bugs with explanations |
| `test_code_tool` | Generate unit tests for existing code |

<br/>

---

## ⚡ Quick Start

### ✅ Prerequisites

```bash
# Required
Python 3.12+
Docker (native Linux or WSL2)
Git

# Get a free Gemini API key
# → https://aistudio.google.com/apikey
```

### 📦 Installation

```bash
# 1️⃣ Clone the repository
git clone https://github.com/YOURUSERNAME/a2a-marketplace.git
cd a2a-marketplace

# 2️⃣ Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3️⃣ Install all dependencies
pip install -e ".[web-search,data-analysis,document,code,dev]"

# 4️⃣ Configure environment
cp .env.example .env
# Edit .env with your API keys
nano .env
```

### 🔐 Environment Configuration

```ini
# .env — minimum required configuration
GOOGLE_API_KEY=your_gemini_api_key_here     # https://aistudio.google.com
AGENT_MODEL=gemini-flash-lite-latest
ORCHESTRATOR_MODEL=gemini-flash-latest
A2A_BEARER_TOKEN=your-secret-token-here
```

### ▶️ Run a Single Agent

```bash
# Start the Web Search Agent
python -m agents.web_search.main

# Verify it's running
curl http://localhost:8001/health
# → {"status": "healthy", "agent": "web-search-agent"}

# View its capabilities
curl http://localhost:8001/.well-known/agent.json | python3 -m json.tool
```

### 🐳 Run the Full System

```bash
# Start all services with Docker Compose
docker compose up --build
```

| 🧩 Service | 🌐 URL |
|:---|:---|
| 🗂️ Agent Registry | `http://localhost:9000` |
| 🧭 Orchestrator | `http://localhost:8000` |
| 🔎 Web Search Agent | `http://localhost:8001` |
| 📊 Data Analysis | `http://localhost:8002` |
| 📄 Document Agent | `http://localhost:8003` |
| 💻 Code Agent | `http://localhost:8004` |

### 🧪 Run Tests

```bash
# All tests
pytest tests/ -v

# Specific agent tests
pytest tests/test_web_search_mcp.py -v

# With coverage report
pytest tests/ --cov=agents --cov-report=html
```

<br/>

---

## 📡 API Reference

### 🌐 A2A Standard Endpoints

Every agent exposes the same A2A-compliant interface:

#### `GET /.well-known/agent.json`
Returns the Agent Card — no authentication required.

```bash
curl http://localhost:8001/.well-known/agent.json
```

#### `GET /health`
Health check for load balancers and orchestration.

```bash
curl http://localhost:8001/health
# → {"status": "healthy", "agent": "web-search-agent", "version": "1.0.0"}
```

#### `POST /a2a/tasks/send`
Send a task to the agent. Requires Bearer token. 🔒

```bash
curl -X POST http://localhost:8001/a2a/tasks/send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-token" \
  -d '{
    "jsonrpc": "2.0",
    "id": "req-001",
    "method": "tasks/send",
    "params": {
      "id": "task-001",
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "Search for AI startups in Singapore"}]
      }
    }
  }'
```

**📥 Response:**
```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "result": {
    "id": "task-001",
    "status": { "state": "completed" },
    "artifacts": [{
      "name": "search_results",
      "parts": [{"type": "text", "text": "Based on search results..."}]
    }]
  }
}
```

#### `POST /a2a/tasks/get`
Retrieve a task by ID.

#### `POST /a2a/tasks/cancel`
Cancel a running task. 🛑

### 🔄 Task State Machine

```text
submitted ──► working ──► completed ✅
                │
                ├──► input-required ──► working
                ├──► failed ❌
                └──► canceled 🚫
```

<br/>

---

## 🎬 Demo Scenarios

### 1️⃣ Market Research 📈

```bash
curl -X POST http://localhost:8000/orchestrate \
  -H "Authorization: Bearer your-token" \
  -d '{
    "task": "Research quantum computing companies in Singapore,
             find their funding data, and summarize the landscape"
  }'
```

```text
🧭 Orchestrator delegates:
  → 🔎 WebSearch Agent:    finds companies
  → 📊 DataAnalysis Agent: processes funding data
  → 🧵 Synthesizes:        comprehensive report
```

<br/>

### 2️⃣ Document Analysis 📄

```bash
curl -X POST http://localhost:8000/orchestrate \
  -H "Authorization: Bearer your-token" \
  -d '{
    "task": "Read this research paper PDF and create a
             Python visualization of the key findings",
    "attachments": ["paper.pdf"]
  }'
```

```text
🧭 Orchestrator delegates:
  → 📄 Document Agent: extracts paper content
  → 💻 Code Agent:     generates visualization code
  → 🧵 Synthesizes:    report + working chart
```

<br/>

### 3️⃣ Live News Analysis 📰

```bash
curl -X POST http://localhost:8001/a2a/tasks/send \
  -H "Authorization: Bearer your-token" \
  -d '{
    "jsonrpc": "2.0",
    "id": "demo-001",
    "method": "tasks/send",
    "params": {
      "id": "task-demo-001",
      "message": {
        "role": "user",
        "parts": [{"type": "text",
          "text": "Search for top 3 AI companies in Singapore"}]
      }
    }
  }'
```

> [!TIP]
> **Actual response (live):**
>
> Based on search results, top AI companies in Singapore include:
>
> 1. **PatSnap** — AI-powered IP and R&D intelligence platform, NUS alumni founded, recognized unicorn
> 2. **Advance Intelligence Group (ADVANCE.AI)** — Leading AI-driven big data and digital identity verification
> 3. **AI Singapore (AISG)** — National R&D program developing foundational AI models including Sea-Lion
>
> *Sources: Built In Singapore, Second Talent, International Business Times*

<br/>

---

## 🛠️ Tech Stack

| 🧱 Layer | 🔧 Technology | 🏷️ Version | 🎯 Purpose |
|:---|:---|:---|:---|
| Protocol | 🌐 A2A (Google) | April 2025 | Agent-to-agent communication |
| Protocol | 🧩 MCP (Anthropic) | 2.0 | Tool and resource access |
| LLM | ✨ Google Gemini | Flash / Flash Lite | Reasoning and synthesis |
| Framework | ⚡ FastAPI | 0.115 | Agent HTTP services |
| Agent Logic | 🕸️ LangGraph | 0.2 | Orchestrator graph execution |
| MCP SDK | 🧩 mcp | 2.0.0 | MCPServer tool definitions |
| Gemini SDK | ✨ google-genai | 2.16.0 | LLM API client |
| Database | 🐘 PostgreSQL | 15 | Task history, agent registry |
| Cache | 🔴 Redis | 7 | Agent state, session data |
| Search | 🔎 ddgs | 9+ | Free web search fallback |
| Validation | 🛡️ Pydantic | v2 | Type safety throughout |
| Logging | 📝 structlog | 24+ | Structured JSON logging |
| Tracing | 🔭 OpenTelemetry | 1.25 | Distributed trace A2A calls |
| Testing | 🧪 pytest | 8.2 | 25+ tests, async support |
| Container | 🐳 Docker | 29.1.3 | Microservice deployment |

<br/>

---

## 🧠 Key Design Decisions

### ❓ Why A2A + MCP Together?

```text
🧩 MCP answers: "How does an agent USE tools?"
🌐 A2A answers: "How does an agent TALK to other agents?"

Together they enable:
├── 🧩 Agent discovers tools via MCP
├── 🌐 Agent delegates sub-tasks via A2A
├── 🎯 Specialist agents focus on one domain
└── 🧵 Orchestrator synthesizes across all agents
```

### ❓ Why Separate Microservices?

```text
Each agent runs as an independent FastAPI service:
├── 📈 Independent scaling (search is used 10x more)
├── 🚀 Independent deployment (update one without restart)
├── 🛡️ Independent failure (one agent down ≠ system down)
└── 🌍 Language agnostic (A2A is HTTP — any language works)
```

### ❓ Why Gemini + Free Tier?

```text
⚡ gemini-flash-lite-latest → specialist agents (fast, cheap)
🧠 gemini-flash-latest      → orchestrator (smarter reasoning)

Free tier strategy:
├── ⚡ Flash Lite: fastest inference, minimal cost
├── 🧩 Tool calling: agents only call LLM when needed
└── 🔴 Caching: Redis caches repeated tool results
```

<br/>

---

## 📊 Project Status

| 🧩 Component | 🚦 Status | 🧪 Tests |
|:---|:---:|:---:|
| 🔎 Web Search Agent | ✅ Complete | 25/25 |
| 📊 Data Analysis Agent | 🚧 In Progress | — |
| 📄 Document Agent | 📋 Planned | — |
| 💻 Code Agent | 📋 Planned | — |
| 🗂️ Agent Registry | 📋 Planned | — |
| 🧭 Orchestrator | 📋 Planned | — |
| 🐳 Docker Compose | 📋 Planned | — |
| 🔭 OpenTelemetry | 📋 Planned | — |

<br/>

---

## 🤝 Contributing

This is an active portfolio project. Architecture decisions and protocol implementations follow the official specs:

- 🌐 [A2A Protocol Spec](https://github.com/google-a2a/A2A)
- 🧩 [MCP Specification](https://modelcontextprotocol.io)
- ✨ [Gemini API Docs](https://ai.google.dev/docs)

<br/>

---

## 📄 License

MIT License — see [LICENSE](./LICENSE) for details.

---

<div align="center">

### 🔥 Built with bleeding-edge AI protocols

`🌐 A2A` • `🧩 MCP` • `✨ Gemini` • `⚡ FastAPI` • `🕸️ LangGraph`

*The future of AI is agents that work together.* 🤖🤝🤖

</div>
