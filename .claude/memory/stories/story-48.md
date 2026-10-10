# Story #48: БД — Alembic async, сессия SQLAlchemy, базовый класс моделей, фикстура db

*Parent: #7. Spec: docs/specs/feature-7-data-model.md (AC-1). Arch: docs/arch/feature-7-data-model.md (ADR-7.8–7.11, 7.13).*

---

## 💻 Реализация (developer)

**Branch:** feature/7-data-model
**Новые файлы:**
- backend/alembic.ini, backend/alembic/env.py, backend/alembic/script.py.mako, backend/alembic/versions/.gitkeep
- backend/tests/db/__init__.py, backend/tests/db/conftest.py, backend/tests/db/test_db_fixture.py, backend/tests/db/test_alembic.py
- backend/tests/test_ids.py, backend/tests/test_db_base.py, backend/tests/test_db_session.py, backend/tests/test_db_guards.py, backend/tests/test_alembic_setup.py

**Изменённые файлы:**
- backend/pyproject.toml (sqlalchemy[asyncio], asyncpg, alembic, tzdata; isort known-third-party = alembic), backend/uv.lock
- backend/app/db/{__init__,base,ids,mixins,session}.py — заглушки заменены реализацией
- backend/app/core/config.py (DATABASE_URL обязателен, DB_POOL_SIZE, DB_MAX_OVERFLOW), backend/app/core/container.py (Container.database, порядок start/stop), backend/app/api/deps.py (get_database, get_session, SessionDep)
- backend/tests/{conftest,doubles,test_config,test_container,test_lifespan,test_main,test_qa_coverage_gaps,test_scaled_worker,test_repo_artifacts}.py
- .env.example, .github/workflows/ci.yml, README.md (шаг «5. База данных», db-тесты)

**Решения:**
- `new_id()` — UUIDv7 по RFC 9562, 42-битный счётчик (12 бит rand_a + 30 бит rand_b) + 32 случайных бита; строгая монотонность в процессе (часы назад — последняя мс, переполнение — +1 мс), потокобезопасно.
- `TenantMixin.__table_args__` строит `UNIQUE (tenant_id, id)` (если есть `UUIDPrimaryKeyMixin`); свои ограничения модель задаёт в `__extra_table_args__` (словарь опций — последним).
- `Database`: движок создаётся при первом обращении к `engine`/`sessionmaker`/`ping`; `session()` — async context manager; `ping()` при ошибке → `False` и warning в лог с паролем, заменённым на `***` (без traceback), отмена не перехватывается.
- В unit-тестах autouse-фикстура `fake_database` подменяет `app.core.container.Database` на `FakeDatabase`.
- env.py: `configure_logger=False` в `config.attributes` отключает `fileConfig` (тесты), `fileConfig(..., disable_existing_loggers=False)`.
- Пустая цепочка ревизий: `alembic upgrade head`/`downgrade base` проходят без шагов и **не создают** `alembic_version`; тесты это допускают (`<= {"alembic_version"}`), корнем цепочки останется `0001` (#49).
- Команды Alembic и пересоздание схемы в фикстурах выполняются в отдельном потоке (`run_in_thread`).

**Build:** ruff OK · ruff format OK · pytest -m "not db and not scaled" 491 passed · pytest -m db 9 passed (локальная ai_waiter_test)

## 🔒 Security
Verdict: PASS. Файлы: alembic/env.py, app/db/session.py, config.py, tests/db/conftest.py, ci.yml, .env.example. Findings: CRITICAL 0, HIGH 0, LOW 2 (защита _test не проверяет хост; нет проверки TEST_DATABASE_URL != DATABASE_URL).
