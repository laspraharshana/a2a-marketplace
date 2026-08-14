FROM python:3.12-slim

LABEL service="a2a-registry" version="1.0.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r a2a && useradd -r -g a2a -d /app -s /sbin/nologin a2a

WORKDIR /app

COPY pyproject.toml ./
RUN mkdir -p \
        shared \
        registry \
        agents/base agents/web_search agents/data_analysis \
        agents/document agents/code \
        orchestrator \
    && touch \
        shared/__init__.py \
        registry/__init__.py \
        agents/__init__.py \
        agents/base/__init__.py \
        agents/web_search/__init__.py \
        agents/data_analysis/__init__.py \
        agents/document/__init__.py \
        agents/code/__init__.py \
        orchestrator/__init__.py

# Registry has no optional deps — base install is enough
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

COPY shared/            ./shared/
COPY registry/          ./registry/
COPY agents/__init__.py ./agents/__init__.py

RUN chown -R a2a:a2a /app
USER a2a

EXPOSE 9000

HEALTHCHECK \
    --interval=15s \
    --timeout=5s \
    --start-period=20s \
    --retries=3 \
    CMD curl -f http://localhost:9000/health || exit 1

CMD exec uvicorn registry.main:app --host 0.0.0.0 --port ${PORT:-9000}