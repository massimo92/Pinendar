# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.11.29 AS uv

FROM python:3.12.12-slim-trixie AS builder
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM builder AS development
COPY alembic.ini ./
COPY alembic ./alembic
COPY public ./public
COPY data/hospitals ./catalog/hospitals
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
ENV PINENDAR_DATABASE_PATH=/app/data/pinendar.sqlite \
    PINENDAR_HOSPITAL_CATALOG_DIR=/app/catalog/hospitals \
    PINENDAR_STATIC_DIR=/app/public \
    PINENDAR_SCHEDULER_PROCESS_POOL=false
CMD ["uv", "run", "--locked", "uvicorn", "pinendar.main:app", "--host", "0.0.0.0", "--port", "4173", "--reload"]

FROM python:3.12.12-slim-trixie AS runtime
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PINENDAR_DATABASE_PATH=/app/data/pinendar.sqlite \
    PINENDAR_HOSPITAL_CATALOG_DIR=/app/catalog/hospitals \
    PINENDAR_STATIC_DIR=/app/public \
    PINENDAR_MIGRATE_ON_STARTUP=false \
    PINENDAR_PORT=4173
WORKDIR /app

RUN groupadd --system pinendar && useradd --system --gid pinendar --home-dir /app pinendar
COPY --from=builder /app/.venv ./.venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY public ./public
COPY data/hospitals ./catalog/hospitals
COPY docker-entrypoint.sh ./
RUN mkdir -p /app/data && chmod 755 /app/docker-entrypoint.sh && chown -R pinendar:pinendar /app/data

USER pinendar
EXPOSE 4173
VOLUME ["/app/data"]
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "pinendar.main:app", "--host", "0.0.0.0", "--port", "4173", "--workers", "1"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4173/health/ready', timeout=3).read()"]
