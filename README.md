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

По умолчанию `.env.example` использует локальный демонстрационный режим:

```dotenv
MAX_MODE=simulated
LLM_MODE=deterministic
AUTH_MODE=demo
BOT_ROLE_MODE=showcase
```

Для реального MAX задайте локально, не коммитьте:

```dotenv
MAX_MODE=real
MAX_BOT_TOKEN=...
MAX_CA_BUNDLE=/app/certs/russian-trusted-ca.pem
```

Compose запустит отдельный `bot` worker. Он читает `GET /updates` через Long Polling, отправляет сообщения в существующий Signal/Issue pipeline и отвечает в MAX. `/start` открывает чатовый пульт и предлагает выбрать рабочую роль **только в режиме показа**. В `BOT_ROLE_MODE=assigned` роли берутся исключительно из `MAX_REPRESENTATIVE_IDS`, `MAX_UK_IDS`, `MAX_EXECUTOR_IDS` (это именно `user_id` из событий MAX, не `chat_id` и не номер из ссылки на диалог). Бот уточняет только то, чего действительно не понял; заявки и инициативы можно создать из чата. Житель подтверждает сигнал и результат, домоуправляющий решает вопрос передачи, УК принимает/назначает, исполнитель прикладывает реальное фото выполнения и завершает работу. В групповом чате бот публикует общий опрос по инициативе с обновляемым итогом; частные действия ролей на этой карточке не показываются. Чат получает обновления статуса. `MAX_CA_BUNDLE` содержит цепочку доверия MAX; TLS verification не отключается. Подробности: [docs/max_setup.md](docs/max_setup.md).

В production задайте `AUTH_MODE=required` и случайный `INTERNAL_API_KEY`: публичные изменения тогда требуют подписанный MAX `initData` с проверкой времени, а бот обращается к API по отдельному серверному ключу. Пользователь выбирает свой дом в приложении, выбор сохраняется по MAX ID и доступен боту. Это **самообъявление дома**, не подтверждение прописки. В режиме показа роли в боте переключаются для жюри; перед реальным использованием назначьте MAX ID и включите `BOT_ROLE_MODE=assigned`. Публичный сайт вне MAX доступен для просмотра, но запись требует входа через MAX.

Опциональный `LLM_MODE=openrouter` относится **только** к ручному чату «Голубь Макс» в мини‑приложении. Перед отправкой показывается уведомление; сообщения групп, обращения и состояние дома во внешний LLM не передаются. Основная ML-категоризация работает локально без него.

Проверка:

```bash
docker compose logs -f bot
```

В MAX откройте своего бота и отправьте `/start`. Сначала выберите роль: после этого главное меню и очередь задач меняются под роль, а не только набор кнопок в карточке. Житель видит свои обращения и проверку результата; домоуправляющий — решения о передаче; УК — новые обращения и работы; исполнитель — назначенные работы. Русские команды: `/состояние`, `/меню`, `/назад`, `/отмена`, `/помощь`; в демо дом можно переключить кнопками или `/дом_a` и `/дом_b`. Кнопка `Назад` возвращает к предыдущему шагу, а отмена очищает текущий диалог и возвращает в меню. В групповом демо выберите отдельную роль для каждого участника: житель → домоуправляющий → УК → исполнитель. Badge `MAX REAL · BOT ONLINE` означает, что и Bot API, и polling-worker реально отвечают.

## Demo за 4 минуты

