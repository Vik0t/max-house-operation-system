FROM node:22-alpine AS build
WORKDIR /app
COPY apps/miniapp/package.json apps/miniapp/package-lock.json apps/miniapp/tsconfig.json apps/miniapp/tsconfig.app.json apps/miniapp/vite.config.ts ./
RUN npm ci --no-audit --no-fund
COPY apps/miniapp/index.html ./
COPY apps/miniapp/src ./src
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY apps/miniapp/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
