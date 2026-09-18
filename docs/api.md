# API contract

Interactive schema is available at `/docs`; OpenAPI JSON is at `/openapi.json`.

## House / Asset

- `GET /houses`
- `GET /houses/{id}`
- `GET /houses/{id}/state`
- `GET /houses/{id}/assets`
- `GET /assets/{id}`
- `GET /assets/{id}/timeline`

## Signal / Issue

- `POST /signals`
- `GET /signals/{id}`
- `POST /signals/{id}/resolve-duplicate`
- `GET /issues?house_id=...`
- `GET /issues/{id}`
- `POST /issues/{id}/confirm`
- `POST /issues/{id}/submit`
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

- `GET /integrations/max/status`
- `GET /integrations/max/chats/{chat_id}/permissions`
- `POST /integrations/max/webhook`

Webhook verifies `X-Max-Bot-Api-Secret` when configured and consumes official `message_created` Update shape. A public deployment should map chat IDs to house IDs explicitly; the demo fallback house is House A.

## Audit

- `GET /audit/{entity_type}/{entity_id}`