1. Откройте mini-app: в MAX или локальном демо первым экраном будут `Задачи` и `Мои обращения`. Перейдите на вкладку `Дом`: там виден `Лифт №2`, текущая проблема, история прошлых случаев и закрытых работ. После повторных прогонов счётчик событий закономерно растёт; для исходного сценария сбросьте только локальную демо-БД.
2. Отправьте по очереди сообщения: `лифт опять встал, второй подъезд`, `у меня тоже`, `вчера уже не работал лифт во втором подъезде`. Они войдут в одну проблему; повторные сообщения будут показаны одной карточкой с числом подтверждений.
3. Для группового демо добавьте бота в домовой чат и проверьте право `read_all_messages`; до живой проверки такого чата не считайте групповой сценарий подтверждённым. Роли показывайте на разных MAX-пользователях через личный диалог с ботом. Локальная веб‑сборка допускает `?demo=true` для показа ролей на общем API; публичный GitHub Pages build этого обхода не содержит. Житель нажимает `У меня тоже`; домоуправляющий — `Подтвердить проблему` и `Передать в УК`; УК — `Принять обращение` и `Назначить исполнителя`; исполнитель — `Начать работу`, прикладывает фото выполнения и завершает работу.
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

Это неперсональные demo identities только для локального режима. В production используется проверенный MAX ID; рабочие роли до назначения allowlist остаются закрытыми в мини‑приложении.

## Reset и migrations

```bash
./scripts/reset-demo.sh
docker compose exec api alembic current
docker compose exec api alembic upgrade head
```

Reset удаляет только данные и схему demo database из текущего Compose project, затем восстанавливает детерминированный seed. **Не запускайте его на VPS с пользовательскими данными.**

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

Последний подтверждённый прогон: `103 passed`, включая 20 последовательных прогонов основного сценария; production React build также проходит. Метрики и ограничения выборки: [docs/ai_metrics.md](docs/ai_metrics.md).

## Архитектура

- `apps/api` — FastAPI, domain orchestration, adapters;
- `apps/miniapp` — React/TypeScript mobile-first mini-app;
- `configs` — house topology, routing, contractors, thresholds;
- `alembic` — PostgreSQL migrations;
- `datasets/house_chat_eval` — synthetic AI eval;
- `tests` — unit, integration, E2E;
- PostgreSQL хранит House State Graph обычными relation tables.

Детали: [docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md). Статическая схема для проверки: [openapi.json](openapi.json), сценарии проверок: [DATA-API.yaml](DATA-API.yaml).

## Real vs simulated

| Интеграция | Статус |
|---|---|
| MAX Bot API | REAL: production worker получает сообщения и callbacks, ведёт chat-first wizard, отправляет inline keyboard/open_app/status notifications и отвечает как `@t312_hakaton_max_bot`; webhook path также готов |
| MAX Bridge / launch context | REAL adapter: официальный Bridge загружается в mini-app, подписанный `initData` проверяется backend HMAC и TTL |
| Локальный direct input | REAL local input path |
| AI pipeline | REAL: структурированный pipeline, локальная обученная модель категорий и безопасные правила для места/объекта/состояния; внешний LLM не требуется |
| «Голубь Макс» | OpenRouter только для ручного чата в подписанной MAX-сессии; при ошибке — локальный ответ |
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
- Карта Кольцово и адресный каталог — стартовые ориентиры; выбранный новый дом/координаты и УК не считаются проверенными официальными сведениями. Для полного каталога нужны адресный реестр и подтверждение УК.
- MAX ID подтверждает личность аккаунта, но не проживание в доме. Организационные роли следует назначить allowlist перед реальным использованием.
- Нет object storage, CRM/ГИС ЖКХ adapter и юридически значимого ОСС. Передача в УК явно симулируется.
- ML-датасет содержит только синтетические/подготовленные обращения; результат нельзя обобщать на реальные чаты. Нужна независимая разметка дубликатов и проверка на других домах.

## Основные документы

- [Architecture](docs/architecture.md)
- [API](docs/api.md)
- [Demo runbook](docs/demo.md)
- [MAX setup](docs/max_setup.md)
- [AI metrics](docs/ai_metrics.md)
- [Evidence registry](docs/evidence_registry.md)
- [Security](docs/security.md)
- [Production deployment](docs/deployment.md)
- [Презентация для жюри (PDF)](submission/DomPuls_MAX_hackathon.pdf) · [редактируемый PPTX](submission/DomPuls_MAX_hackathon.pptx)
