<div align="center">

# ⚡ A2A Multi-Agent Marketplace

### 🧠 A production-grade multi-agent system where AI agents **discover** 🔎, **negotiate** 🤝, and **collaborate** 🚀 using Google's Agent-to-Agent (A2A) protocol and Anthropic's Model Context Protocol (MCP).

<br/>

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Google Gemini](https://img.shields.io/badge/Gemini-Flash-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://ai.google.dev)
[![MCP](https://img.shields.io/badge/MCP-2.0-FF6B35?style=for-the-badge&logo=anthropic&logoColor=white)](https://modelcontextprotocol.io)
[![Docker](https://img.shields.io/badge/Docker-Native_WSL2-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)
[![GCP](https://img.shields.io/badge/GCP-Cloud_Run-4285F4?style=for-the-badge&logo=googlecloud&logoColor=white)](https://cloud.google.com/run)
[![CI/CD](https://img.shields.io/badge/CI/CD-GitHub_Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white)](.github/workflows/deploy.yml)
[![Tests](https://img.shields.io/badge/Tests-236%2F236_Passing-22C55E?style=for-the-badge&logo=pytest&logoColor=white)](./tests)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](./LICENSE)

<br/>

**[📖 Overview](#-overview)** · **[🏗️ Architecture](#️-architecture)** · **[🔌 Protocols](#-protocols)** · **[🤖 Agents](#-specialist-agents)** · **[⚡ Quick Start](#-quick-start)** · **[☁️ Cloud Deployment](#️-cloud-deployment)** · **[📡 API Reference](#-api-reference)** · **[🎬 Demo](#-demo-scenarios)**

</div>

<br/>

---

## 📖 Overview

> [!NOTE]
> This project implements two of the most important emerging protocols in the AI industry — side by side, in production form, running live on Google Cloud Run.

| Protocol | ⚙️ By | 🎯 Purpose |
|:---|:---|:---|
| 🌐 **A2A** — Agent-to-Agent | Google · April 2025 | Standardizes how AI agents **discover** and **communicate** with each other |
| 🧩 **MCP** — Model Context Protocol | Anthropic | Standardizes how agents **access tools**, resources, and APIs |

Instead of one monolithic AI trying to do everything, this system orchestrates a **marketplace of specialist agents** — each expert at one domain — that collaborate to solve complex, multi-step tasks.

```mermaid
flowchart LR
    U["👤 User\n'Research quantum computing companies in\nSingapore, analyze funding trends,\nand create a visualization'"] --> O

    subgraph Orchestrator["🧭 Orchestrator"]
        O["Discover agents → Decompose task →\nDelegate → Synthesize"]
    end

    O --> WS["🔎 WebSearch Agent\nfinds companies & news"]
    O --> DA["📊 DataAnalysis Agent\nprocesses funding data"]
    O --> DOC["📄 Document Agent\nextracts PDF reports"]
    O --> CODE["💻 Code Agent\ngenerates visualizations"]

    WS --> R["🧵 Synthesized Report"]
    DA --> R
    DOC --> R
    CODE --> R

    style U fill:#1e293b,stroke:#38bdf8,color:#f8fafc
    style Orchestrator fill:#0f172a,stroke:#818cf8,color:#f8fafc
    style R fill:#14532d,stroke:#22c55e,color:#f8fafc
```

<br/>

---

## 🏗️ Architecture

### 🐳 Local (Docker Compose)

```mermaid
flowchart TB
    subgraph Registry["🗂️ AGENT REGISTRY · :9000"]
        REG["FastAPI + PostgreSQL + Redis\nAgent Cards · Health Status · Capability Index"]
    end

    subgraph Orch["🧭 ORCHESTRATOR AGENT · :8000"]
        ORC["LangGraph + Gemini Flash\n\n1️⃣ Receive task  2️⃣ Query Registry  3️⃣ Decompose\n4️⃣ Delegate via A2A  5️⃣ Aggregate  6️⃣ Synthesize"]
    end

    Registry -- "HTTP Discovery" --> Orch

    subgraph Agents["Specialist Agents (A2A)"]
        direction LR
        WS["🔎 WebSearch\n:8001\n\nMCP tools:\nsearch_web\nget_news\nfetch_url"]
        DA["📊 DataAnalysis\n:8002\n\nMCP tools:\nrun_python\ncreate_chart\nstatistics"]
        DOC["📄 Document\n:8003\n\nMCP tools:\nread_pdf\nsummarize\nextract_entities"]
        CODE["💻 Code\n:8004\n\nMCP tools:\nanalyze_code\nexecute_code\nexplain_code"]
    end

    Orch -- "A2A" --> WS
    Orch -- "A2A" --> DA
    Orch -- "A2A" --> DOC
    Orch -- "A2A" --> CODE

    subgraph Infra["⚙️ INFRASTRUCTURE"]
        direction LR
        PG[("PostgreSQL :5432")]
        RD[("Redis :6379")]
        OT["OpenTelemetry"]
    end

    Agents --- Infra

    style Registry fill:#0f172a,stroke:#38bdf8,color:#f8fafc
    style Orch fill:#0f172a,stroke:#818cf8,color:#f8fafc
    style WS fill:#1e293b,stroke:#facc15,color:#f8fafc
    style DA fill:#1e293b,stroke:#facc15,color:#f8fafc
    style DOC fill:#1e293b,stroke:#facc15,color:#f8fafc
    style CODE fill:#1e293b,stroke:#facc15,color:#f8fafc
    style Infra fill:#1e293b,stroke:#64748b,color:#f8fafc
```

### ☁️ Production (GCP Cloud Run)

```mermaid
flowchart TB
    GH["👤 GitHub\ngit push main"] --> CI

    subgraph CI["🤖 GITHUB ACTIONS · CI/CD Pipeline"]
        CI1["▶ Run 236 unit tests"]
        CI2["▶ Build 6 images"]
        CI3["▶ Push to Artifact Registry"]
        CI4["▶ Deploy Registry → Agents → Orchestrator"]
        CI5["▶ Smoke tests"]
        CI1 --> CI2 --> CI3 --> CI4 --> CI5
    end

    CI -- "deploy" --> AR

    subgraph AR["📦 ARTIFACT REGISTRY"]
        ARI["asia-southeast1-docker.pkg.dev/*/a2a-marketplace/"]
    end

    AR -- "pull" --> CR

    subgraph CR["☁️ CLOUD RUN SERVICES"]
        direction LR
        S1["🗂️ a2a-registry\nmin=1 instance"]
        S2["🧭 a2a-orchestrator\nmin=0 · scale to zero"]
        S3["🔎 web-search-agent\nmin=0"]
        S4["📊 data-analysis-agent\nmin=0"]
        S5["📄 document-agent\nmin=0"]
        S6["💻 code-agent\nmin=0"]
    end

    CR --> DATA

    subgraph DATA["🔐 Data & Security Layer"]
        direction LR
        SQL[("🐘 Cloud SQL\nPostgreSQL 15\ndb-f1-micro")]
        SM["🔐 Secret Manager\n9 secrets"]
        WIF["🛡️ Workload Identity\nFederation"]
    end

    style CI fill:#0f172a,stroke:#38bdf8,color:#f8fafc
    style AR fill:#1e293b,stroke:#facc15,color:#f8fafc
    style CR fill:#0f172a,stroke:#22c55e,color:#f8fafc
    style DATA fill:#1e293b,stroke:#f87171,color:#f8fafc
```

### 📁 Directory Structure

```text
a2a-marketplace/
│
├── 📁 shared/                      # Shared across all services
│   ├── a2a_types.py                # A2A protocol Pydantic models
│   ├── config.py                   # Pydantic v2 settings
│   └── logging_config.py           # Structured logging (structlog)
│
├── 📁 agents/
│   ├── 📁 base/                    # Reusable A2A base class
│   │   └── a2a_server.py
│   │
│   ├── 📁 web_search/              # ✅ Complete
│   │   ├── tools.py                # search_web, get_news, fetch_url
│   │   ├── mcp_server.py           # MCPServer 2.0 tool definitions
│   │   ├── main.py                 # FastAPI A2A service
│   │   └── Dockerfile              # Production container
│   │
│   ├── 📁 data_analysis/           # ✅ pandas + matplotlib
│   ├── 📁 document/                # ✅ PDF + DOCX processing
│   └── 📁 code/                    # ✅ Code generation + execution
│
├── 📁 orchestrator/                # ✅ LangGraph orchestration
│   ├── a2a_client.py               # A2A protocol HTTP client
│   ├── task_decomposer.py          # LLM-powered task planning
│   ├── main.py                     # FastAPI service
│   └── Dockerfile
│
├── 📁 registry/                    # ✅ Agent discovery service
│   ├── models.py                   # Pydantic models
│   ├── database.py                 # Async asyncpg pool
│   ├── main.py                     # Registry FastAPI service
│   └── Dockerfile
│
├── 📁 tests/                       # ✅ 236 tests, all passing
│   ├── test_web_search_mcp.py      # 25 tests
│   ├── test_data_analysis.py       # 40 tests
│   ├── test_document.py            # 41 tests
│   ├── test_code.py                # 41 tests
│   ├── test_registry.py            # 33 tests
│   ├── test_orchestrator.py        # 32 tests
│   └── test_e2e.py                 # 24 E2E tests
│
├── 📁 deploy/                      # ☁️ Cloud Run configurations
│   └── cloudrun/                   # Service definitions
│
├── 📁 scripts/                     # 🛠️ Deployment automation
│   ├── setup_gcp.sh                # GCP infrastructure
│   ├── setup_secrets.sh            # Secret Manager
│   └── setup_workload_identity.sh  # GitHub Actions auth
│
├── 📁 .github/workflows/           # 🤖 CI/CD pipeline
│   └── deploy.yml                  # Test → Build → Deploy
│
├── 🐳 docker-compose.yml           # Full local system
├── 🐳 docker-compose.dev.yml       # Dev overrides (hot reload)
├── 📄 Makefile                     # Convenient commands
└── 📦 pyproject.toml               # Single dependency source
```

<br/>

---

## 🔌 Protocols

### 🧩 MCP — Model Context Protocol

```mermaid
sequenceDiagram
    participant G as ✨ Gemini LLM
    participant M as 🧩 MCP Tool Layer
    participant T as 🔧 Tool Execution

    G->>M: "I need to search the web"
    Note over M: search_web_tool(query, max=5)<br/>get_news_tool(topic, max=5)<br/>fetch_url_tool(url)
    M->>T: execute_mcp_tool(name, args)
    T->>T: Run actual tool logic
    T-->>M: Result string
    M-->>G: FunctionResponse
    G-->>G: 💬 Final synthesized text response
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

```mermaid
sequenceDiagram
    participant O as 🧭 Orchestrator
    participant W as 🔎 WebSearch Agent

    O->>W: GET /.well-known/agent.json
    W-->>O: 🪪 Agent Card

    O->>W: POST /a2a/tasks/send<br/>JSONRPCRequest { method: "tasks/send" }
    Note over W: 🔧 Agent runs tools<br/>✨ Gemini synthesizes
    W-->>O: JSONRPCResponse { status: "completed", artifacts: [...] }
```

Every agent serves an **Agent Card** at `/.well-known/agent.json` — a machine-readable manifest describing capabilities, skills, and authentication requirements. The orchestrator reads these cards to make intelligent delegation decisions.

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

<br/>

### 📊 Data Analysis Agent · `:8002` ✅

> Runs Python code, generates charts, and performs statistical analysis on structured data.

| 🛠️ Tool | 📋 Description |
|:---|:---|
| `run_python_code` | Execute Python in a sandboxed environment |
| `create_chart` | Generate matplotlib visualizations (bar, line, scatter, histogram, pie) |
| `statistical_analysis` | Descriptive stats: mean, median, std, percentiles, IQR |

<br/>

### 📄 Document Agent · `:8003` ✅

> Reads and extracts structured information from PDF, DOCX, and web URLs.

| 🛠️ Tool | 📋 Description |
|:---|:---|
| `extract_text` | Extract text from PDF, DOCX, TXT files, or web URLs |
| `summarize_document` | AI-powered summaries (concise, detailed, bullet, executive) |
| `extract_entities` | Extract emails, URLs, dates, names, organizations |

<br/>

### 💻 Code Agent · `:8004` ✅

> Analyzes, executes, and explains Python code with sandboxed execution.

| 🛠️ Tool | 📋 Description |
|:---|:---|
| `analyze_code` | AST-based analysis + complexity grading (A-F) via radon |
| `execute_code` | Sandboxed subprocess execution with timeout + memory limits |
| `explain_code` | AI-powered explanations with improvement suggestions |

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
git clone https://github.com/laspraharshana/a2a-marketplace.git
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
GOOGLE_API_KEY=your_gemini_api_key_here
AGENT_MODEL=gemini-flash-lite-latest
ORCHESTRATOR_MODEL=gemini-flash-latest
A2A_BEARER_TOKEN=your-secret-token-here
```

### 🐳 Run the Full System Locally

```bash
# Start all services with Docker Compose
make up

# Or manually:
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
# All unit tests (fast)
make test

# Full E2E tests (requires Docker stack running)
make test-e2e

# Check service health
make status

# Live demo
make demo
```

<br/>

---

## ☁️ Cloud Deployment

This project runs in production on **Google Cloud Platform** with fully automated CI/CD.

### 🏗️ GCP Architecture

| ☁️ Service | 🎯 Purpose | 💰 Cost |
|:---|:---|:---:|
| ☁️ Cloud Run | Serverless containers (6 services) | Free tier |
| 🐘 Cloud SQL | Managed PostgreSQL (db-f1-micro) | ~$7/mo |
| 📦 Artifact Registry | Docker image storage | ~$0.10/mo |
| 🔐 Secret Manager | API keys, DB passwords, tokens | Free tier |
| 🛡️ Workload Identity | Keyless GitHub Actions auth | Free |

**Total estimated cost: ~$7-8/month** (fully covered by $300 free credits for years)

### 🤖 Automated CI/CD Pipeline

Every push to `main` triggers:

```mermaid
flowchart TB
    A["📥 git push main"] --> B

    subgraph B["🤖 GitHub Actions Pipeline"]
        direction TB
        J1["🧪 Job 1 — Unit Tests (~3 min)\nSetup Python 3.12 → Install deps →\nRun 236 tests → Upload results"]
        J2["📦 Job 2 — Build & Push (~8 min)\nAuth via Workload Identity →\nBuild 6 images in parallel → Push to AR"]
        J3["☁️ Job 3 — Deploy (~5 min)\nDeploy Registry → 4 Agents →\nOrchestrator → Smoke tests"]
        J1 -- "only if tests pass" --> J2 --> J3
    end

    B --> C["🚀 Live on Cloud Run URLs\n~16 minutes total"]

    style B fill:#0f172a,stroke:#818cf8,color:#f8fafc
    style C fill:#14532d,stroke:#22c55e,color:#f8fafc
```

### 🚀 One-Time Setup

```bash
# 1. Install and initialize gcloud
curl https://sdk.cloud.google.com | bash
gcloud init

# 2. Run infrastructure setup
./scripts/setup_gcp.sh

# 3. Load secrets from .env
./scripts/setup_secrets.sh

# 4. Configure GitHub Actions auth
./scripts/setup_workload_identity.sh

# 5. Add printed values to GitHub Secrets:
# https://github.com/laspraharshana/a2a-marketplace/settings/secrets/actions
```

### 📊 Cloud Run Dashboard

**View live services:**
```
https://console.cloud.google.com/run?project=a2a-marketplace
```

**Check service status:**
```bash
# All Cloud Run services
gcloud run services list \
    --region=asia-southeast1 \
    --project=a2a-marketplace

# Or use Make target
make gcp-status

# Get all URLs
make gcp-urls
```

### 🎬 Live GCP Demo

```bash
# Live demo against production
make gcp-demo

# Or manually
ORCH_URL=$(gcloud run services describe a2a-orchestrator \
    --region=asia-southeast1 \
    --project=a2a-marketplace \
    --format="value(status.url)")

curl -X POST $ORCH_URL/orchestrate \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $BEARER_TOKEN" \
    -d '{"query": "Search for top 3 AI companies in Singapore"}' \
    | python3 -m json.tool
```

### 🛡️ Security Features

- **🔐 Workload Identity Federation** — no service account keys stored in GitHub
- **🔒 Secret Manager** — all API keys and passwords encrypted at rest
- **🚫 Private agents** — specialist agents require Bearer token (no public access)
- **🌐 Public orchestrator + registry** — only entry points exposed
- **🛡️ Cloud SQL private connection** — via Cloud SQL Unix socket
- **⏱️ Automatic scaling** — agents scale to zero when idle

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

### 🔄 Task State Machine

```mermaid
stateDiagram-v2
    [*] --> submitted
    submitted --> working
    working --> completed
    working --> input_required : input-required
    input_required --> working
    working --> failed
    working --> canceled
    completed --> [*]
    failed --> [*]
    canceled --> [*]

    completed : completed ✅
    failed : failed ❌
    canceled : canceled 🚫
```

<br/>

---

## 🎬 Demo Scenarios

### 1️⃣ Market Research 📈

```bash
curl -X POST http://localhost:8000/orchestrate \
  -H "Authorization: Bearer your-token" \
  -d '{
    "query": "Research quantum computing companies in Singapore,
             find their funding data, and summarize the landscape"
  }'
```

**Orchestrator delegates:** 🔎 WebSearch Agent finds companies → 📊 DataAnalysis Agent processes funding data → 🧵 Synthesizes comprehensive report.

<br/>

### 2️⃣ Code Analysis 💻

```bash
curl -X POST http://localhost:8000/orchestrate \
  -H "Authorization: Bearer your-token" \
  -d '{
    "query": "Explain what this Python code does and analyze complexity:
              def bubble_sort(arr): ..."
  }'
```

**Orchestrator delegates:** 💻 Code Agent analyzes AST + complexity → 💻 Code Agent generates explanation → 🧵 Synthesizes complete analysis.

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
> **Actual response (live from Cloud Run):**
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
| Search | 🔎 ddgs | 9+ | Free web search fallback |
| Validation | 🛡️ Pydantic | v2 | Type safety throughout |
| Logging | 📝 structlog | 24+ | Structured JSON logging |
| Testing | 🧪 pytest | 8.2 | 236 tests, async support |
| Container | 🐳 Docker | 29.1.3 | Microservice deployment |
| Cloud | ☁️ Google Cloud Run | Latest | Serverless containers |
| CI/CD | 🤖 GitHub Actions | v4 | Automated test + deploy |
| Auth | 🛡️ Workload Identity | Latest | Keyless GCP authentication |

<br/>

---

## 🧠 Key Design Decisions

### ❓ Why A2A + MCP Together?

```mermaid
flowchart LR
    Q1["🧩 MCP answers:\n'How does an agent USE tools?'"]
    Q2["🌐 A2A answers:\n'How does an agent TALK to\nother agents?'"]
    Q1 --> R["Together:\nAgent discovers tools via MCP →\nAgent delegates sub-tasks via A2A →\nSpecialists focus on one domain →\nOrchestrator synthesizes across all"]
    Q2 --> R

    style Q1 fill:#1e293b,stroke:#facc15,color:#f8fafc
    style Q2 fill:#1e293b,stroke:#38bdf8,color:#f8fafc
    style R fill:#0f172a,stroke:#818cf8,color:#f8fafc
```

### ❓ Why Cloud Run + Serverless?

Cloud Run with `min-instances=0` gives:
- 💰 **Pay only when handling requests**
- 📈 **Auto-scales up** under load
- 🌍 **Global by default** (asia-southeast1 for latency)
- 🚀 **No cluster management** overhead
- 🔐 **Managed TLS, secrets, IAM**

### ❓ Why Separate Microservices?

Each agent runs as an independent FastAPI service:
- 📈 **Independent scaling** — search used 10x more than others
- 🚀 **Independent deployment** — update one without restarting the rest
- 🛡️ **Independent failure** — one agent down ≠ system down
- 🌍 **Language agnostic** — A2A is plain HTTP

<br/>

---

## 📊 Project Status

| 🧩 Component | 🚦 Status | 🧪 Tests | ☁️ GCP |
|:---|:---:|:---:|:---:|
| 🔎 Web Search Agent | ✅ Complete | 25/25 | ✅ Deployed |
| 📊 Data Analysis Agent | ✅ Complete | 40/40 | ✅ Deployed |
| 📄 Document Agent | ✅ Complete | 41/41 | ✅ Deployed |
| 💻 Code Agent | ✅ Complete | 41/41 | ✅ Deployed |
| 🗂️ Agent Registry | ✅ Complete | 33/33 | ✅ Deployed |
| 🧭 Orchestrator | ✅ Complete | 32/32 | ✅ Deployed |
| 🐳 Docker Compose | ✅ Complete | — | — |
| 🌐 E2E Tests | ✅ Complete | 24/24 | ✅ Passing |
| 🤖 GitHub Actions | ✅ Complete | — | ✅ Live |

**Total: 236 tests passing · 6 services deployed on GCP Cloud Run**

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

`🌐 A2A` · `🧩 MCP` · `✨ Gemini` · `⚡ FastAPI` · `🕸️ LangGraph` · `☁️ Cloud Run`

*The future of AI is agents that work together.* 🤖🤝🤖

**⭐ Star this repo if you find it useful!**

</div>
