# Jury demo runbook

## Before the demo

```bash
cp .env.example .env   # once
docker compose up --build -d
./scripts/reset-demo.sh
curl http://localhost:8000/health
```

Open <http://localhost:3000>. Keep `/docs` in a second tab as architecture proof.

## Exact flow

### 0:00–0:40 — House memory

Show House A metrics and click `Лифт №2`. Point out three previous closed incidents and current fourth incident. Close timeline.

### 0:40–1:10 — Chat to structured Issue

Send the three supplied chips in order. The current issue reaches 8 confirmations and retains two source evidence. Say: «ДомПульс связал сообщения не просто с тикетом, а с объектом и его историей».

### 1:10–2:30 — Closed loop

Open the current Issue and press:

```text
Подтвердить проблему
→ Передать ответственному
→ Принять от имени УК
→ Назначить мастера
→ Начать работу
→ Добавить evidence
→ Завершить работу
→ Да, работает
```

Show that Submission is honestly marked SIMULATED. After verification, Asset becomes HEALTHY. Reopen Asset timeline and show the new Issue and WorkOrder.

### 2:30–3:10 — Community initiative

Vote in «Второй фонарь на парковке», then `Зафиксировать результат`. Show `FORMAL HANDOFF REQUIRED` and the notice that the poll is not a legal ОСС.

### 3:10–3:35 — Scale proof

Switch to House B. Point out different asset tree, management organization, recurrence threshold and contractor routing. If time allows, create a lift issue and confirm it; Action destination is `polar-lift-contractor`.

### 3:35–4:00 — Reliability / integrity

Mention 20 clean E2E runs, webhook idempotency, state-machine rejection, manual AI fallback and provenance. Click `Проверить AI fallback` if the network/demo is stable.

## Recovery

- Reset: `./scripts/reset-demo.sh`.
- API health: `curl http://localhost:8000/health`.
- Logs: `docker compose logs --tail=100 api`.
- If MAX CA/token/webhook is unavailable, keep direct input and show `REAL · CONFIGURED`; never call it connected.

