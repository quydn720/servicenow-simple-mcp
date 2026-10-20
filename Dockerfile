# syntax=docker/dockerfile:1
# Remote OAuth broker image: non-root, read-only root filesystem friendly.
# Build: docker build -t servicenow-mcp-remote .
# Run:   see docs/deployment.md

FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md MANIFEST.in ./
RUN uv sync --locked --no-dev --extra remote --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --extra remote --no-editable

FROM python:3.13-slim
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin mcp \
    && mkdir -p /data && chown 10001:10001 /data && chmod 700 /data
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MCP_BIND_HOST=0.0.0.0 MCP_BIND_PORT=8000 MCP_STORAGE_DIR=/data \
    FASTMCP_CHECK_FOR_UPDATES=off FASTMCP_ENABLE_RICH_LOGGING=false
USER 10001:10001
WORKDIR /data
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status != 200)"]
ENTRYPOINT ["servicenow-mcp-remote"]
