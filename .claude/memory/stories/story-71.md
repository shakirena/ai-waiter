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
**API:** `GET /health/ready` при `APP_ENV=prod`: демо найдено или проверка не выполнена (ошибка/таймаут) → 503 `{"status": "not_ready", "checks": {"database": "ok", "redis": …}}` — тело и OpenAPI без изменений, ключа `demo_data` нет (ADR-60.3, открытый вопрос 1 — подтверждает пользователь). Вне prod проверка не вызывается. `/health` не меняется
**Решение (ADR-60.2):** сочетание — `DemoDataMonitor` (`app.state.demo_data_monitor`, создаёт `create_app`, `DemoDataMonitor(READINESS_CHECK_TIMEOUT)`): (1) lifespan после `start_container` один раз `await refresh(container.database)` — чтобы WARNING был в логе службы Windows без опросов; таймаут 2 с, не бросает, старт не прерывает; (2) каждый `/health/ready` в prod — `refresh` в том же `gather`, без кэша (удаление демо видно со следующего опроса). Отказ стартовать — отвергнут (ломает «стартуем при недоступной БД», цикл перезапусков службы/контейнера, Caddy `depends_on`)
**Лог:** только при смене состояния: → FOUND WARNING `DEMO_FOUND_WARNING`; → UNKNOWN WARNING `DEMO_CHECK_FAILED` + `describe_error`; FOUND → ABSENT INFO; без `exc_info`; `component="demo_data"`
**События/задачи:** нет (TaskScheduler не используется)
**ИИ-tools:** не затронуты
**Security:** тело не раскрывает наличие демо; без строки подключения; одинаково single/scaled (только `Database`). Readiness не закрывает доступ по демо-токенам — рекомендация: блокировка `DEMO_TENANT_ID` в prod в story гостевого входа
**Тесты:** unit `tests/test_demo_data.py` (новый), дополнения `tests/test_health.py`, `tests/test_lifespan.py`/`tests/test_main.py`; db — дополнения `tests/db/test_health_db.py` (AC-2, 200 без демо, удаление демо между опросами)
**Code stubs:** `backend/app/api/demo_data.py` (`DemoDataState`, `DemoDataMonitor.refresh/_transition`, тексты лога); `backend/app/seed/guard.py:demo_tenant_exists`; правки — `app/api/deps.py` (`get_demo_data_monitor`), `app/api/health.py`, `app/main.py`
**Arch doc:** docs/arch/feature-60-demo-data-guard.md (ADR-60.2, ADR-60.3); DEC-014
