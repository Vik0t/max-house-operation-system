FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/apps/api
COPY pyproject.toml alembic.ini ./
RUN pip install --no-cache-dir '.[dev]'
COPY apps/api ./apps/api
COPY configs ./configs
COPY scripts ./scripts
COPY alembic ./alembic
COPY tests ./tests
COPY datasets ./datasets
COPY models ./models
COPY certs ./certs
RUN chmod +x scripts/api-entrypoint.sh
EXPOSE 8000
CMD ["./scripts/api-entrypoint.sh"]
