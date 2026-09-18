#!/bin/sh
set -eu
alembic upgrade head
python -m app.seed --if-empty
exec uvicorn app.main:app --host 0.0.0.0 --port "${API_PORT:-8000}"

