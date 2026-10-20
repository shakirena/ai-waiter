# Test Cases: Story #67 — Выгрузка меню кассы «restoran» в файл импорта

**Feature:** #8 «Импорт меню из CSV/XLSX» (story #67, AC-7)
**Spec:** docs/specs/feature-8-menu-import.md (FR-8, NFR-9, AC-7)
**Arch:** docs/arch/feature-8-menu-import.md (ADR-8.8, ADR-8.2)
**ТЗ:** приложение A.2 (соответствие полей кассы и снимка)
**Created:** 2026-10-19

Обозначения: **Ручной** — шаги вручную. Код выгрузки (`php yii ai-export-menu`, `commands/AiExportMenuController.php`, `components/MenuSnapshotBuilder.php`) находится в отдельном репозитории кассы, не в ai-waiter (ADR-8.8, CLAUDE.md «Независимость от кассы»); автотестов в `backend/tests` для него нет и быть не должно. Unit-тесты `MenuSnapshotBuilder` (codeception) — в репозитории кассы. Проверка на стороне ai-waiter — команда `python -m app.menu_sync check` (TC-66-002).

**Статус прогона:** приёмка выполнена пользователем на реальном меню заведения: выгрузка прошла `check` и импорт, 362 позиции импортированы успешно. Данные заведения (названия, цены, файл выгрузки) в репозиторий не попадают.

AC story (spec AC-7, редакция после решения пользователя 2026-10-13 по открытому вопросу 5): **Given** база кассы с позицией `price_vip = 0`, позицией `disabled = 1` и ценой во float `7.999999` / **When** `php yii ai-export-menu <каталог ai-waiter>/local-data/menu.csv`, затем `python -m app.menu_sync check` / **Then** код 0; у позиции с `price_vip = 0` колонка `price_vip` пустая; позиции с `disabled = 1` в файле нет (колонка `is_available` не выгружается); цена `8.00`; файл в `local-data/` (игнорируется git).

> Расхождение формулировок: в тексте issue #67 осталось «у отключённой `is_available = 0`»; действующая редакция — spec AC-7 (позиция не выгружается). TC написаны по spec.

---

## TC-67-001: Выгрузка проходит check с кодом 0

**Priority:** Critical
**Type:** Functional
**AC:** AC-7 (`check` — код 0)
**E2E Automated:** No
**Автоматизация:** Ручной (код выгрузки в репозитории кассы). Формат выгрузки со стороны ядра на вымышленных данных проверяют `backend/tests/test_menu_csv.py::test_pos_export_format_from_tz_a2_is_accepted` и `backend/tests/test_menu_sync_cli.py::test_check_accepts_pos_export_format`.
**Статус прогона:** PASS (ручная проверка, приёмка пользователем; автотесты формата — PASS 2026-10-19)

### Preconditions
- Локальная база кассы с меню; в ai-waiter выполнен `uv sync`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | В каталоге кассы: `php yii ai-export-menu <каталог ai-waiter>/local-data/menu.csv` | Код 0, файл создан (через временный файл и переименование) |
| 2 | В `backend/`: `python -m app.menu_sync check ../local-data/menu.csv` | Код 0, ошибок нет |
| 3 | Проверить формат | UTF-8 без BOM, разделитель `,`, кавычки RFC 4180, колонки по ADR-8.2, `currency` пусто |

---

## TC-67-002: price_vip = 0 → колонка price_vip пустая

**Priority:** High
**Type:** Functional
**AC:** AC-7 (пустой `price_vip`); ТЗ A.2 (`price_vip > 0` → `price_vip`, иначе пусто)
**E2E Automated:** No
**Автоматизация:** Ручной — автотест: нет в ai-waiter; unit-тест `MenuSnapshotBuilderTest` в репозитории кассы.
**Статус прогона:** PASS (ручная проверка)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Позиция с `price_vip = 0` и с `price_vip = NULL` | В файле `price_vip` пусто |
| 2 | Импорт в ai-waiter | У позиции нет тарифа `vip` (ранее существовавший удаляется, TC-62-004) |

