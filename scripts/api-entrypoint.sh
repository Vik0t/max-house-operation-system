#!/bin/sh
set -eu
alembic upgrade head
if [ "${SEED_DEMO_ON_STARTUP:-true}" != "false" ]; then
  python -m app.seed --if-empty
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${API_PORT:-8000}"
