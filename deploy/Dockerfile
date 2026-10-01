# Образ api/worker для режима scaled (ADR-3, ADR-6). Контекст сборки — корень репозитория:
#   docker compose -f deploy/docker-compose.yml build
# Раскладка /app/backend + /app/frontend/dist совпадает с репозиторием, поэтому
# FRONTEND_DIST_DIR по умолчанию работает без переменных окружения.

# ---------- 1. Сборка фронтенда
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- 2. Backend
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --extra scaled --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev --extra scaled

COPY --from=frontend /app/frontend/dist /app/frontend/dist

RUN useradd --create-home --uid 10001 app && mkdir -p /app/backend/media && chown app /app/backend/media
USER app

ENV PATH="/app/backend/.venv/bin:$PATH"
EXPOSE 8000
# Команда задаётся в docker-compose.yml (api / worker / migrate).
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
