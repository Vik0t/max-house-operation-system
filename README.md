# ДомПульс / MAX

Работающий P0 MVP операционного цифрового двойника многоквартирного дома:

```text
Signal → Issue / Initiative → House / Zone / Asset → Action → Submission
→ WorkOrder → Evidence → Verification → House Memory
```

ДомПульс управляет состоянием объектов дома во времени. Главный proof — не карточка заявки, а полный цикл для `Подъезд 2 → Лифт №2` с историей повторений, работой исполнителя, evidence, проверкой жителем и обновлением Asset timeline.

## Быстрый запуск

### Prerequisites

- Docker Desktop / Docker Engine с Compose v2;
- свободные порты `3000` и `8000`;
- для реального MAX в hackathon/dev — bot token; CA bundle Минцифры уже лежит в `certs/` и используется только MAX-клиентом.

```bash
cp .env.example .env
docker compose up --build
```

Открыть:

- mini-app: <http://localhost:3000>
- OpenAPI: <http://localhost:8000/docs>
- health: <http://localhost:8000/health>

Публичный demo:

- mini-app: <https://apaww.github.io/dom.sreda.io/>
- API / health: <https://104.252.77.141.nip.io/health>

Первый запуск автоматически выполняет `alembic upgrade head` и загружает seed. Повторный запуск не дублирует данные.

## Environment

По умолчанию `.env.example` использует безопасный демонстрационный режим:

```dotenv
MAX_MODE=simulated
LLM_MODE=deterministic
```

Для реального MAX задайте локально, не коммитьте:

```dotenv
MAX_MODE=real
MAX_BOT_TOKEN=...
MAX_CA_BUNDLE=/app/certs/russian-trusted-ca.pem
```

Compose запустит отдельный `bot` worker. Он читает `GET /updates` через Long Polling, отправляет сообщения в существующий Signal/Issue pipeline и отвечает в MAX. `/start` открывает чатовый пульт: бот сначала пытается понять сообщение целиком и задаёт уточнение только при низкой уверенности, `/status` показывает активные Issue с кнопками, а инициативу можно создать и довести до handoff прямо в чате. Карточки Issue используют role-scoped inline-кнопки: житель подтверждает сигнал и результат, домоуправляющий принимает решение о передаче, УК принимает/назначает, исполнитель добавляет evidence и завершает работу. Чат подписывается на созданный Issue и получает уведомления о смене состояния. `MAX_CA_BUNDLE` содержит официальную цепочку Russian Trusted Root/Sub CA; TLS verification не отключается. Подробности: [docs/max_setup.md](docs/max_setup.md).

Проверка:

```bash
docker compose logs -f bot
```

В MAX откройте своего бота и отправьте `/start`. Используйте кнопки `Сообщить о проблеме`, `Состояние дома`, `Предложить инициативу`, `Сменить дом`, `Моя рабочая роль`; команды: `/status`, `/house_a`, `/house_b`, `/menu`, `/back`, `/cancel`, `/help`. Кнопка `Назад` возвращает к предыдущему шагу, а `/back` работает как её текстовая альтернатива. В групповом демо выберите отдельную роль для каждого участника: житель → домоуправляющий → УК → исполнитель. Badge `MAX REAL · BOT ONLINE` означает, что и Bot API, и polling-worker реально отвечают.

## Demo за 4 минуты

1. Откройте House A. В House State виден `Лифт №2`: текущая проблема, четвёртый incident за 90 дней, два source evidence и история трёх закрытых работ.
2. Отправьте по очереди demo-сообщения: `лифт опять встал, второй подъезд`, `у меня тоже`, `вчера уже не работал лифт во втором подъезде`. Они войдут в один Issue; счётчик подтверждений станет 8.
3. Для group demo выберите роли на разных MAX-пользователях и пройдите межролевой loop: житель нажимает `У меня тоже`; домоуправляющий — `Подтвердить проблему` и `Передать в УК`; УК — `Принять в работу` и `Назначить исполнителя`; исполнитель — `Начать работу`, `Добавить evidence`, `Завершить`.
4. На вопрос «Проблема устранена?» нажмите `Да, работает`. Issue станет CLOSED, WorkOrder — ACCEPTED, Asset — HEALTHY, timeline сохранит результат.
5. В Initiative «Второй фонарь на парковке» проголосуйте и нажмите `Зафиксировать результат`. Появится `FORMAL HANDOFF REQUIRED`; UI явно говорит, что это не ОСС.
6. В верхнем selector переключитесь на House B: изменятся topology, УК, recurrence threshold и routing без изменения core-кода.

