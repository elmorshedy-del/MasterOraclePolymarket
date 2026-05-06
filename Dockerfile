# Backend container — same image runs the FastAPI service, the async
# worker, or a one-shot DB migrate. Role selected by RUN_MODE env var so
# Railway can split the deployment into multiple services that share one
# build cache. See scripts/entrypoint.sh.
#
# Web (Next.js) has its own Dockerfile under web/.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps for compiled wheels (asyncpg, scipy, lxml-style libs).
# tini is a tiny init that reaps zombies + forwards SIGTERM cleanly so
# Railway's deploy/restart cycle doesn't leak processes.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better layer caching. We support both
# pyproject.toml (preferred) and requirements.txt (Nixpacks fallback).
COPY pyproject.toml ./
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel \
    && (pip install -e . || pip install -r requirements.txt)

# Copy source after deps so dep changes don't bust the source layer.
COPY src/ ./src/
COPY scripts/ ./scripts/

# Default port for healthcheck. Railway will override via $PORT.
EXPOSE 8000

# tini → entrypoint.sh dispatcher. The dispatcher reads RUN_MODE
# (api | worker | migrate) and execs the right command. Defaults to api
# so a Railway service that forgets RUN_MODE still becomes a healthy
# /health endpoint instead of a crashlooping worker.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "/app/scripts/entrypoint.sh"]
