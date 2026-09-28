# API contract

Interactive schema is available at `/docs`; OpenAPI JSON is at `/openapi.json`.

## House / Asset

- `GET /houses`
- `GET /houses/{id}`
- `GET /houses/{id}/state?viewer_id=...&role=resident|representative|uk|executor` — состояние дома плюс `viewer`, `my_issues` и серверная очередь `my_tasks` с одним следующим действием для роли
- `GET /houses/{id}/assets`
- `GET /assets/{id}`
- `GET /assets/{id}/timeline`

## Signal / Issue

- `POST /signals`
- `GET /signals/{id}`
- `POST /signals/{id}/resolve` — applies a user's category/zone clarification to the original Signal without creating a duplicate
- `POST /signals/{id}/resolve-duplicate`
- `GET /issues?house_id=...`
- `GET /issues/{id}`
- `POST /issues/{id}/confirm`
- `POST /issues/{id}/route` — ручной выбор адресата при низкой уверенности маршрутизации; выбор сохраняется на действии и учитывается при передаче
- `POST /issues/{id}/submit` — отправляет по выбранному вручную адресату, иначе по роутингу категории из конфига дома
- `POST /issues/{id}/accept`
- `POST /issues/{id}/verify`

`POST /signals` returns one of: Issue, Initiative, NO_ACTION, or an explicit fallback. `force_ai_failure=true` is demo/test-only fault injection.

## WorkOrder

- `POST /work-orders`
- `PATCH /work-orders/{id}`
- `POST /work-orders/{id}/evidence`

## Initiative

- `POST /initiatives`
- `GET /initiatives/{id}`
- `POST /initiatives/{id}/poll`
- `POST /initiatives/{id}/handoff`

## MAX

- Bot worker: `GET https://platform-api2.max.ru/updates` (Long Polling, hackathon/dev)
- Bot replies: `POST https://platform-api2.max.ru/messages`
- `GET /integrations/max/status`
- `GET /integrations/max/chats/{chat_id}/permissions`
- `POST /integrations/max/webhook`

The worker and webhook consume the same official `message_created` Update shape. Polling conversations can switch config with `/house_a` and `/house_b`; the default is House A. Webhook verifies `X-Max-Bot-Api-Secret` when configured. A production deployment should persist an explicit chat-to-house mapping and move reception to webhook.

## Audit

- `GET /audit/{entity_type}/{entity_id}`
