# Jury demo runbook

## Before the demo

```bash
cp .env.example .env   # once
docker compose up --build -d
./scripts/reset-demo.sh
curl http://localhost:8000/health
```

Open <http://localhost:3000/?demo=true>. The first screen is the resident's task queue and `Мои обращения`; `Дом` shows the state of the selected house. `?demo=true` works only in the local Docker build; the public GitHub Pages build requires signed MAX identity for write actions. Bot role selection is temporarily enabled by `BOT_ROLE_MODE=showcase`; set `BOT_ROLE_MODE=assigned` and MAX-ID allowlists before real operation. Keep `/docs` in a second tab as architecture proof.

For the real MAX demo, open the configured bot, send `/start`, choose a role, then send the lift messages there. Watch `docker compose logs -f bot`; the same Issue will appear in the mini-app. Use `Сменить дом` or `/дом_b` to demonstrate config-driven switching from the bot.

## Exact flow

### 0:00–0:40 — Role-specific task queue

Start as `Житель`, then switch to `Домоуправляющий`, `УК / диспетчер` and `Исполнитель`. The heading, task queue and next action change for each role. A resident never sees assignment or executor controls. `Мои обращения` stays in `Задачи` even after a problem is closed; `Дом` shows the shared asset history.

### 0:40–1:10 — House memory

Show House A metrics and click `Лифт №2`. Point out three previous closed incidents and current fourth incident. Close timeline. In the MAX group, the bot keeps one public issue card with its confirmations and recurrence count; subsequent steps edit that same card.

### 1:10–1:40 — Chat to structured Issue

Send the three supplied messages in order. The current issue is shown as one grouped incident with confirmations and source messages. Say: «ДомПульс связал сообщения не просто с обращением, а с объектом и его историей».

### 1:40–3:00 — Closed loop

Open the current Issue with the appropriate role and press:

```text
У меня тоже / Подтвердить проблему
→ Передать в УК
→ Принять обращение
→ Назначить исполнителя
→ Начать работу
→ Приложить фото выполненной работы
→ Завершить работу
→ Да, всё исправлено
```

Show that передача помечена как демонстрационная. After verification, Asset becomes HEALTHY. Reopen Asset timeline and show the new Issue and WorkOrder. Return to the MAX group card: it now says the resident confirmed the result, with no operator controls or personal data exposed.

### 3:00–3:35 — Community initiative

If a MAX house group is registered and its `read_all_messages` permission is verified, send «На парковке нужен второй фонарь» there. The bot publishes one informal poll card in that group. Vote from two different MAX accounts and show the count update in place. Then, as the representative, open the initiative in the bot or mini-app and press `Зафиксировать результат`. Show the marker that a formal handoff is required and the notice that the poll is not a legal ОСС. Until a real group is connected, demonstrate this flow in the bot's personal dialog and do not call the group integration live-tested.

### 3:35–3:55 — Scale proof

Switch to House B. Point out different asset tree, management organization, recurrence threshold and contractor routing. If time allows, create a lift issue and confirm it; Action destination is `polar-lift-contractor`.

### 3:55–4:20 — Reliability / integrity

Mention 20 clean E2E runs, polling/webhook idempotency, state-machine rejection, manual AI fallback and provenance. Technical signal input and AI fallback are available only under the explicit `Это демо` control in the resident report form.

## Recovery

- Reset: `./scripts/reset-demo.sh`.
- API health: `curl http://localhost:8000/health`.
- Logs: `docker compose logs --tail=100 api bot`.
- If MAX CA/token is unavailable, keep direct input and show the exact connection state; never call it connected.