---

## TC-67-003: disabled = 1 → позиции нет в файле

**Priority:** High
**Type:** Functional
**AC:** AC-7 (позиции с `disabled = 1` в файле нет; колонка `is_available` не выгружается)
**E2E Automated:** No
**Автоматизация:** Ручной — автотест: нет в ai-waiter; unit-тест `MenuSnapshotBuilderTest` в репозитории кассы.
**Статус прогона:** PASS (ручная проверка)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Позиции с `disabled = 0`, `NULL`, `1` | В файле только первые две |
| 2 | Проверить заголовок файла | Колонки `is_available` нет |
| 3 | Импорт в ai-waiter после того, как позиция была в меню | Позиция скрыта (`is_hidden = true`), не удалена |

---

## TC-67-004: Цена float 7.999999 → 8.00

**Priority:** High
**Type:** Functional
**AC:** AC-7 (цена `8.00`); ТЗ C-07 (округление на стороне выгрузки, half-up до двух знаков)
**E2E Automated:** No
**Автоматизация:** Ручной — автотест: нет в ai-waiter; unit-тест `MenuSnapshotBuilderTest` в репозитории кассы.
**Статус прогона:** PASS (ручная проверка)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Цена `7.999999` | `8.00` |
| 2 | `check` на результате | Нет `too_many_decimals` |

---

## TC-67-005: Файл выгрузки в local-data/ и не попадает в git

**Priority:** Critical
**Type:** Security
**AC:** AC-7 (файл в `local-data/`, игнорируется git); NFR-9 spec
**E2E Automated:** No
**Автоматизация:** Ручной — автотест: нет.
**Статус прогона:** PASS (ручная проверка, 2026-10-19: `git check-ignore -v local-data/menu.csv` → `.gitignore:26:local-data/`)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `git check-ignore -v local-data/menu.csv` | Правило `local-data/` из `.gitignore` |
| 2 | `git status` после выгрузки | Файл не отображается |
| 3 | Проверить коммиты ветки | Реальной выгрузки, названий и цен заведения нет |

---

## TC-67-006: Выгрузка импортируется: dry-run, затем import

**Priority:** High
**Type:** Functional
**AC:** AC-7; FR-8 spec (проверка — `check`, затем импорт #66)
**E2E Automated:** No
**Автоматизация:** Ручной — автотест: нет.
**Статус прогона:** PASS (ручная проверка, приёмка пользователем: 362 позиции импортированы успешно)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `python -m app.menu_sync import ../local-data/menu.csv --tenant <UUID> --dry-run` | Код 0, план: все позиции создаются |
| 2 | То же без `--dry-run` | Код 0, `applied`, позиции в меню |
| 3 | Повтор | Код 0, `unchanged` |

---

## TC-67-007: В ядре ai-waiter нет кода под кассу

**Priority:** High
**Type:** Functional (архитектура)
**AC:** ADR-8.8; CLAUDE.md «Независимость от кассы»; NFR-9 spec
**E2E Automated:** No
**Автоматизация:** Ручной — автотест: нет.
**Статус прогона:** PASS (ручная проверка, 2026-10-19)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Поиск по `backend/app` упоминаний таблиц и команд кассы (`sell2`, `yii`, `ai-export-menu`) | Нет совпадений |
| 2 | README, «Выгрузка меню из кассы „restoran“» | Команда описана с плейсхолдерами путей; предупреждение не открывать файл в Excel (CSV-инъекция) и хранить только в `local-data/` |

---

## Related TCs
- TC-64-001…TC-64-011 (формат файла, который выдаёт выгрузка)
- TC-66-001, TC-66-002 (`check` и `import`)
- TC-62-003, TC-62-004 (скрытие снятых с продажи позиций и удаление тарифа `vip`)
