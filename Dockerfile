# Backend container — Python worker + FastAPI in a single async process.
# Web (Next.js) has its own Dockerfile under web/.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps (compiled wheels for asyncpg, scipy, etc. on slim images)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install -e .

# Copy source
COPY src/ ./src/
COPY scripts/ ./scripts/

EXPOSE 8000

# Entrypoint chosen by Railway via service config (see railway.json):
#   - worker: python -m src.runner.main
#   - api:    uvicorn src.api.main:app --host 0.0.0.0 --port $PORT
# Default to API for healthcheck purposes; the worker service overrides.
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
