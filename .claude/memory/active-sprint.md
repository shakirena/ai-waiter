# Active Sprint

*Обновляется Team Leads. Рабочие агенты не обновляют.*

---

## Ready for Dev

- #71 (выделено из #60: `/health/ready` 503 в prod при демо-заведении, AC-2) — kanban:ready-for-dev, G2 PASS 2026-10-25, size:s. Spec: docs/specs/feature-60-demo-data-guard.md; arch: docs/arch/feature-60-demo-data-guard.md (ADR-60.2, ADR-60.3, DEC-014); заглушка: backend/app/api/demo_data.py. `app.seed.guard.demo_tenant_exists` уже реализована в рамках #60.
  - Тело `/health/ready` без ключа для демо (ADR-60.3) подтверждено пользователем 2026-10-26.
  - Для developer/security #71: `app/api/health.py::_check` логирует `exc_info=True` (INFO из security review #60, код #56) — traceback без маскирования может содержать DSN; решить в #71 или отдельным bug.
  - Для #71: WARNING `DEMO_CHECK_FAILED` идёт через `describe_error`, который маскирует только пароль (см. LOW ниже).
  - Рекомендация для анализа #9 (комментарий в issue): в prod отклонять вход по токенам демо-заведения.

## In Development (WIP: 0/5)

*(пусто)*

## In Testing (WIP: 1/5)

- #60 (сид не загружает демо в базу с другими заведениями, AC-1) — kanban:testing, G3 PASS, G4 PASS, security:passed 2026-10-26. Код: коммит 4ff4749 (backend/app/seed/guard.py, `__main__`.py, `__init__`.py, README; тесты tests/test_seed_guard.py, tests/test_seed.py, tests/db/test_seed.py), ветка feature/60-demo-seed-guard, PR #72. Build: unit 1410 passed, db 280 passed. Doc-sync после G4 выполнен 2026-10-26 (docs/traceability.md, раздел «Реализация #60» в arch).
  - Security LOW (существует с #7): `Database.describe_error` маскирует только пароль; хост/порт/пользователь из текста ошибки драйвера могут попасть в stderr сида (код 1) — расходится с буквой NFR-1 spec («хоста или порта»). Ограничение зафиксировано в spec NFR-1 и arch (Security); исправление — отдельная задача на `describe_error`.
  - Для TC (G5): AC-1, E-1…E-6, E-10; ручной сценарий — запуск сида с `--database-url` базы с другим заведением.

## Ready to Deploy (группа feature #8: импорт меню из CSV/XLSX)

#61, #62, #63, #64, #65, #66, #67 — kanban:ready-to-deploy, qa:passed, security:passed (G5 PASS 2026-10-19). Код: ветка feature/8-menu-import, PR #69 (в main не влит); код выгрузки #67 — в репозитории кассы (ветка feature/67-ai-export-menu). Spec: docs/specs/feature-8-menu-import.md; arch: docs/arch/feature-8-menu-import.md. TC: docs/test-cases/feature-61…67-*.md (67 TC: PASS 66, из них ручных 9; не выполнен 1 — TC-62-010). Финальный прогон: 1669 passed, 3 skipped (Redis), покрытие `app` 100%, 81,5 с. Doc-sync после тестирования выполнен 2026-10-20 (docs/traceability.md, список файлов и тестов в docs/arch/feature-8-menu-import.md).
Для G6: замер NFR-5 на сервере пилота — TC-62-010 (2 000 позиций не дольше 10 с, Windows Server 2019, `single`); ревизия 0005 (`menu_sync_runs`) — `alembic upgrade head`. Метка родительской feature #8 на G5 не менялась.

## Backlog

- #70 (bug, #63/#66, NFR-8 spec #8) — итог синхронизации меню не пишется в структурированный лог; фиксируется только строкой `menu_sync_runs`. Не блокирует G5.

## Ready to Deploy (группа feature #6)

#37, #38, #39, #40, #41, #42, #43, #44, #45 — kanban:ready-to-deploy, qa:passed, security:passed (G5 PASS 2026-10-02). Код: ветка feature/6-project-scaffold (PR #47 в chore/feature-6-design). Ручные проверки для G6: TC-43-003 (запуск compose на Linux с доменом), TC-41-006 (вёрстка 360 px), TC-45-001 шаги 1-4 (чистая машина).

## Done

- Feature #7 (модель данных v1, #48–#54, #56) — PR #57 влит в main, issue #7 закрыт (kanban:done). Дефект #58 исправлен (PR #59). Остаётся ручная проверка TC-53-006 (AZ-названия, носитель языка) до показа демо заведению.
