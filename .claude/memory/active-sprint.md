# Active Sprint

*Обновляется Team Leads. Рабочие агенты не обновляют.*

---

## Ready for Dev

- #60 (сид не загружает демо в базу с другими заведениями, AC-1) и #71 (выделено из #60: `/health/ready` 503 в prod при демо-заведении, AC-2) — kanban:ready-for-dev, G2 PASS 2026-10-25. Spec: docs/specs/feature-60-demo-data-guard.md; arch: docs/arch/feature-60-demo-data-guard.md (ADR-60.1…60.3, DEC-014); заглушки: backend/app/seed/guard.py, backend/app/api/demo_data.py. Истории независимы, size:s. Ветка анализа feature/60-demo-seed-guard.
  - Тело `/health/ready` без ключа для демо (ADR-60.3) подтверждено пользователем 2026-10-26.
  - Для developer #60: CLI-тесты в tests/test_seed.py, подменяющие только `apply_seed`, должны подменять и `ensure_seed_target`.
  - Для security review #71: проверить, не попадает ли DSN в traceback `exc_info=True` в `app/api/health.py::_check` (существующий код #56).
  - Окружение: в локальной `.venv` нет `openpyxl` — перед G3 выполнить `uv sync --extra scaled`.
  - Рекомендация для анализа #9 (комментарий в issue): в prod отклонять вход по токенам демо-заведения.

## In Development (WIP: 0/5)

*(пусто)*

## In Testing (WIP: 0/5)

*(пусто по историям)*

## Ready to Deploy (группа feature #8: импорт меню из CSV/XLSX)

#61, #62, #63, #64, #65, #66, #67 — kanban:ready-to-deploy, qa:passed, security:passed (G5 PASS 2026-10-19). Код: ветка feature/8-menu-import, PR #69 (в main не влит); код выгрузки #67 — в репозитории кассы (ветка feature/67-ai-export-menu). Spec: docs/specs/feature-8-menu-import.md; arch: docs/arch/feature-8-menu-import.md. TC: docs/test-cases/feature-61…67-*.md (67 TC: PASS 66, из них ручных 9; не выполнен 1 — TC-62-010). Финальный прогон: 1669 passed, 3 skipped (Redis), покрытие `app` 100%, 81,5 с. Doc-sync после тестирования выполнен 2026-10-20 (docs/traceability.md, список файлов и тестов в docs/arch/feature-8-menu-import.md).
Для G6: замер NFR-5 на сервере пилота — TC-62-010 (2 000 позиций не дольше 10 с, Windows Server 2019, `single`); ревизия 0005 (`menu_sync_runs`) — `alembic upgrade head`. Метка родительской feature #8 на G5 не менялась.

## Backlog

- #70 (bug, #63/#66, NFR-8 spec #8) — итог синхронизации меню не пишется в структурированный лог; фиксируется только строкой `menu_sync_runs`. Не блокирует G5.

## Ready to Deploy (группа feature #6)

#37, #38, #39, #40, #41, #42, #43, #44, #45 — kanban:ready-to-deploy, qa:passed, security:passed (G5 PASS 2026-10-02). Код: ветка feature/6-project-scaffold (PR #47 в chore/feature-6-design). Ручные проверки для G6: TC-43-003 (запуск compose на Linux с доменом), TC-41-006 (вёрстка 360 px), TC-45-001 шаги 1-4 (чистая машина).

## Done

- Feature #7 (модель данных v1, #48–#54, #56) — PR #57 влит в main, issue #7 закрыт (kanban:done). Дефект #58 исправлен (PR #59). Остаётся ручная проверка TC-53-006 (AZ-названия, носитель языка) до показа демо заведению.
