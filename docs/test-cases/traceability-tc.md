# Test Case Traceability Matrix

Обновлено: 2026-10-02. Feature #6 «Каркас проекта», stories #37–#45. Столбец «Авто» — где тест выполняется автоматически; «Прогон» — результат на дату обновления.

| TC ID | Title | Feature | AC | Priority | E2E Automated | Авто (unit/static) | Прогон |
|-------|-------|---------|-----|----------|---------------|--------------------|--------|
| TC-37-001 | Запуск backend и ответ /health в режиме single | #37 | AC-1 | Critical | No | test_health.py, test_main.py | PASS |
| TC-37-002 | Некорректный APP_MODE прерывает запуск | #37 | AC-1 | Critical | No | test_config.py, test_main.py | PASS |
| TC-37-003 | Отсутствие обязательной переменной в scaled | #37 | AC-1 | High | No | test_config.py | PASS |
| TC-37-004 | Безопасные значения по умолчанию и секреты | #37 | AC-1, NFR-2 | High | No | test_config.py, test_repo_artifacts.py | PASS |
| TC-37-005 | Готовность /health/ready, устойчивость к Redis | #37 | AC-1 | Medium | No | test_health.py | PASS |
| TC-37-006 | Структурированные логи, ленивое создание app | #37 | AC-1, NFR-4 | Medium | No | test_log.py, test_main.py | PASS |
| TC-38-001 | Фабрика возвращает реализации по APP_MODE | #38 | AC-2 | Critical | No | test_container.py, test_lifespan.py | PASS |
| TC-38-002 | Неизвестный режим и scaled без REDIS_URL | #38 | AC-2 | Critical | No | test_container.py, test_lifespan.py | PASS |
| TC-38-003 | Границы импортов redis, arq, apscheduler | #38 | AC-2, NFR-7 | High | No | test_import_boundaries.py | PASS |
| TC-38-004 | Контракты интерфейсов и событий | #38 | AC-2 | High | No | test_interfaces.py | PASS |
| TC-39-001 | Сквозной сценарий single без Redis | #39 | AC-3 | Critical | No | test_single_mode.py, test_events.py, test_scheduler.py, test_ratelimit.py | PASS |
| TC-39-002 | Изоляция тенантов и медленный подписчик | #39 | AC-3 | High | No | test_events.py | PASS |
| TC-39-003 | Планировщик: идемпотентность, отмена, остановка | #39 | AC-3 | High | No | test_scheduler.py | PASS |
| TC-39-004 | RateLimiter в памяти: окно и память | #39 | AC-3 | High | No | test_ratelimit.py | PASS |
| TC-40-001 | Событие, задача arq, общий счётчик лимита | #40 | AC-4 | Critical | No | test_scaled_*.py (fakeredis), test_scaled_redis.py (Redis, CI) | PASS (fakeredis); настоящий Redis — только CI |
| TC-40-002 | scaled без REDIS_URL, защита адреса | #40 | AC-4 | Critical | No | test_scaled_worker.py, test_container.py | PASS |
| TC-40-003 | Отказоустойчивость Redis-реализаций | #40 | AC-4 | High | No | test_scaled_events.py, test_scaled_scheduler.py, test_scaled_ratelimit.py, test_scaled_connection.py | PASS |
| TC-41-001 | Проверки frontend: lint, тесты, сборка | #41 | AC-5 | Critical | No | CI frontend (2 ОС) | PASS |
| TC-41-002 | Маршруты /t/:token, /staff, /admin | #41 | AC-5 | Critical | No | App.test.tsx, main.test.tsx | PASS |
| TC-41-003 | Неизвестные маршруты и отсутствие #root | #41 | AC-5 | Medium | No | App.test.tsx, main.test.tsx | PASS |
| TC-41-004 | PWA: манифест и service worker | #41 | AC-5 | High | No | pwa-config.test.ts | PASS |
| TC-41-005 | Клиент API: /health и ошибки | #41 | AC-5 | Medium | No | client.test.ts | PASS |
| TC-41-006 | Вёрстка на ширине 360 px | #41 | AC-5, NFR-3 | Medium | No | — (ручной) | НЕ ВЫПОЛНЕН |
| TC-42-001 | SPA fallback для маршрутов интерфейсов | #42 | AC-6 | Critical | No | test_spa.py | PASS |
| TC-42-002 | Кэширование статики | #42 | AC-6 | High | No | test_spa.py | PASS |
| TC-42-003 | Пути API не перехватываются | #42 | AC-6 | Critical | No | test_spa.py | PASS |
| TC-42-004 | Защита от обхода каталога | #42 | AC-6, NFR-2 | Critical | No | test_spa.py | PASS |
| TC-42-005 | Отсутствует каталог сборки | #42 | AC-6 | High | No | test_spa.py | PASS |
| TC-43-001 | Состав сервисов, healthcheck, тома (статика) | #43 | AC-7 | Critical | No | test_repo_artifacts.py | PASS |
| TC-43-002 | Сетевая изоляция и безопасность контейнеров | #43 | AC-7, NFR-2 | High | No | test_repo_artifacts.py | PASS |
| TC-43-003 | Запуск стека на Docker, /health по домену | #43 | AC-7 | Critical | No | — (ручной, Linux-хост) | НЕ ВЫПОЛНЕН |
| TC-44-001 | Матрица ОС и состав шагов CI | #44 | AC-8 | Critical | No | test_repo_artifacts.py; PR #47 CI | PASS |
| TC-44-002 | Падение шага делает проверку красной | #44 | AC-8 | High | No | test_repo_artifacts.py | PASS |
| TC-44-003 | Безопасность workflow | #44 | AC-8, NFR-2 | High | No | test_repo_artifacts.py | PASS |
| TC-45-001 | Локальный запуск по README (single) | #45 | AC-9 | Critical | No | — (ручной) | ЧАСТИЧНО (шаги 5–7) |
| TC-45-002 | Раздел scaled и команды проверок совпадают | #45 | AC-9 | High | No | test_repo_artifacts.py | PASS |
| TC-45-003 | README без секретов и адресов заведения | #45 | AC-9, NFR-2 | High | No | test_repo_artifacts.py | PASS |

Итого: 37 TC (PASS 34; не выполнены 2: TC-41-006, TC-43-003; частично 1: TC-45-001).

## Cross-reference между историями
- #37 → #38 (Settings → фабрика), #42 (`FRONTEND_DIST_DIR`)
- #38 → #39, #40 (реализации интерфейсов)
- #40 → #43 (worker и Redis в compose)
- #41 → #42 (сборка раздаётся backend-ом)
- #42, #43 → #45 (README описывает запуск)
- #37, #41 → #44 (CI выполняет их проверки)
