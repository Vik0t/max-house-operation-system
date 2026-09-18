# MAX integration setup

The adapter follows the current MAX contract:

- base URL: `https://platform-api2.max.ru`;
- bot token only in `Authorization` header;
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
MAX_CA_BUNDLE=/run/secrets/russian-trusted-ca.pem
MAX_WEBHOOK_SECRET=<5-256 chars: A-Z, a-z, 0-9, underscore, hyphen>
```

MAX currently requires the Russian Trusted Root/Sub CA in the client trust chain. Obtain it from the official Госуслуги certificate page, verify its source/fingerprint, create a PEM bundle and mount it read-only into the API container. Do not use `verify=false` or `curl -k` with the token.

## Verification

```bash
curl http://localhost:8000/integrations/max/status
curl http://localhost:8000/integrations/max/chats/<chat_id>/permissions
```

The UI displays `REAL · CONNECTED` only after strict-TLS `GET /me` succeeds. `REAL · CONFIGURED` means credentials/config exist but connectivity has not been verified.

## Webhook subscription

Deploy `/integrations/max/webhook` behind public HTTPS on port 443, set a strong `MAX_WEBHOOK_SECRET`, then create the subscription through the official MAX API for `message_created`, `message_callback`, `bot_added` and `bot_started`. The handler acknowledges duplicates without creating a second Signal.

Before the group demo, add the bot as admin and confirm `has_read_all_messages=true`. Without it, use direct bot/share-to-bot input and describe that limitation honestly.
