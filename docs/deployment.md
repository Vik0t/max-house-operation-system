# Production deployment

Текущий demo разделён на два deployment unit:

- frontend: GitHub Pages, `https://apaww.github.io/dom.sreda.io/`;
- backend: VPS, `https://104.252.77.141.nip.io/` (Caddy + Let's Encrypt), PostgreSQL, API и MAX bot worker.

## Backend

Production Compose описан в `compose.prod.yaml`. На сервер передаются только image artifact, Compose/Caddy config и закрытый `.env.prod`; секреты не коммитятся.

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

GitHub Pages сейчас совместим с branch-based публикацией: production `index.html` и hashed assets лежат в `main`; GitHub Actions workflow также собирает воспроизводимый `dist` artifact.

## Operations

- единственный production poller должен работать на VPS; не запускайте локальный `bot` одновременно с ним;
- логи: `docker compose --env-file .env.prod -f compose.yaml logs -f api bot caddy`;
- БД и Caddy certificates находятся в named volumes;
- firewall пропускает только `22`, `80`, `443`; парольный SSH отключён, используется deploy key;
- перед передачей проекта команде добавьте резервный SSH key и сохраните recovery-инструкцию вне репозитория.
