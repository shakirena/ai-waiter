# Story #71: Неготовность приложения в prod при демо-заведении в базе

*Выделено из #60. Связано: #53, #56 (TC-53-003). Spec: docs/specs/feature-60-demo-data-guard.md (AC-2).*

---

## 📋 Задача (analyst)

**AC:** Given приложение запущено с `APP_ENV=prod`, а в его базе есть заведение `DEMO_TENANT_ID` When запрашивается `/health/ready` Then ответ — 503 `not_ready` без строки подключения и внутренних деталей в теле, а в лог пишется предупреждение о демо-заведении без строки подключения
**Роли:** администратор платформы (развёртывание, мониторинг `/health/ready`, логи)
**ТЗ:** NFR-4, NFR-6, NFR-8, 9.2; arch #6 (контракт `/health/ready`), ADR-7.12
**Граничные случаи (spec E-3, E-4, E-7…E-10):** `APP_ENV=dev`/`test` → поведение не меняется; prod без демо → прежние проверки; база недоступна → 503 из-за `database`, «демо нет» не выводится
**Ограничения:** проверка в сиде (#60); удаление демо; блокировка гостевых запросов по демо-токенам; чек-лист деплоя. Место и частота проверки, ключ в `checks` — решение architect
**Зависимости:** #53, #56 (влиты)
**Spec:** docs/specs/feature-60-demo-data-guard.md

---

## 🏗️ Архитектура (architect)


**Таблицы:** нет изменений (`EXISTS` по PK `tenants.id = DEMO_TENANT_ID`)
**Миграция:** нет
**API:** `GET /health/ready` при `APP_ENV=prod`: демо найдено или проверка не выполнена (ошибка/таймаут) → 503 `{"status": "not_ready", "checks": {"database": "ok", "redis": …}}` — тело и OpenAPI без изменений, ключа `demo_data` нет (ADR-60.3, подтверждено пользователем 2026-10-26). Вне prod проверка не вызывается. `/health` не меняется
**Решение (ADR-60.2):** сочетание — `DemoDataMonitor` (`app.state.demo_data_monitor`, создаёт `create_app`, `DemoDataMonitor(READINESS_CHECK_TIMEOUT)`): (1) lifespan после `start_container` один раз `await refresh(container.database)` — чтобы WARNING был в логе службы Windows без опросов; таймаут 2 с, не бросает, старт не прерывает; (2) каждый `/health/ready` в prod — `refresh` в том же `gather`, без кэша (удаление демо видно со следующего опроса). Отказ стартовать — отвергнут (ломает «стартуем при недоступной БД», цикл перезапусков службы/контейнера, Caddy `depends_on`)
**Лог:** только при смене состояния: → FOUND WARNING `DEMO_FOUND_WARNING`; → UNKNOWN WARNING `DEMO_CHECK_FAILED` + `describe_error`; FOUND → ABSENT INFO; без `exc_info`; `component="demo_data"`
**События/задачи:** нет (TaskScheduler не используется)
**ИИ-tools:** не затронуты
**Security:** тело не раскрывает наличие демо; без строки подключения; одинаково single/scaled (только `Database`). Readiness не закрывает доступ по демо-токенам — рекомендация: блокировка `DEMO_TENANT_ID` в prod в story гостевого входа
**Тесты:** unit `tests/test_demo_data.py` (новый), дополнения `tests/test_health.py`, `tests/test_lifespan.py`/`tests/test_main.py`; db — дополнения `tests/db/test_health_db.py` (AC-2, 200 без демо, удаление демо между опросами)
**Code stubs:** `backend/app/api/demo_data.py` (`DemoDataState`, `DemoDataMonitor.refresh/_transition`, тексты лога); `backend/app/seed/guard.py:demo_tenant_exists`; правки — `app/api/deps.py` (`get_demo_data_monitor`), `app/api/health.py`, `app/main.py`
**Arch doc:** docs/arch/feature-60-demo-data-guard.md (ADR-60.2, ADR-60.3); DEC-014

---

## 💻 Реализация (developer)

**Branch:** feature/60-demo-seed-guard (общая ветка с #60, PR #72; по указанию dev-lead)
**Новые файлы:**
- backend/tests/test_demo_data.py — `DemoDataMonitor`: FOUND/ABSENT/UNKNOWN, лог только при смене, маскирование пароля, таймаут, TimeoutError драйвера, CancelledError, закрытие сессии

**Изменённые файлы:**
- backend/app/api/demo_data.py — `refresh` (`database.session()` + `demo_tenant_exists` под `asyncio.timeout`; таймаут → `DEMO_CHECK_TIMEOUT_TEXT`, иное исключение → `describe_error`; `TimeoutError` драйвера при неистёкшем таймауте — тоже `describe_error`), `_transition` возвращает новое состояние; лог без `exc_info`, `component="demo_data"`
- backend/app/api/deps.py — `get_demo_data_monitor`
- backend/app/api/health.py — в prod `monitor.refresh` в общем `gather` с ping-ами; не `ABSENT` → 503, тело/OpenAPI прежние (docstring эндпоинта не менялся — он виден в OpenAPI); `_check` без traceback: БД — `Database.describe_error`, Redis — только имена классов исключений по цепочке (`_exception_names`)
- backend/app/main.py — `create_app` создаёт `app.state.demo_data_monitor`; lifespan в prod — один `refresh` внутри `try` (при отмене старта контейнер останавливается)
- backend/app/seed/guard.py — docstring `foreign_tenants_exist`: #71 гонку не закрывает, а обнаруживает её последствие
- backend/tests/doubles.py — `FakeDatabase.describe_error`
- backend/tests/test_health.py — prod FOUND/UNKNOWN/таймаут → 503 (тело ровно), ABSENT → 200, dev/test не вызывается, scaled, параллельность, OpenAPI без ключа демо, один WARNING при повторных опросах, `_check` без traceback/пароля; существующий тест Redis-ошибки переписан (`exc_info is None`)
- backend/tests/test_lifespan.py — monitor в `create_app`, `get_demo_data_monitor`, refresh один раз в prod, сбой проверки не роняет старт, вне prod не вызывается
- backend/tests/db/test_health_db.py — AC-2 (сид + prod → 503 + WARNING без пароля), prod без демо → 200, удаление демо между опросами → 200 + INFO, нет схемы → 503 при `database` ok

**Build:** ruff OK · pytest unit 1448 passed · pytest db 284 passed · frontend не затронут

---

## 🔒 Security review (#71)

**Verdict:** PASS (label `security:passed`), коммит c2332c2
**Файлы:** app/api/demo_data.py, app/api/deps.py, app/api/health.py, app/main.py, app/seed/guard.py (docstring), тесты
**Findings:** CRITICAL 0 · HIGH 0 · MEDIUM 0 · LOW 1 · INFO 4
**Заметки:** тело и OpenAPI `/health/ready` прежние, ключа `demo_data` нет; `exc_info` из `_check` убран, БД пишется через `describe_error`, Redis — только имена классов; `CancelledError` не перехватывается; lifespan при недоступной БД не падает; проверка только при `APP_ENV=prod`, отключить нельзя. LOW: публичный `/health/ready` без rate-limit, в prod два соединения на запрос, рекомендуется закрыть путь в Caddy (отдельная задача). INFO: 503 при ok-проверках косвенно выдаёт демо (это следует из AC); маскирование host/user — #73; гонка логов монитора; блокировка демо-токенов — в story гостевого входа.
