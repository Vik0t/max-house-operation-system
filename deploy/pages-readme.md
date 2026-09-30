# Дом.Среда · MAX mini-app

Публичный frontend P0 MVP: состояние дома, проблемы и их жизненный цикл, work orders, evidence/verification, история активов и инициативы.

Production: <https://apaww.github.io/dom.sreda.io/>

Frontend собирается GitHub Actions из `main`. Backend URL задаётся через `VITE_API_URL` в workflow; сейчас он указывает на VPS проекта.

## Локальный запуск

```bash
cp .env.example .env
npm ci
npm run dev
```

Для production-проверки:

```bash
VITE_API_URL=https://104.252.77.141.nip.io \
VITE_BASE_PATH=/dom.sreda.io/ \
npm run build
```

MAX Bridge загружается с официального CDN. При обычном открытии в браузере mini-app остаётся работоспособным в web-режиме; внутри MAX подписанный launch context валидируется backend-ом.
