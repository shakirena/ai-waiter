# Story #37: Backend: каркас FastAPI, настройки из окружения, /health, .env.example

*Родитель: #6. Каждый агент дописывает свой раздел — не перезаписывает чужие.*

---

## 📋 Задача (analyst)

**AC:** Given в чистой копии репозитория установлены зависимости `backend/` (Python 3.12) и заданы переменные из `.env.example` When выполняются `ruff check .`, `pytest -q` и запускается `uvicorn app.main:app`, затем выполняется `GET /health` Then ruff и pytest завершаются без ошибок, а `/health` отвечает `200` с JSON, где есть `status: ok` и текущий `mode` (`single` или `scaled`); приложение не стартует с понятной ошибкой, если обязательная переменная не задана или `APP_MODE` имеет недопустимое значение
**Роли:** разработчик
**ТЗ:** ТЗ раздел 8 (стек, режимы), NFR-4 (секреты в env), NFR-6, NFR-8
**Ограничения:** Модели БД, Alembic и подключение к PostgreSQL (задача #7); Интерфейсы EventBus/TaskScheduler/RateLimiter (отдельная story); Авторизация, tenant-логика, бизнес-эндпоинты; Проверка доступности БД в `/health` (появится с #7)
**Зависимости:** нет
**Spec:** docs/specs/feature-6-project-scaffold.md

---

## 💻 Реализация (developer)

**Branch:** wt/37-backend (от feature/6-project-scaffold)
**Новые файлы:**
- backend/uv.lock
- backend/tests/test_main.py — create_app, docs в prod/dev, ленивый `app`, `python -m app` (uvicorn.run подменён), ошибки старта
- backend/tests/test_log.py — JSON/console, маскирование SecretStr, uvicorn-логгеры

**Изменённые файлы:**
- backend/app/main.py — `create_app(settings=None, *, registry=None)`, `app.state.settings`/`task_registry`, ленивый `app` через `__getattr__`, минимальный lifespan (лог старта/остановки; Container — #38), `mount_spa` при `SERVE_FRONTEND` (реализация — #42)
- backend/app/__main__.py — uvicorn factory, HOST/PORT/API_WORKERS, `log_config=None`, `proxy_headers`, `forwarded_allow_ips="127.0.0.1,::1"`; `ConfigError` → текст в stderr, код 1
- backend/app/core/config.py — `ConfigError` и `format_validation_error` (русские пояснения, значения переменных не выводятся, цепочка исключений подавлена); `env_ignore_empty`; single слушает только loopback; `PUBLIC_BASE_URL` — домен, не IP
- backend/app/core/log.py — `JsonFormatter`, `configure_logging` (идемпотентен, stderr, uvicorn-логгеры через корневой обработчик, `color_message` uvicorn отбрасывается)
- backend/app/api/health.py — только `GET /health`; настройки из `app.state.settings`; `/health/ready` и `ReadinessResponse` убраны (вернёт #38 вместе с `get_container`)
- backend/tests/test_config.py — добавлены тесты #37 (в т. ч. «каждое поле Settings есть в .env.example»)
- backend/pyproject.toml — ruff `src = ["."]` (иначе `app`/`tests` не считались first-party, I001 в тестах)
- backend/tests/test_container.py — только `ruff format`
- .env.example — уточнены комментарии (DATABASE_URL обязателен с #7, HOST в single, PUBLIC_BASE_URL — домен)

**Build:** ruff check OK · ruff format --check OK (37 файлов) · pytest (файлы #37) 56 passed · `python -m app` и `uvicorn app.main:app` → GET /health 200 · APP_MODE=bogus и scaled без REDIS_URL → понятная ошибка, код 1

**Для следующих stories:**
- #38: вернуть `/health/ready` в `app/api/health.py`, lifespan — `build_container`/start/stop; `_app_settings` можно заменить на `deps.get_app_settings`.
- #42: пока `mount_spa` — заглушка, запуск с `SERVE_FRONTEND=true` падает; до слияния #42 — `SERVE_FRONTEND=false`.
- Тесты `tests/test_health.py::test_ready_*` относятся к #38 и в #37 не запускались.
