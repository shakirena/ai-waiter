# Story #61: Снимок меню: модель с проверкой согласованности

*Parent: #8. Spec: docs/specs/feature-8-menu-import.md (AC-1).*

---

## 📋 Задача (analyst)

**AC:** Given заведение с валютой AZN и снимок из трёх позиций (нет цены `default`; валюта USD; ссылка на отсутствующую категорию) When снимок проверяется Then ровно три ошибки с `external_id`, полем и причиной на русском; корректный снимок того же размера проходит без ошибок
**Роли:** разработчик ядра; потребители — файловый импорт (#64–#66) и `PUT /menu` (#16)
**ТЗ:** 4.4, INT-1, INT-2, ADR-7.4 (чужая валюта отклоняет весь снимок)
**Arch:** ADR-8.1, 8.3, 8.5 — `app/schemas/money.py` (`MoneyStr`), `app/menu_sync/snapshot.py` (`MenuSnapshot`, `check_snapshot`, `parse_snapshot`, `resolve_currency`; `snapshot_hash` — в #63), `app/menu_sync/report.py`
**Ограничения:** план, запись, lock, mass_hide (#62), журнал (#63), разбор файлов (#64, #65), эндпоинт `PUT /menu` (#16)
**Зависимости:** #7 (влит)
**Spec:** docs/specs/feature-8-menu-import.md

---

## 🏗️ Архитектура (architect)

**ADR:** ADR-8.1 (единый снимок), ADR-8.2 (лимиты), ADR-8.3 (валюта); DEC-011, DEC-013
**Таблицы:** нет (без БД)
**Миграция:** нет
**API:** нет; `parse_snapshot` — будущая точка входа `PUT /menu` (#16)
**События/задачи:** нет
**ИИ-tools:** не затронуты
**Security:** `extra="forbid"`, длины и шаблоны, запрет управляющих символов (AI-3), `float` в деньгах отвергается; лимиты 500 категорий / 5000 позиций / 10 тарифов
**Code stubs:**
- `backend/app/schemas/__init__.py`, `backend/app/schemas/money.py` — `MoneyStr = Annotated[Decimal, BeforeValidator(parse_money), PlainSerializer(format_money, when_used="json")]`; `parse_money(value: object) -> Decimal`; `format_money(value: Decimal) -> str`; `MONEY_MAX = Decimal("99999999.99")`
- `backend/app/menu_sync/__init__.py` — описание пакета и границ импортов
- `backend/app/menu_sync/report.py` — `IssueCode`, `Severity`, `SyncIssue(code, message, severity, row, column, external_id, value).to_dict()`, `limit_issues(issues) -> (list, int)`; `EntityCounts`/`PriceCounts`/`MenuSyncReport` объявлены, заполняет #62
- `backend/app/menu_sync/snapshot.py` — `SnapshotCategory`, `SnapshotItem` (валидатор тарифов: `PRICE_TIER_PATTERN`, `default` обязателен), `MenuSnapshot`; `check_snapshot(snapshot, tenant_currency) -> list[SyncIssue]`; `issues_from_validation_error(exc, data) -> list[SyncIssue]`; `parse_snapshot(data, tenant_currency) -> (MenuSnapshot | None, list[SyncIssue])`; `resolve_currency(snapshot, tenant_currency) -> MenuSnapshot`. `snapshot_hash` — заглушка для #63
**Ключевое:** межэлементные проверки (дубли, ссылки, валюта) — не в `model_validator` родителя, а в `check_snapshot`: иначе ошибка одной позиции обрывает остальные проверки и AC «три ошибки сразу» не выполняется
**Тесты:** `tests/test_money.py`, `tests/test_menu_snapshot.py` (unit, Windows и Linux); граница: `app.menu_sync` не импортирует `fastapi`/`app.api`
**Зависимости:** #7; новых пакетов нет
**Arch doc:** docs/arch/feature-8-menu-import.md (раздел «Истории — файлы, тесты, порядок»)
