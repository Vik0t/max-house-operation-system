#!/bin/sh
set -eu

# Stop the worker while its persisted conversation state is being replaced.
# Keep the MAX marker (so a reset does not replay old chat messages), but drop
# old watchers, roles, dialogs and house mappings.
docker compose stop bot >/dev/null
docker compose run --rm --no-deps --entrypoint python bot -c '
import json
from pathlib import Path

path = Path("/var/lib/dompuls-bot/state.json")
try:
    marker = json.loads(path.read_text()).get("marker")
except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
    marker = None
path.write_text(json.dumps({"marker": marker, "houses": {}, "watchers": {}, "conversations": {}, "dialogs": {}, "roles": {}}, ensure_ascii=False))
'
docker compose exec api python -m app.seed --reset
docker compose up -d bot >/dev/null
echo "Demo data reset complete: House A, House B, elevator history and initiative restored."
