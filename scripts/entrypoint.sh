#!/usr/bin/env sh
# Unified container entrypoint. Same image runs three roles, selected by
# the RUN_MODE env var so Railway can split worker / api / one-shot migrate
# into separate services that share one Docker image.
#
# Modes:
#   api      (default) — uvicorn FastAPI on $PORT, healthcheck /health
#   worker             — async runner (ingestion + strategies + fills)
#   migrate            — apply schema.sql once and exit
#
# DB readiness:
#   - api / worker wait up to DB_WAIT_SECS (default 120) for DATABASE_URL
#     to accept a connection before starting work
#   - migrate runs --wait by default
#
# Logs go straight to stdout (PYTHONUNBUFFERED=1 set in Dockerfile).

set -e

MODE="${RUN_MODE:-api}"
PORT="${PORT:-8000}"

echo "[entrypoint] starting mode=$MODE port=$PORT"

# Wait for DB before non-migrate roles, but tolerate a missing DATABASE_URL
# (e.g. local dev) by skipping the wait — the runner's tenacity loop and
# the API's lazy pool init will handle it once a value appears.
if [ -n "${DATABASE_URL:-}" ] && [ "$MODE" != "migrate" ]; then
    echo "[entrypoint] waiting for DB..."
    python -m scripts.bootstrap_db --check || \
        python -m scripts.bootstrap_db --wait || \
        echo "[entrypoint] DB still unreachable; continuing anyway, lazy init will retry"
fi

case "$MODE" in
    api)
        exec uvicorn src.api.main:app --host 0.0.0.0 --port "$PORT"
        ;;
    worker)
        exec python -m src.runner.main
        ;;
    migrate)
        exec python -m scripts.bootstrap_db --wait
        ;;
    *)
        echo "[entrypoint] unknown RUN_MODE=$MODE (expected api|worker|migrate)"
        exit 1
        ;;
esac
