#!/bin/sh
set -eu

SOURCE_ENV="${1:-.env}"
TARGET_ENV="${2:-.env.prod}"
API_HOST="${API_HOST:-104.252.77.141.nip.io}"
PAGES_URL="${PAGES_URL:-https://apaww.github.io/dom.sreda.io/}"
CORS_ORIGIN="${CORS_ORIGIN:-https://apaww.github.io}"

if [ ! -f "$SOURCE_ENV" ]; then
  echo "Source env file not found: $SOURCE_ENV" >&2
  exit 1
fi

MAX_BOT_TOKEN="$(sed -n 's/^MAX_BOT_TOKEN=//p' "$SOURCE_ENV" | tail -n 1)"
if [ -z "$MAX_BOT_TOKEN" ]; then
  echo "MAX_BOT_TOKEN is missing in $SOURCE_ENV" >&2
  exit 1
fi

POSTGRES_PASSWORD="$(openssl rand -hex 24)"
MAX_WEBHOOK_SECRET="$(openssl rand -hex 32)"

umask 077
{
  printf 'API_HOST=%s\n' "$API_HOST"
  printf 'POSTGRES_PASSWORD=%s\n' "$POSTGRES_PASSWORD"
  printf 'CORS_ORIGINS=%s\n' "$CORS_ORIGIN"
  printf 'API_PORT=8000\n'
  printf 'MAX_MODE=real\n'
  printf 'MAX_BOT_TOKEN=%s\n' "$MAX_BOT_TOKEN"
  printf 'MAX_WEBHOOK_SECRET=%s\n' "$MAX_WEBHOOK_SECRET"
  printf 'MAX_API_BASE=https://platform-api2.max.ru\n'
  printf 'MAX_CA_BUNDLE=/app/certs/russian-trusted-ca.pem\n'
  printf 'MAX_POLL_TIMEOUT=30\n'
  printf 'MAX_POLL_STATE_PATH=/var/lib/dompuls-bot/state.json\n'
  printf 'MAX_DEFAULT_HOUSE_ID=demo-house-a\n'
  printf 'MAX_MINIAPP_URL=%s\n' "$PAGES_URL"
  printf 'MAX_INIT_DATA_MAX_AGE_SECONDS=3600\n'
  printf 'LLM_MODE=deterministic\n'
  printf 'LOG_LEVEL=INFO\n'
} > "$TARGET_ENV"

chmod 600 "$TARGET_ENV"
printf 'Created %s with restricted permissions.\n' "$TARGET_ENV"
