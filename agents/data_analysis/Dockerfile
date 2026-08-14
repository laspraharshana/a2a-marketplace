FROM python:3.12-slim

LABEL service="a2a-data-analysis-agent" version="1.0.0"

# numpy/pandas/matplotlib build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
        curl \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r a2a && useradd -r -g a2a -d /app -s /sbin/nologin a2a

WORKDIR /app

# ← FIXED: force matplotlib Agg backend before any import
ENV MPLBACKEND=Agg

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

# ← FIXED: install data-analysis optional deps
# (pandas, matplotlib, numpy, scipy)
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[data-analysis]"

COPY shared/                ./shared/
COPY agents/__init__.py     ./agents/__init__.py
COPY agents/base/           ./agents/base/
COPY agents/data_analysis/  ./agents/data_analysis/

RUN chown -R a2a:a2a /app
USER a2a

EXPOSE 8002

HEALTHCHECK \
    --interval=15s \
    --timeout=5s \
    --start-period=30s \
    --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

CMD exec uvicorn agents.data_analysis.main:app --host 0.0.0.0 --port ${PORT:-8002}