# Makefile — A2A Multi-Agent Marketplace
# Usage: make <target>
# Requires: make, docker, docker compose, python3

.PHONY: help install test test-unit test-integration test-e2e \
        build up down restart logs clean format lint \
        services-start services-stop db-start redis-start \
        status demo

# ── Colors ────────────────────────────────────────────────────
CYAN    := \033[0;36m
GREEN   := \033[0;32m
YELLOW  := \033[0;33m
RED     := \033[0;31m
RESET   := \033[0m
BOLD    := \033[1m

# ── Config ────────────────────────────────────────────────────
COMPOSE         := docker compose
COMPOSE_DEV     := docker compose -f docker-compose.yml \
                   -f docker-compose.dev.yml
PYTHON          := python3
PYTEST          := pytest
VENV            := .venv
PIP             := $(VENV)/bin/pip

# ══════════════════════════════════════════════════════════════
# HELP
# ══════════════════════════════════════════════════════════════

help: ## Show this help message
	@echo ""
	@echo "$(BOLD)A2A Multi-Agent Marketplace$(RESET)"
	@echo "$(CYAN)══════════════════════════════════════════$(RESET)"
	@echo ""
	@echo "$(BOLD)Setup:$(RESET)"
	@grep -E '^(install|db-start|redis-start|services-start).*:.*##' \
		$(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*##"}; {printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(BOLD)Testing:$(RESET)"
	@grep -E '^test.*:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*##"}; {printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(BOLD)Docker:$(RESET)"
	@grep -E '^(build|up|down|restart|logs|clean).*:.*##' \
		$(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*##"}; {printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(BOLD)Development:$(RESET)"
	@grep -E '^(format|lint|status|demo).*:.*##' \
		$(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*##"}; {printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2}'
	@echo ""


# ══════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════

install: ## Install all dependencies in virtual environment
	@echo "$(CYAN)► Installing dependencies...$(RESET)"
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[web-search,data-analysis,document,code,dev]"
	@echo "$(GREEN)✓ Dependencies installed$(RESET)"

db-start: ## Start PostgreSQL (WSL2)
	@echo "$(CYAN)► Starting PostgreSQL...$(RESET)"
	sudo service postgresql start
	@sleep 2
	@echo "$(GREEN)✓ PostgreSQL started$(RESET)"

db-setup: db-start ## Create database and user
	@echo "$(CYAN)► Setting up database...$(RESET)"
	sudo -u postgres psql -c \
		"CREATE USER a2a WITH PASSWORD 'a2a_password';" 2>/dev/null || true
	sudo -u postgres psql -c \
		"CREATE DATABASE a2a_marketplace OWNER a2a;" 2>/dev/null || true
	sudo -u postgres psql -c \
		"GRANT ALL PRIVILEGES ON DATABASE a2a_marketplace TO a2a;" 2>/dev/null || true
	@echo "$(GREEN)✓ Database ready$(RESET)"

redis-start: ## Start Redis (WSL2)
	@echo "$(CYAN)► Starting Redis...$(RESET)"
	redis-server --daemonize yes 2>/dev/null || true
	@sleep 1
	@echo "$(GREEN)✓ Redis started$(RESET)"

services-start: db-start redis-start ## Start host services (PostgreSQL + Redis)
	@echo "$(GREEN)✓ Host services ready$(RESET)"

services-stop: ## Stop host services
	@echo "$(CYAN)► Stopping host services...$(RESET)"
	sudo service postgresql stop 2>/dev/null || true
	redis-cli shutdown 2>/dev/null || true
	@echo "$(GREEN)✓ Host services stopped$(RESET)"


# ══════════════════════════════════════════════════════════════
# TESTING
# ══════════════════════════════════════════════════════════════

test: ## Run all unit tests (no integration)
	@echo "$(CYAN)► Running unit tests...$(RESET)"
	$(PYTEST) tests/ -m "not integration" -v --tb=short
	@echo "$(GREEN)✓ Unit tests complete$(RESET)"

test-unit: test ## Alias for 'make test'

test-web-search: ## Run Web Search Agent tests only
	@echo "$(CYAN)► Testing Web Search Agent...$(RESET)"
	$(PYTEST) tests/test_web_search_mcp.py -v --tb=short

test-data-analysis: ## Run Data Analysis Agent tests only
	@echo "$(CYAN)► Testing Data Analysis Agent...$(RESET)"
	$(PYTEST) tests/test_data_analysis.py -v --tb=short

test-document: ## Run Document Agent tests only
	@echo "$(CYAN)► Testing Document Agent...$(RESET)"
	$(PYTEST) tests/test_document.py -v --tb=short

test-code: ## Run Code Agent tests only
	@echo "$(CYAN)► Testing Code Agent...$(RESET)"
	$(PYTEST) tests/test_code.py -v --tb=short

test-registry: ## Run Registry tests only
	@echo "$(CYAN)► Testing Registry...$(RESET)"
	$(PYTEST) tests/test_registry.py -v --tb=short

test-orchestrator: ## Run Orchestrator unit tests only
	@echo "$(CYAN)► Testing Orchestrator...$(RESET)"
	$(PYTEST) tests/test_orchestrator.py -m "not integration" \
		-v --tb=short

test-integration: services-start ## Run integration tests (needs PostgreSQL)
	@echo "$(CYAN)► Running integration tests...$(RESET)"
	$(PYTEST) tests/ -m "integration" -v --tb=short \
		-k "not e2e"
	@echo "$(GREEN)✓ Integration tests complete$(RESET)"

test-e2e: services-start up-wait ## Run E2E tests (needs full Docker stack)
	@echo "$(CYAN)► Running E2E tests...$(RESET)"
	@echo "$(YELLOW)  Waiting for services to stabilize...$(RESET)"
	@sleep 15
	$(PYTEST) tests/test_e2e.py -m "integration" \
		-v --tb=short -s
	@echo "$(GREEN)✓ E2E tests complete$(RESET)"

test-all: services-start ## Run ALL tests including integration + E2E
	@echo "$(CYAN)► Running full test suite...$(RESET)"
	$(PYTEST) tests/ -v --tb=short
	@echo "$(GREEN)✓ All tests complete$(RESET)"

test-coverage: ## Run tests with coverage report
	@echo "$(CYAN)► Running tests with coverage...$(RESET)"
	$(PYTEST) tests/ -m "not integration" \
		--cov=agents --cov=registry --cov=orchestrator --cov=shared \
		--cov-report=html --cov-report=term-missing \
		--tb=short
	@echo "$(GREEN)✓ Coverage report at htmlcov/index.html$(RESET)"


# ══════════════════════════════════════════════════════════════
# DOCKER
# ══════════════════════════════════════════════════════════════

build: ## Build all Docker images
	@echo "$(CYAN)► Building Docker images...$(RESET)"
	$(COMPOSE) build --parallel
	@echo "$(GREEN)✓ Images built$(RESET)"

build-no-cache: ## Build all Docker images (no cache)
	@echo "$(CYAN)► Building Docker images (no cache)...$(RESET)"
	$(COMPOSE) build --no-cache --parallel
	@echo "$(GREEN)✓ Images built$(RESET)"

up: services-start ## Start full system (build if needed)
	@echo "$(CYAN)► Starting A2A Marketplace...$(RESET)"
	$(COMPOSE) up -d --build
	@echo "$(GREEN)✓ System starting — run 'make logs' to follow$(RESET)"
	@echo "$(YELLOW)  Use 'make status' to check service health$(RESET)"

up-wait: up ## Start system and wait for all services healthy
	@echo "$(CYAN)► Waiting for all services to be healthy...$(RESET)"
	@timeout 120 bash -c '\
		until docker compose ps | grep -v "healthy" | \
		      grep -qE "(registry|agent|orchestrator)"; do \
			sleep 3; \
		done; \
	' || true
	@echo "$(GREEN)✓ Services ready$(RESET)"

up-dev: services-start ## Start in development mode (hot reload)
	@echo "$(CYAN)► Starting in development mode...$(RESET)"
	$(COMPOSE_DEV) up -d --build
	@echo "$(GREEN)✓ Dev system starting with hot reload$(RESET)"

down: ## Stop all containers
	@echo "$(CYAN)► Stopping containers...$(RESET)"
	$(COMPOSE) down
	@echo "$(GREEN)✓ Containers stopped$(RESET)"

down-volumes: ## Stop containers and remove volumes
	@echo "$(RED)► Removing containers and volumes...$(RESET)"
	$(COMPOSE) down -v
	@echo "$(GREEN)✓ Done$(RESET)"

restart: down up ## Restart all containers

restart-agent: ## Restart a single agent (usage: make restart-agent SERVICE=web-search-agent)
	@echo "$(CYAN)► Restarting $(SERVICE)...$(RESET)"
	$(COMPOSE) restart $(SERVICE)
	@echo "$(GREEN)✓ $(SERVICE) restarted$(RESET)"

logs: ## Follow logs for all services
	$(COMPOSE) logs -f

logs-registry: ## Follow registry logs
	$(COMPOSE) logs -f registry

logs-web-search: ## Follow web search agent logs
	$(COMPOSE) logs -f web-search-agent

logs-orchestrator: ## Follow orchestrator logs
	$(COMPOSE) logs -f orchestrator

clean: down ## Remove containers and built images
	@echo "$(CYAN)► Cleaning up Docker resources...$(RESET)"
	$(COMPOSE) rm -f
	docker rmi $$(docker images | grep "a2a-" | \
		awk '{print $$3}') 2>/dev/null || true
	@echo "$(GREEN)✓ Cleaned$(RESET)"


# ══════════════════════════════════════════════════════════════
# DEVELOPMENT
# ══════════════════════════════════════════════════════════════

format: ## Format code with ruff
	@echo "$(CYAN)► Formatting code...$(RESET)"
	$(VENV)/bin/ruff format .
	@echo "$(GREEN)✓ Code formatted$(RESET)"

lint: ## Lint code with ruff
	@echo "$(CYAN)► Linting code...$(RESET)"
	$(VENV)/bin/ruff check .
	@echo "$(GREEN)✓ Lint complete$(RESET)"

status: ## Show health status of all services
	@echo ""
	@echo "$(BOLD)Service Health Status$(RESET)"
	@echo "$(CYAN)══════════════════════════════════════════$(RESET)"
	@check_service() { \
		name=$$1; url=$$2; \
		response=$$(curl -s -o /dev/null -w "%{http_code}" \
			--max-time 3 $$url/health 2>/dev/null); \
		if [ "$$response" = "200" ]; then \
			echo "  $(GREEN)✓$(RESET) $$name"; \
		else \
			echo "  $(RED)✗$(RESET) $$name ($$response)"; \
		fi; \
	}; \
	check_service "Registry        :9000" "http://localhost:9000"; \
	check_service "Orchestrator    :8000" "http://localhost:8000"; \
	check_service "Web Search      :8001" "http://localhost:8001"; \
	check_service "Data Analysis   :8002" "http://localhost:8002"; \
	check_service "Document Agent  :8003" "http://localhost:8003"; \
	check_service "Code Agent      :8004" "http://localhost:8004"
	@echo ""

demo: ## Run a live demo query through the orchestrator
	@echo ""
	@echo "$(BOLD)Live Demo — A2A Multi-Agent Marketplace$(RESET)"
	@echo "$(CYAN)══════════════════════════════════════════$(RESET)"
	@echo "$(YELLOW)Query: Search for top AI companies in Singapore$(RESET)"
	@echo ""
	@curl -s -X POST http://localhost:8000/orchestrate \
		-H "Content-Type: application/json" \
		-H "Authorization: Bearer $${A2A_BEARER_TOKEN:-dev-bearer-token}" \
		-d '{"query": "Search for top 3 AI companies in Singapore and give a brief summary"}' \
		| $(PYTHON) -m json.tool
	@echo ""

demo-search: ## Demo direct Web Search Agent call
	@echo "$(CYAN)► Direct Web Search Agent call...$(RESET)"
	@curl -s -X POST http://localhost:8001/a2a/tasks/send \
		-H "Content-Type: application/json" \
		-H "Authorization: Bearer $${A2A_BEARER_TOKEN:-dev-bearer-token}" \
		-d '{ \
			"jsonrpc":"2.0","id":"demo-001","method":"tasks/send", \
			"params":{"id":"task-demo-001","message":{"role":"user", \
			"parts":[{"type":"text","text":"Search for Python programming language"}]}} \
		}' | $(PYTHON) -m json.tool

demo-code: ## Demo direct Code Agent call
	@echo "$(CYAN)► Direct Code Agent call...$(RESET)"
	@curl -s -X POST http://localhost:8004/a2a/tasks/send \
		-H "Content-Type: application/json" \
		-H "Authorization: Bearer $${A2A_BEARER_TOKEN:-dev-bearer-token}" \
		-d '{ \
			"jsonrpc":"2.0","id":"demo-002","method":"tasks/send", \
			"params":{"id":"task-demo-002","message":{"role":"user", \
			"parts":[{"type":"text","text":"Explain def add(a,b): return a+b"}]}} \
		}' | $(PYTHON) -m json.tool

registry-list: ## List all registered agents in registry
	@echo "$(CYAN)► Registered agents:$(RESET)"
	@curl -s http://localhost:9000/agents | $(PYTHON) -m json.tool