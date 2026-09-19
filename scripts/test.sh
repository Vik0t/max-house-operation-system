#!/bin/sh
set -eu
docker compose build api bot web
docker compose run --rm --no-deps api pytest
