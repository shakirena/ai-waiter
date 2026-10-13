# Active Sprint

*Обновляется Team Leads. Рабочие агенты не обновляют.*

---

## Ready for Dev

### Группа feature #8: импорт меню из CSV/XLSX (G2 PASS 2026-10-13)

| # | История | size | priority | Зависит от |
|---|---|---|---|---|
| #61 | Снимок меню: модель с проверкой согласованности (`MoneyStr`, `MenuSnapshot`, `check_snapshot`) | m | high | — |
| #62 | Применение снимка меню к базе по external_id со скрытием пропавших позиций | l | high | #61 |
| #63 | Журнал синхронизаций меню с пропуском неизменённого снимка (`menu_sync_runs`, ревизия 0005) | m | high | #62 |
| #64 | Разбор CSV-файла меню в снимок с построчным отчётом ошибок | m | high | #61 |
| #65 | Разбор XLSX-файла меню в снимок (openpyxl, defusedxml) | m | medium | #64 |
| #66 | CLI-команда импорта меню из файла с режимом --dry-run (`python -m app.menu_sync`) | m | high | #63, #64 |
| #67 | Выгрузка меню кассы «restoran» в файл импорта (`php yii ai-export-menu`, код в репозитории кассы) | m | high | #64; проверка — #66 |

Порядок: #61 → (#62 ∥ #64) → #63, #65 → #66 → #67. Spec: docs/specs/feature-8-menu-import.md; arch: docs/arch/feature-8-menu-import.md (ADR-8.1…8.8, DEC-011…013). Ветка анализа: feature/8-menu-import.
До начала #62 и #63 пользователь подтверждает открытые вопросы spec: «всё или ничего»; хранение хеша в `menu_sync_runs` вместо `connectors.last_menu_hash` (уточняет ADR-7.7); защиту от массового скрытия. #67 нужны данные кассы: в дампе `restoran(3).sql` нет строк `menu`.

## In Development (WIP: 0/5)

*(пусто)*

## In Testing (WIP: 0/5)

*(пусто по историям)* Родительская feature #7 остаётся в kanban:testing — её метки на G5 не менялись; закрывается вместе с влитием PR #57.

## Ready to Deploy (группа feature #7)

#48, #49, #50, #51, #52, #53, #54, #56 — kanban:ready-to-deploy, qa:passed (G5 PASS 2026-10-13), G3, G4 и security review пройдены ранее. Код: ветка feature/7-data-model, PR #57 (в main не влит). TC: docs/test-cases/feature-48…56-*.md (57 TC: PASS 55, FAIL 1 — TC-53-007, дефект #58; не выполнен 1 — TC-53-006, ручная проверка AZ-названий носителем). Финальный прогон: с db — 1053 passed, 3 skipped, 1 xfailed; без db — 830 passed, 3 skipped; покрытие `app` 100%. Doc-sync после тестирования выполнен 2026-10-13 (docs/traceability.md, список тестов в docs/arch/feature-7-data-model.md).
Для G6: ревизия 0002 изменена в #54 — локальные БД, поднятые старой 0002, пересоздать (story-54.md); ручная проверка TC-53-006 до показа демо заведению.

## Backlog

- #58 (bug, #53 сид) — повторный `python -m app.seed` падает на `uq_visits_open_table`, если демо-визит закрыт, а на демо-столе открыт другой визит. TC-53-007, тест `tests/db/test_seed.py::test_seed_rerun_when_demo_table_has_another_open_visit` (xfail strict — снять при исправлении).

## Ready to Deploy (группа feature #6)

#37, #38, #39, #40, #41, #42, #43, #44, #45 — kanban:ready-to-deploy, qa:passed, security:passed (G5 PASS 2026-10-02). Код: ветка feature/6-project-scaffold (PR #47 в chore/feature-6-design). Ручные проверки для G6: TC-43-003 (запуск compose на Linux с доменом), TC-41-006 (вёрстка 360 px), TC-45-001 шаги 1-4 (чистая машина).

## Готово к разработке (2026-09-30)

Задача #6 (каркас проекта): истории #37-#45 в kanban:ready-for-dev. Начинать можно с #37 и #41 (без блокеров).
Spec: docs/specs/feature-6-project-scaffold.md; arch: docs/arch/feature-6-project-scaffold.md
