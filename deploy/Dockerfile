# syntax=docker/dockerfile:1
# Образ api/worker для режима scaled (ADR-3, ADR-6). Контекст сборки — корень репозитория:
#   docker compose -f deploy/docker-compose.yml build
# Раскладка /app/backend + /app/frontend/dist совпадает с репозиторием, поэтому
# FRONTEND_DIST_DIR по умолчанию (<repo>/frontend/dist) работает без переменных окружения.

# ---------- 1. Сборка фронтенда (Node 22 LTS — как в CI)
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. uv: версия закреплена (не latest), чтобы сборка была воспроизводимой
FROM ghcr.io/astral-sh/uv:0.12.21 AS uv

# ---------- 3. Backend
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app/backend
# Сначала только зависимости (слой кэшируется, пока не меняется uv.lock), затем код проекта.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra scaled --no-install-project
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra scaled

COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Код и зависимости принадлежат root и только читаются; пользователь app может писать
# лишь в каталог медиа (именованный том media).
# USER — числовой: так среда запуска может проверить, что процесс не root.
RUN groupadd --gid 10001 app \
    && useradd --create-home --uid 10001 --gid app --shell /usr/sbin/nologin app \
    && mkdir -p /app/backend/media \
    && chown app:app /app/backend/media
USER 10001:10001

ENV PATH="/app/backend/.venv/bin:$PATH"
EXPOSE 8000
# Liveness api (GET /health не трогает БД и Redis). Для worker в docker-compose.yml
# задан свой healthcheck.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]
# Команда задаётся в docker-compose.yml (api / worker).
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
