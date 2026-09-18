#!/bin/sh
set -eu
docker compose build api web
docker compose run --rm --no-deps api pytest

