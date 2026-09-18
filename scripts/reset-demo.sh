#!/bin/sh
set -eu
docker compose exec api python -m app.seed --reset
echo "Demo data reset complete: House A, House B, elevator history and initiative restored."

