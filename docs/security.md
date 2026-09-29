# Security notes

## Implemented

- Git and Docker context exclude `.env`.
- Settings validate integration mode.
- `AUTH_MODE=required` проверяет подписанный MAX `initData` (HMAC и срок жизни) для публичных изменений; бот использует отдельный `INTERNAL_API_KEY`. Для ролей УК/исполнителя/домоуправляющего предусмотрены MAX-ID allowlists.
- Выбор дома хранится по MAX ID. Доступ к записи ограничен выбранным домом; подтверждение проживания пока самообъявленное, не официальный реестр жителей.
- `BOT_ROLE_MODE=showcase` разрешает переключать рабочую роль **только в боте для жюри**. До работы с настоящими жильцами нужен `BOT_ROLE_MODE=assigned` и заполненные role allowlists.
- MAX token is never accepted via query parameter.
- Webhook secret uses constant-time comparison.
- Signal external IDs and Webhook event IDs are unique/idempotent.
- Evidence accepts only `http(s)`, `/demo/` or data-image URIs; no executable upload path exists.
- Фото из браузера ограничено размером и типом data-image. Бот принимает только фактический HTTPS URL вложения MAX; фиктивное подтверждение работы не создаётся.
- В OpenRouter идут только вручную написанные сообщения помощнику при подписанном запуске из MAX; обращения/группы и данные дома не пересылаются. Есть ограничение частоты, маскирование типичных телефонов/e-mail и локальный fallback.
- Domain transitions are deterministic and audited.
- Synthetic and AI-derived data carry provenance.
- Database is not exposed to the host by Compose.

## Production gates

- Назначить реальные MAX ID в role allowlists и переключить `BOT_ROLE_MODE=assigned`; demo showcase не является контролем доступа оператора.
- Require (not merely support) `MAX_WEBHOOK_SECRET` in real mode.
- Привязать групповые чаты к дому администратором/домоуправляющим и подтвердить право `read_all_messages`; сейчас связь хранится в состоянии бота, не в официальном реестре.
- Use S3-compatible object storage, MIME sniffing, size limits, malware scanning and signed URLs for uploads.
- Add retention/deletion policy and PII redaction.
- Move secrets to Docker/Kubernetes secret mounts or a managed secret store.
- Generate explicit Alembic revisions for every schema change and rehearse backup/restore.