Для reopen path на шаге 4 выберите `Нет, переоткрыть`; Issue станет REOPENED, WorkOrder — REWORK_REQUIRED, появится `Начать доработку`.

Полный сценарий: [docs/demo.md](docs/demo.md).

## Demo users / roles

| Роль | Demo ID | Действия |
|---|---|---|
| Житель | `resident-demo` | signal, confirmation, poll, verification |
| Представитель дома | `representative-demo` | action confirmation, submission, initiative handoff |
| УК | `uk-demo` | accept, assign |
| Исполнитель | `master-demo` | start, evidence, complete |

Это фиксированные неперсональные demo identities. Production authentication/RBAC остаётся integration task.

## Reset и migrations

```bash
./scripts/reset-demo.sh
docker compose exec api alembic current
docker compose exec api alembic upgrade head
```

Reset удаляет только данные и схему demo database из текущего Compose project, затем восстанавливает детерминированный seed.

## Tests

```bash
./scripts/test.sh
```

Suite покрывает:

- state machines и невозможные переходы;
- config/schema, contextual duplicate scoring и recurrence;
- AI structured extraction и synthetic eval;
- API, database, AI fallback и MAX mock adapter;
- webhook и polling-message idempotency;
- golden path 20 clean последовательных прогонов;
- negative verification/rework;
- Initiative flow;
- second-house routing.

Последний подтверждённый прогон API и MAX-бота: `42 passed`; production React build и live browser verification также проходят. Метрики: [docs/ai_metrics.md](docs/ai_metrics.md).

## Архитектура

- `apps/api` — FastAPI, domain orchestration, adapters;
- `apps/miniapp` — React/TypeScript mobile-first mini-app;
- `configs` — house topology, routing, contractors, thresholds;
- `alembic` — PostgreSQL migrations;
- `datasets/house_chat_eval` — synthetic AI eval;
- `tests` — unit, integration, E2E;
- PostgreSQL хранит House State Graph обычными relation tables.

Детали: [docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md).

## Real vs simulated

| Интеграция | Статус |
|---|---|
| MAX Bot API | REAL: production worker получает сообщения и callbacks, ведёт chat-first wizard, отправляет inline keyboard/open_app/status notifications и отвечает как `@t312_hakaton_max_bot`; webhook path также готов |
| MAX Bridge / launch context | REAL adapter: официальный Bridge загружается в mini-app, подписанный `initData` проверяется backend HMAC и TTL |
| Локальный direct input | REAL local input path |
| AI pipeline | REAL deterministic structured pipeline; внешний LLM не требуется |
| Отправка в УК / ГИС ЖКХ / Госуслуги Дом | SIMULATED, `Submission.is_simulated=true` |
| Demo evidence и history | SYNTHETIC, помечено provenance |
| Initiative poll | REAL внутри MVP, но не юридически значимое ОСС |

## Security

- `.env` и secrets исключены из Git и Docker build context;
- токен передаётся MAX только в `Authorization` header;
- webhook secret проверяется constant-time;
- webhook и signal external IDs идемпотентны;
- evidence URI валидируется, arbitrary file execution/upload отсутствует;
- provenance разделяет OFFICIAL / USER / CALCULATED / AI_INFERENCE / SYNTHETIC;
- state changes пишутся в append-only audit table;
- зависимости backend зафиксированы версиями.

Security notes: [docs/security.md](docs/security.md).

## Ограничения MVP

- Сейчас bot стабильно работает через Long Polling с VPS. Публичный HTTPS webhook endpoint готов; переключение делается после выдачи/подключения webhook со стороны MAX.
- Для чтения группового чата бот должен быть администратором с правом `read_all_messages`; личный диалог работает без этого права.
- Внешний LLM не подключён: deterministic pipeline выбран для воспроизводимого hackathon demo. Есть schema validation и fault injection fallback.
- Нет production auth/RBAC, object storage, CRM/ГИС ЖКХ adapter и юридически значимого ОСС.
- Eval dataset содержит 30 синтетических примеров, не 300–500 production-like сообщений; метрики нельзя обобщать на реальные чаты.

## Основные документы

- [Architecture](docs/architecture.md)
- [API](docs/api.md)
- [Demo runbook](docs/demo.md)
- [MAX setup](docs/max_setup.md)
- [AI metrics](docs/ai_metrics.md)
- [Evidence registry](docs/evidence_registry.md)
- [Security](docs/security.md)
- [Production deployment](docs/deployment.md)
