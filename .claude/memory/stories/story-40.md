# Story #40: Режим scaled: заготовки Redis pub/sub, arq, Redis RateLimiter

*Родитель: #6. Каждый агент дописывает свой раздел — не перезаписывает чужие.*

---

## 📋 Задача (analyst)

**AC:** Given приложение запущено с `APP_MODE=scaled` и заданным `REDIS_URL`, доступен тестовый Redis (или его in-memory-замена в юнит-тестах) When выполняются публикация события, постановка задачи в очередь и запросы к RateLimiter Then событие доставляется подписчику другого экземпляра через Redis pub/sub, задача попадает в очередь arq и обрабатывается worker-ом, а счётчик лимита общий для всех экземпляров; без `REDIS_URL` приложение в режиме `scaled` не стартует с понятной ошибкой
**Роли:** разработчик
**ТЗ:** ТЗ раздел 8, ТЗ 9.3 (перенос на VPS), NFR-4
**Ограничения:** Реализации для `single`; Бизнес-задачи worker-а (эскалации, очистка, импорт файлов); Продвинутая обработка отказов Redis, ретраи, метрики; Docker-образы и compose (отдельная story)
**Зависимости:** #38
**Spec:** docs/specs/feature-6-project-scaffold.md

---

## 💻 Реализация (developer)

**Branch:** wt/40-scaled (от feature/6-project-scaffold)
**Новые файлы:**
- backend/app/core/scaled/connection.py — ленивые фабрики клиентов `redis_from_url`, `arq_redis_from_url` (без сетевых вызовов при создании); JSON-сериализатор задач arq `serialize_job`/`deserialize_job` вместо pickle
- backend/tests/fake_redis.py — фабрики клиентов на общем `FakeServer` (несколько «процессов api» на одном Redis)
- backend/tests/test_scaled_connection.py, test_scaled_events.py, test_scaled_ratelimit.py, test_scaled_scheduler.py, test_scaled_worker.py — unit-тесты на fakeredis, без маркера
- backend/tests/test_scaled_redis.py — `@pytest.mark.scaled`, настоящий Redis из `REDIS_URL` (без него skip): событие между экземплярами, общий счётчик, задача выполнена worker-ом

**Изменённые файлы:**
- backend/app/core/scaled/events.py — `RedisEventBus`: `PUBLISH channel event.model_dump_json()`; подписка = свой `PubSub` + задача-читатель → ограниченная очередь (переполнение — отброс старого + warning); подтверждение SUBSCRIBE до выхода из `subscribe()`; некорректное сообщение пропускается; обрыв соединения завершает итератор; `stop()` завершает все подписки; `ping()` — Redis PING (не запущен → False)
- backend/app/core/scaled/ratelimit.py — `RedisRateLimiter`: MULTI/EXEC `INCR` + `PEXPIRE key ms NX` + `PTTL`; `retry_after` из PTTL; префикс `rl:`; `validate_hit_args` первым
- backend/app/core/scaled/scheduler.py — `ArqTaskScheduler` (только издатель): `validate_task` → `validate_delay` → `enqueue_job(name, payload, _job_id, _defer_by)`; дубликат по `job_id` возвращает тот же id; `cancel` под WATCH: не трогает задачу с `arq:in-progress:` ключом, иначе ZREM из очереди + DEL `arq:job:`
- backend/app/core/scaled/worker.py — `build_functions` (обработчики реестра + служебная `worker:noop`), `cron_schedule`/`build_cron_jobs` (`cron:{name}`, `unique=True`), `build_worker_settings(settings, registry)`, `on_startup`/`on_shutdown`; `WorkerSettings` — ленивый атрибут модуля (PEP 562)

**Build:** ruff check OK · ruff format --check OK (49 файлов) · тесты scaled — 82 passed, 3 skipped (маркер scaled, нет Redis), покрытие `app.core.scaled` 100 % · тесты #37/#38 — 159 passed · `import app.core.scaled.worker` OK; `WorkerSettings` собирается при `APP_MODE=scaled` + `REDIS_URL`

**Решения и отклонения:**
- `WorkerSettings` — не класс в модуле, а атрибут через `__getattr__` модуля: arq читает настройки из `settings_cls.__dict__`, поэтому `redis_settings` нельзя вычислить лениво внутри класса, а вычисление при импорте требовало бы `REDIS_URL`. Импорт модуля ничего не делает; `arq app.core.scaled.worker.WorkerSettings` (через `getattr`) получает класс, без `APP_MODE=scaled`/`REDIS_URL` — `ConfigError` с понятным текстом (адрес Redis не выводится).
- Клиенты создаются в `start()` без PING: недоступный при старте Redis не роняет api, его видно в `/health/ready`. `publish`/`hit`/`enqueue` до `start()` — RuntimeError.
- Сериализация задач arq — JSON (а не pickle по умолчанию): чтение из Redis не исполняет код. Издатель и worker используют одни и те же функции из `connection.py`.
- `keep_result=0`: результаты задач не хранятся, поэтому дедупликация по `job_id` действует, пока задача в очереди или выполняется (после выполнения тот же id можно поставить снова). `max_tries=3`, `job_timeout=5 мин`.
- `EXPIRE … NX` требует Redis 7+ (в compose — `redis:7-alpine`). Lua не используется: fakeredis без `lupa` Lua не исполняет, а MULTI/EXEC даёт ту же атомарность.
- arq не запускается без единой функции, а реестр в каркасе пуст — добавлена служебная `worker:noop` (в реестре её нет, через TaskScheduler её не поставить).
- `Worker.close()` arq использует SIGUSR1, которого нет на Windows; в unit-тесте worker на fakeredis закрывается вручную, `log_redis_info` (INFO не поддерживается fakeredis) подменён. В проде worker работает в Linux-контейнере.
- Настоящий Redis локально недоступен (Docker выключен): тесты `test_scaled_redis.py` не запускались, пройдут в Linux-джобе CI с сервисом Redis.

**Для следующих stories:**
- #20: подписчик WebSocket должен быть готов к завершению итератора (`stop()` или обрыв Redis) — переподписаться и перечитать состояние по REST.
- #23: периодические задачи — `@registry.periodic`; в scaled их выполняет только worker (`cron:{name}`, `unique=True`). Для отмены таймера — `cancel(job_id)` до начала выполнения.
- #36: worker в compose — `arq app.core.scaled.worker.WorkerSettings` с `APP_MODE=scaled` и `REDIS_URL`; Redis ≥ 7.
