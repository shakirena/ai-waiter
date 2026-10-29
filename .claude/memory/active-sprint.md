# Active Sprint

*Обновляется Team Leads. Рабочие агенты не обновляют.*

---

## Ready for Dev

*(пусто)*

## In Development (WIP: 0/5)

*(пусто)*

## In Testing (WIP: 1/5)

- #71 (выделено из #60: `/health/ready` 503 в prod при демо-заведении, AC-2) — kanban:testing, security:passed, G4 PASS 2026-10-29, size:s. Код: коммит c2332c2 (backend/app/api/demo_data.py, deps.py, health.py, main.py; docstring app/seed/guard.py), security review — 1725f49; ветка feature/60-demo-seed-guard, PR #72. Build: ruff OK, unit 1448 passed, db 284 passed. Spec: docs/specs/feature-60-demo-data-guard.md (AC-2, FR-3, FR-4, NFR-1…NFR-6, E-7…E-10); arch: docs/arch/feature-60-demo-data-guard.md («Реализация #71»). Doc-sync после G4 выполнен 2026-10-29.
  - Для G5: TC-документ #71 (AC-2, E-7…E-9; случаи из arch «Для TC»: удаление демо без перезапуска → 200 + INFO, повторные опросы → один WARNING, БД недоступна при старте → `/health` 200, проверка не выполнена при `database` ok → 503); WARNING о демо в логе идёт после «Приложение запущено».
  - `_check` больше не пишет traceback (закрыт INFO security review #60): БД — `describe_error`, Redis — имена классов.
  - Security LOW: публичный `/health/ready` без rate-limit, в prod два соединения на запрос — закрыть путь в Caddy или `RateLimiter` отдельной задачей. INFO: маскирование host/user — #73.
  - Рекомендация для анализа #9 (комментарий в issue): в prod отклонять вход по токенам демо-заведения.

## Ready to Deploy (#60)

- #60 (сид не загружает демо в базу с другими заведениями, AC-1) — kanban:ready-to-deploy, qa:passed, security:passed, G5 PASS 2026-10-28 (G3, G4 PASS, security review 2026-10-26). Код: коммит 4ff4749 (backend/app/seed/guard.py, `__main__`.py, `__init__`.py, README), тесты G5 — коммит 7d3e0dd; ветка feature/60-demo-seed-guard, PR #72. TC: docs/test-cases/feature-60-demo-seed-guard.md (10 TC, PASS 10, ручной 1 — TC-60-010). Прогон: 1692 passed, 3 skipped (Redis), покрытие `app/seed` 100%, `app` 99% (непокрыт только app/api/demo_data.py — заглушка #71). Doc-sync после G5 выполнен 2026-10-28 (docs/traceability.md, раздел «Реализация #60» в arch).
  - Для G6: пункт чек-листа «APP_ENV=prod на боевом сервере»; Linux — по CI PR #72.
  - Security LOW (существует с #7): `Database.describe_error` маскирует только пароль; хост/порт/пользователь из текста ошибки драйвера могут попасть в stderr сида (код 1) — расходится с буквой NFR-1 spec («хоста или порта»). Ограничение зафиксировано в spec NFR-1, arch (Security) и TC-60-006; исправление — отдельная задача на `describe_error`.

## Ready to Deploy (группа feature #8: импорт меню из CSV/XLSX)

#61, #62, #63, #64, #65, #66, #67 — kanban:ready-to-deploy, qa:passed, security:passed (G5 PASS 2026-10-19). Код: ветка feature/8-menu-import, PR #69 (в main не влит); код выгрузки #67 — в репозитории кассы (ветка feature/67-ai-export-menu). Spec: docs/specs/feature-8-menu-import.md; arch: docs/arch/feature-8-menu-import.md. TC: docs/test-cases/feature-61…67-*.md (67 TC: PASS 66, из них ручных 9; не выполнен 1 — TC-62-010). Финальный прогон: 1669 passed, 3 skipped (Redis), покрытие `app` 100%, 81,5 с. Doc-sync после тестирования выполнен 2026-10-20 (docs/traceability.md, список файлов и тестов в docs/arch/feature-8-menu-import.md).
Для G6: замер NFR-5 на сервере пилота — TC-62-010 (2 000 позиций не дольше 10 с, Windows Server 2019, `single`); ревизия 0005 (`menu_sync_runs`) — `alembic upgrade head`. Метка родительской feature #8 на G5 не менялась.

## Backlog

- #73 (bug, security, priority:medium) — `Database.describe_error` не скрывает хост, порт и пользователя из `DATABASE_URL` (LOW из security review #60/#71; затрагивает stderr сида, `DEMO_CHECK_FAILED`, `_check` компонента `database`).
- #70 (bug, #63/#66, NFR-8 spec #8) — итог синхронизации меню не пишется в структурированный лог; фиксируется только строкой `menu_sync_runs`. Не блокирует G5.

## Ready to Deploy (группа feature #6)

#37, #38, #39, #40, #41, #42, #43, #44, #45 — kanban:ready-to-deploy, qa:passed, security:passed (G5 PASS 2026-10-02). Код: ветка feature/6-project-scaffold (PR #47 в chore/feature-6-design). Ручные проверки для G6: TC-43-003 (запуск compose на Linux с доменом), TC-41-006 (вёрстка 360 px), TC-45-001 шаги 1-4 (чистая машина).

## Done

- Feature #7 (модель данных v1, #48–#54, #56) — PR #57 влит в main, issue #7 закрыт (kanban:done). Дефект #58 исправлен (PR #59). Остаётся ручная проверка TC-53-006 (AZ-названия, носитель языка) до показа демо заведению.
