# MAX integration setup

The adapter follows the current MAX contract:

- base URL: `https://platform-api2.max.ru`;
- bot token only in `Authorization` header;
- local/hackathon receive path: `GET /updates` Long Polling in a dedicated `bot` container;
- webhook: `POST /subscriptions`, HTTPS port 443;
- webhook authenticity: `X-Max-Bot-Api-Secret`;
- group permission check: `GET /chats/{chatId}/members/me` and `read_all_messages`;
- notification: `POST /messages?chat_id=...` or `user_id=...`;
- bounded retry for timeout, 429 and 5xx.

## Local configuration

```dotenv
MAX_MODE=real
MAX_BOT_TOKEN=<secret>
MAX_API_BASE=https://platform-api2.max.ru
MAX_CA_BUNDLE=/app/certs/russian-trusted-ca.pem
MAX_POLL_TIMEOUT=30
MAX_DEFAULT_HOUSE_ID=demo-house-a
MAX_MINIAPP_URL=http://localhost:3000
```

MAX currently requires the Russian Trusted Root/Sub CA in the client trust chain. The repository contains the public official certificates in `certs/russian-trusted-ca.pem`; the adapter scopes that bundle to MAX requests only and does not alter the OS trust store. Verified SHA-256 fingerprints:

- Root: `D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31`
- Sub: `BB:BD:E2:10:3E:79:0B:99:9E:C6:2B:D0:3C:F6:25:A5:A2:E7:C3:16:E1:0A:FE:6A:49:0E:ED:EA:D8:B3:FD:9B`

Do not use `verify=false` or `curl -k` with the token.

## Verification

```bash
curl http://localhost:8000/integrations/max/status
curl http://localhost:8000/integrations/max/chats/<chat_id>/permissions
docker compose logs --tail=100 bot
```

The UI displays `REAL · BOT ONLINE` only after strict-TLS `GET /me` succeeds and the marker file proves that the polling worker completed a request recently. `REAL · CONFIGURED` means credentials/config exist but the receiver is not currently verified as active.

## Long Polling (hackathon/dev)

`docker compose up --build -d` starts the worker automatically. It verifies the token with `GET /me`, refuses to start polling if a webhook subscription exists, then requests `message_created` updates and persists the returned marker in the `dompuls_bot_state` volume. Signal `external_id` is the MAX message ID, so replay cannot create a duplicate.

Supported commands:

- `/start` and `/help` — instructions;
- `/status` — current House State metrics;
- `/house_a` and `/house_b` — config-driven house switch for the current dialog/chat.

Any other text enters the real Signal → Issue/Initiative pipeline. The response reports the created/clustered entity, state, confirmations and recurrence. According to MAX documentation, Long Polling is for development and testing, not production.

The mini-app refreshes House State every five seconds, so a Signal received from MAX becomes visible without reloading the page.

## Webhook subscription

Deploy `/integrations/max/webhook` behind public HTTPS on port 443, set a strong `MAX_WEBHOOK_SECRET`, then create the subscription through the official MAX API for `message_created`, `message_callback`, `bot_added` and `bot_started`. The handler acknowledges duplicates without creating a second Signal.

An active webhook subscription disables Long Polling. Stop the `bot` worker when moving to webhooks.

Before the group demo, add the bot as admin and confirm `has_read_all_messages=true`. Without it, use direct bot/share-to-bot input and describe that limitation honestly.
