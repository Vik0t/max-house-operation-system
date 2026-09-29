# Production deployment

Текущий demo разделён на два deployment unit:

- frontend: GitHub Pages, `https://apaww.github.io/dom.sreda.io/`;
- backend: VPS, `https://104.252.77.141.nip.io/` (Caddy + Let's Encrypt), PostgreSQL, API и MAX bot worker.

## Backend

Production Compose описан в `compose.prod.yaml`. На сервер передаются только image artifact, Compose/Caddy config и закрытый `.env.prod`; секреты не коммитятся. Перед обновлением сохраняйте текущий tag образа и копию `.env.prod` с правами 0600: это даёт откат без сброса БД.

```bash
./scripts/render-prod-env.sh .env /private/tmp/dompuls.env.prod
docker buildx build --platform linux/amd64 \
  -f apps/api/Dockerfile -t dompuls-api:latest --load .
docker save dompuls-api:latest | gzip -1 > /private/tmp/dompuls-api-amd64.tar.gz
```

На VPS:

```bash
cd /opt/dompuls
gunzip -c dompuls-api-amd64.tar.gz | docker load
docker compose --env-file .env.prod -f compose.yaml up -d
docker compose --env-file .env.prod -f compose.yaml ps
```

Для публичного запуска: `AUTH_MODE=required`, `INTERNAL_API_KEY` — случайный длинный ключ, `BOT_ROLE_MODE=showcase` только на время жюри. После получения MAX ID заполнить allowlists и выставить `BOT_ROLE_MODE=assigned`. `LLM_MODE=openrouter` и `LLM_API_KEY` включают только ручной чат помощника. Ключи никогда не должны попадать в `VITE_*`, Git или Pages.

Проверка:

```bash
curl --fail https://104.252.77.141.nip.io/health
```

## Frontend

Исходники frontend находятся в отдельном репозитории `apaww/dom.sreda.io`. Build использует:

```dotenv
VITE_API_URL=https://104.252.77.141.nip.io
VITE_BASE_PATH=/dom.sreda.io/
```

GitHub Actions из `main` собирает и публикует воспроизводимый `dist` artifact. Публичная сборка не включает `VITE_ALLOW_REMOTE_DEMO`, поэтому `?demo=true` на Pages не обходит MAX-auth. Локально `?local=true` открывает отдельно помеченный offline-demo; он не записывает данные на VPS.

## Operations

- единственный production poller должен работать на VPS; не запускайте локальный `bot` одновременно с ним;
- логи: `docker compose --env-file .env.prod -f compose.yaml logs -f api bot caddy`;
- БД и Caddy certificates находятся в named volumes;
- перед production использовать SSH-ключи и отключить парольный вход; текущее состояние VPS проверять отдельно, не считать это уже выполненным;
- перед передачей проекта команде добавьте резервный SSH key и сохраните recovery-инструкцию вне репозитория.
