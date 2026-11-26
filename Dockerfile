# syntax=docker/dockerfile:1.7
# ForgeAI production image: the full Streamlit app (build · results · chat).
# One image, two profiles: FORGE_UI_CONFIG=configs/cloud_groq.toml (hosted API, default)
#                          FORGE_UI_CONFIG=configs/docker_ollama.toml (Ollama sidecar, see docker-compose.yml)

# ---------- builder: resolve and install dependencies into an isolated venv ----------
FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY deploy/streamlit/requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt

# ---------- runtime: slim, non-root, health-checked ----------
FROM python:3.11-slim AS runtime
LABEL org.opencontainers.image.title="ForgeAI (Agent Smith)" \
      org.opencontainers.image.description="The agent that builds agents: brief + documents -> tested RAG agent + honest report" \
      org.opencontainers.image.source="https://github.com/DeeptanshNagar/Agent_Smith_ByOceanAI"

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FORGE_UI_CONFIG=configs/cloud_groq.toml \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin forge
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
RUN chown forge:forge /app
COPY --chown=forge:forge . .
# writable state lives in volumes in production (runs, LLM cache, index cache)
RUN mkdir -p runs .forge_cache .forge_index && chown forge:forge runs .forge_cache .forge_index

USER forge
EXPOSE 8501
VOLUME ["/app/runs", "/app/.forge_cache"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)" || exit 1

CMD ["streamlit", "run", "forge/runner/app_ui.py"]
