# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy only what's needed to build the wheel for better cache reuse
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip build && python -m build --wheel --outdir /dist .


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    FORGEMILL_MCP_PORT=3030 \
    FORGEMILL_MCP_HOST=0.0.0.0

# Non-root user — match the Forgemill image's UID range for least-surprise
RUN groupadd --system --gid 1001 mcp \
    && useradd --system --uid 1001 --gid 1001 --home /home/mcp --shell /sbin/nologin mcp \
    && mkdir -p /home/mcp \
    && chown -R mcp:mcp /home/mcp

# Install the wheel built in the previous stage
COPY --from=build /dist/*.whl /tmp/
RUN pip install /tmp/*.whl && rm -f /tmp/*.whl

# Tiny tini-less init — but `python -m` is fine for our purposes (single proc)

USER mcp
WORKDIR /home/mcp

EXPOSE 3030

# Pure-Python healthcheck (no curl in the image)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket,sys; \
                   s=socket.socket(); s.settimeout(2); \
                   s.connect(('127.0.0.1', int(__import__('os').environ.get('FORGEMILL_MCP_PORT','3030')))); \
                   s.close()" || exit 1

ENTRYPOINT ["forgemill-mcp"]
