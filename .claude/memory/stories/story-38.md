# Story #38: Интерфейсы EventBus, TaskScheduler, RateLimiter с выбором реализации по режиму

*Родитель: #6. Каждый агент дописывает свой раздел — не перезаписывает чужие.*

---

## 📋 Задача (analyst)

**AC:** Given каркас backend (story A) запущен и определён `APP_MODE` When приложение стартует и запрашивает `EventBus`, `TaskScheduler`, `RateLimiter` через фабрику зависимостей Then фабрика возвращает реализацию, соответствующую `APP_MODE`, а неизвестное значение режима приводит к ошибке старта; код за пределами пакета реализаций не импортирует `redis`, `arq` и `apscheduler` напрямую (проверяется тестом на импорты)
**Роли:** разработчик
**ТЗ:** ТЗ раздел 8 (таблица режимов), NFR-8, NFR-4 (rate-limit по IP и столу)
**Ограничения:** Реализации для `single` (отдельная story); Реализации для `scaled` (отдельная story); Конкретные события и задачи бизнес-логики (эскалации, очистка диалогов)
**Зависимости:** #37
**Spec:** docs/specs/feature-6-project-scaffold.md

---

## 💻 Реализация (developer)

**Branch:** wt/38-interfaces (от feature/6-project-scaffold)
**Новые файлы:**
- backend/app/core/payload.py — `ensure_json_object`: dict со строковыми ключами (на любой глубине), строгий JSON (без NaN/Decimal/datetime/set) → иначе TypeError; общая для событий и задач
- backend/tests/doubles.py — тестовые двойники `FakeEventBus`/`FakeTaskScheduler`/`FakeRateLimiter`, `make_fake_container` (журнал вызовов, управляемые ошибки start/stop/ping, задержка ping)
- backend/tests/test_interfaces.py — ABC, `Event`, `tenant_channel`, `TaskRegistry`/`PeriodicTask`, `validate_task`/`validate_delay`, `rate_key`, `validate_hit_args`, `ensure_json_object`
- backend/tests/test_lifespan.py — lifespan (build → start → app.state.container → stop), неизвестный режим роняет старт, ошибка старта компонента не роняет, `app/api/deps.py`

**Изменённые файлы:**
- backend/app/core/events.py — `tenant_channel` (tenant_id > 0, не bool; topic непустой, без пробелов); `Event`: `tenant_id` strict > 0, payload проверяется `ensure_json_object`, `occurred_at` только aware
- backend/app/core/scheduler.py — `PeriodicTask.__post_init__` (имя + `is_valid_interval`), `TaskRegistry.task/periodic/get` (дубликаты между task и periodic — ValueError, интервал проверяется при объявлении), `validate_task(registry, name, payload)` и `validate_delay(delay)` — общие проверки `enqueue` для #39/#40
- backend/app/core/ratelimit.py — `rate_key` (части — str/int, не пустые, без `:` и пробелов), `validate_hit_args(limit, window)` — общая проверка `hit` для #39/#40
- backend/app/core/container.py — `build_container` (match по `app_mode`, ленивый импорт пакета реализаций, неизвестный режим и scaled без REDIS_URL → `ConfigError`), `start_container`/`stop_container` (порядок по ADR-1, ошибки каждого компонента логируются, остальные продолжают)
- backend/app/api/deps.py — `get_container` (нет Container → RuntimeError), `get_app_settings` (Container, до lifespan — `app.state.settings`), `get_event_bus`/`get_scheduler`/`get_rate_limiter`
- backend/app/api/health.py — `/health` через `deps.get_app_settings`; `GET /health/ready` + `ReadinessResponse`: scaled — `ping()` шины и rate-limiter-а параллельно, таймаут `READINESS_CHECK_TIMEOUT = 2.0` на проверку; single — `"skipped"`; fail → 503; детали только в лог
- backend/app/main.py — lifespan: `build_container` → `start_container` → `app.state.container` → yield → `stop_container`
- backend/tests/test_container.py — single/scaled реализации, ленивый импорт (в процессе и в чистом subprocess), ошибки старта, порядок и терпимость start/stop
- backend/tests/test_health.py — readiness в scaled на двойниках: ok, 503 без текста исключения, ping=False, таймаут, Redis недоступен на старте, single без ping, 503 в OpenAPI; заглушка-skip удалена
- backend/tests/test_import_boundaries.py — самопроверка сканера (находит app/, ловит все формы импорта)

**Build:** ruff check OK · ruff format --check OK (41 файл) · pytest: #37 (test_main, test_log, test_config) + #38 (test_interfaces, test_container, test_lifespan, test_health, test_import_boundaries, интерфейсные тесты из test_events/test_scheduler/test_ratelimit) — 175 passed; покрытие container/events/scheduler/ratelimit/payload/deps/health — 100 %

**Решения и отклонения:**
- `start_container` терпим к ошибкам **любого** компонента, не только Redis: без импорта redis вне `app/core/scaled/` отличить «Redis недоступен» нельзя. Ошибка — `logger.exception` с `component`, о неготовности сообщает `/health/ready`.
- Пока #39 не слит, реализации single — заглушки: в lifespan `InProcessTaskScheduler.start()` и `InMemoryEventBus.stop()` бросают NotImplementedError, это логируется, тесты #37 и `test_ready_in_single_mode_skips_redis` зелёные. Логи с трассой исчезнут после #39.
- Для проверок `enqueue`/`hit` добавлены функции `validate_task`, `validate_delay`, `validate_hit_args` — реализации #39/#40 обязаны вызывать их первыми (одинаковое поведение режимов).
- `rate_key` запрещает `:` в частях, поэтому IPv6 вызывающий код нормализует сам (например, `:` → `-`) — учесть в #22/#26.
- Тесты `test_events.py`, `test_scheduler.py`, `test_ratelimit.py` про реализации single (и skip-заглушки в них) не трогал — это #39; интерфейсные тесты #38 вынесены в `test_interfaces.py`, чтобы не было конфликтов слияния.

**Для следующих stories:**
- #39/#40: в начале `enqueue` — `payload = validate_task(self._registry, name, payload)` и `validate_delay(delay)`; в начале `hit` — `validate_hit_args(limit, window)`; `ping()` должен уважать отмену (readiness оборачивает его в `asyncio.timeout(2)`).
- #7: добавить ключ `"database"` в `checks` `/health/ready` (тип `ReadinessResponse.checks` уже допускает его) и поля движка/сессий в `Container`.
- #20: WebSocket-зависимости — вариант `get_container` через `HTTPConnection`.
