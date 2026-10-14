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

---

## 💻 Разработка (developer)

**Branch:** feature/8-menu-import (общий worktree группы #8)
**Новые файлы:**
- backend/tests/test_money.py
- backend/tests/test_menu_snapshot.py

**Изменённые файлы:**
- backend/app/schemas/money.py — `parse_money`, `format_money`, `MoneyError(ValueError)` с `reason: MoneyErrorReason` (`invalid`/`float`/`too_many_decimals`/`negative`/`too_large`)
- backend/app/menu_sync/report.py — `SyncIssue.to_dict`, обрезка/экранирование `value` (`issue_value`, `__post_init__`), `has_errors`, `limit_issues`, `MenuSyncReport.has_errors/counts_dict/to_dict`
- backend/app/menu_sync/snapshot.py — валидаторы `SnapshotItem`, `issues_from_validation_error`, `check_snapshot`, `parse_snapshot`, `resolve_currency` (`snapshot_hash` — заглушка для #63)
- backend/tests/test_import_boundaries.py — `app.menu_sync`/`app.schemas` без `fastapi`/`app.api`; `app.core` без `app.menu_sync`

**Решения:**
- Проверка тарифов — `field_validator("prices")` с `PydanticCustomError` (`missing_default_price`, `invalid_price_tier`), а не `model_validator`: ошибка получает поле `prices.default`/`prices`. Пустая `station` → `None` — отдельный `field_validator`.
- `parse_snapshot` при ошибках формы всё равно выполняет межэлементные проверки над элементами без ошибок (`_check_valid_elements`), поэтому AC «три ошибки сразу» выполняется. Ссылка на категорию с ошибкой формы не даёт `unknown_category`; если все позиции невалидны, нет `empty_snapshot`. При неверной структуре или превышении лимитов межэлементные проверки пропускаются.
- Ошибки категорий помечаются префиксом «категория: » в сообщении (`external_id` категорий и позиций — разные пространства имён); `row` у снимка — `None` (номер строки подставляет `files`, #64).
- `MoneyError.reason` — для #64: `IssueCode` выбирается по причине, без разбора текста.
- `Decimal("8.500")` принимается (то же значение, без округления); строка `"8.505"` и `Decimal("8.505")` — `too_many_decimals`; `bool` отвергается.

**Build:** ruff check / format OK · pytest 1171 passed, 3 skipped (с db) · покрытие money.py, report.py — 100 %, snapshot.py — 99 % (не покрыта только заглушка `snapshot_hash`)
