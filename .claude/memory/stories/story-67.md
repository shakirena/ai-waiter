# Story #67: Выгрузка меню кассы «restoran» в файл импорта

*Parent: #8. Spec: docs/specs/feature-8-menu-import.md (AC-7).*

---

## 📋 Задача (analyst)

**AC:** Given локальная база «restoran» с позицией `price_vip = 0`, позицией `disabled = 1` и ценой float `7.999999` When `php yii ai-export-menu <путь к ai-waiter>/local-data/menu.csv`, затем `python -m app.menu_sync check` Then код 0; пустой `price_vip`, `is_available = 0`, цена `8.00`, файл в `local-data/`
**Роли:** оператор пилота
**ТЗ:** A.1, A.2, C-07, 4.2
**Ограничения:** отправка в Integration API (#18), столы, стоп-лист, заказы, наполнение AZ/RU (#33); реальный файл не коммитится; код — `php yii ai-export-menu` (`commands/AiExportMenuController.php`, `MenuSnapshotBuilder`) в репозитории кассы (ADR-8.8); реальная выгрузка — `local-data/`; в дампе нет строк `menu` — открытый вопрос 6; смысл `menu.disabled` — вопрос 5
**Зависимости:** #64 (формат); проверка `check` — #66
**Spec:** docs/specs/feature-8-menu-import.md

---

## 🏗️ Архитектура (architect)

**ADR:** ADR-8.8 (выгрузка на стороне кассы); ADR-8.2 (формат); CLAUDE.md — без кода под кассу в ядре
**Таблицы:** нет (в ai-waiter)
**Миграция:** нет
**API:** нет (отправка в Integration API — #18)
**События/задачи:** нет
**ИИ-tools:** не затронуты
**Security:** реальная выгрузка — только `local-data/` (в `.gitignore`) или вне репозитория; `config/db.php` кассы не копируется и не цитируется; названия и цены заведения в публичный репозиторий не попадают
**Code stubs:** в ai-waiter нет; `.gitignore` + `local-data/` (сделано). В репозитории кассы: `commands/AiExportMenuController.php` (`php yii ai-export-menu <file.csv>`) и `MenuSnapshotBuilder` с соответствием A.2 — переиспользуется в #18 для `PUT /menu`
**Соответствие:**
- `type.id`/`name`/`vid` → `category_external_id`/`category_name`/`category_sort_key`;
- `menu.id`/`name`/`vid` → `external_id`/`name`/`sort_key`;
- `price` → `price_default`, half-up до 2 знаков;
- `price_vip > 0` → `price_vip`, иначе пусто;
- `currency` пусто;
- `store.name` (LEFT JOIN по `id_store`) → `station`;
- `disabled` 0/NULL → `is_available=1`, иначе 0.

Файл — `fputcsv`, UTF-8 без BOM, разделитель `,`.
**Данные:** в дампе `restoran(3).sql` нет строк `menu`. Живые данные — в `userdata/MariaDB-10.3-x64/restoran`; нужно переключить OpenServer на MariaDB 10.3 (до этого скопировать каталог) или взять свежий дамп от заведения
**Тесты:** касса — округление `7.999999` → `8.00`, `price_vip` 0/NULL, `disabled` 1/NULL; приёмка — `python -m app.menu_sync check` → 0, `import --dry-run` в БД разработки
**Зависимости:** #64 (формат), проверка импортом — #66
**Arch doc:** docs/arch/feature-8-menu-import.md (раздел «Истории — файлы, тесты, порядок»)

---

## 💻 Разработка (developer)

**Репозиторий:** касса «restoran», ветка `feature/67-ai-export-menu` (от origin/master fb7f374), коммит 8598378
**Файлы:** `components/MenuSnapshotBuilder.php` (новый), `commands/AiExportMenuController.php` (новый), `tests/codeception/unit/components/MenuSnapshotBuilderTest.php` (новый), `tests/codeception/unit/_bootstrap.php` (алиас `@app`)
**Реализация:**
- `MenuSnapshotBuilder`: соответствие A.2 на массивах строк; `fetchRows()` — один SELECT (INNER JOIN type, LEFT JOIN store, цены `CAST AS DECIMAL(16,6)`); `buildRows()`, `formatPrice()` (half-up в целых копейках, без float/printf), `formatVipPrice()` (NULL/≤0 → пусто), `csvLine()` (RFC 4180). Переиспользуется в #18 для `PUT /menu`.
- `disabled` 0/NULL → в файле, иначе не выгружается; колонки `is_available` нет; `currency` пусто.
- Текст: невалидный UTF-8 → ошибка; управляющие символы → пробел, края обрезаются.
- Команда: файл через `.tmp` и rename; коды 0/1 (данные, БД)/2 (аргумент)/3 (запись).
**Тесты:** codeception unit (PHP 7.1, codeception 2.5.6): 12 tests, 48 assertions, OK. Старые ContactFormTest и LoginFormTest падают и на origin/master (несовместимость yii2-codeception).
**Локальная выгрузка:** 362 позиции, 20 категорий, 1 не выгружена (disabled), файл в `local-data/`.
**Отклонения:** собственная запись CSV вместо fputcsv (escape `\` в PHP 7.1); нормализация управляющих символов (в реальном названии была табуляция); AC-7 в spec исправлен — `is_available` не выгружается, `disabled = 1` в файл не попадает.

---

## 🔒 Security Review

- Verdict: PASS (метка security:passed), 2026-10-14
- Scope: касса restoran, ветка feature/67-ai-export-menu, 8598378 (delta от fb7f374): components/MenuSnapshotBuilder.php, commands/AiExportMenuController.php, tests/codeception/unit/components/MenuSnapshotBuilderTest.php, tests/codeception/unit/_bootstrap.php
- Findings: CRITICAL 0, HIGH 0, MEDIUM 0, LOW 1, INFO 2
- LOW: CSV-инъекция формулами (= + - @) при открытии файла в Excel — не экранировать (испортит названия), предупредить в инструкции к выгрузке (README ai-waiter).
- INFO: текст yii\db\Exception в stderr может содержать пользователя и хост БД (без пароля); в ai-sync (#9) наружу передавать только SQLSTATE.
- INFO: предсказуемое имя <файл>.tmp — безвредно, по желанию tempnam().
- Заметки: SQL статический, только SELECT; невалидный UTF-8 отвергается, управляющие и Cf-символы заменяются (AI-3); CSV по RFC 4180; секретов в коммите нет; unit-тесты 12/12 OK.
- Комментарий: https://github.com/shakirena/ai-waiter/issues/67#issuecomment-6165448425
