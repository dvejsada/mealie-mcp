FROM python:3.14-slim

# No .pyc files, unbuffered stdout/stderr for clean container logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so they cache independently of source changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY mealie_mcp ./mealie_mcp
COPY main.py ./

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Server defaults (override via environment / compose).
ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    MCP_PATH=/mcp

EXPOSE 8000

# Liveness probe hits the unauthenticated /healthz route.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
url='http://127.0.0.1:%s/healthz' % os.getenv('MCP_PORT','8000'); \
sys.exit(0 if urllib.request.urlopen(url, timeout=4).status == 200 else 1)"

CMD ["python", "-m", "mealie_mcp"]
