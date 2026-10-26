# Story #60: Защита от загрузки демо-данных в боевую базу

*Связано: #53 (TC-53-003), #71. Spec: docs/specs/feature-60-demo-data-guard.md (AC-1).*

---

## 📋 Задача (analyst)

**AC:** Given в целевой базе есть хотя бы одно заведение, кроме демо (`DEMO_TENANT_ID`) When запускается `python -m app.seed` с `APP_ENV`, отличным от `prod` Then команда завершается с кодом 2 и сообщением на русском в stderr без строки подключения, ничего не записав в базу
**Роли:** оператор / разработчик (запускает сид)
**ТЗ:** NFR-4, NFR-8, 9.2; arch ADR-7.12; TC-53-003
**Граничные случаи (spec E-1…E-6, E-10):** пустая база → сид как раньше, код 0; только демо → идемпотентно, код 0; демо + реальное → код 2, демо-строки не обновляются; `APP_ENV=prod` → прежний отказ до подключения к базе; ошибка БД (в т.ч. нет таблицы `tenants`) → код 1 через `describe_error`
**Ограничения:** проверка в приложении (#71); удаление демо-заведения; флаг `--force`; изменение демо-данных (#53); дефект #58
**Зависимости:** #53, #56 (влиты)
**Spec:** docs/specs/feature-60-demo-data-guard.md

---

## 🏗️ Архитектура (architect)


**Таблицы:** нет изменений (читается `tenants` по PK; `tenants` — корневая, без `tenant_id`)
**Миграция:** нет
**API:** CLI `python -m app.seed` — новый отказ: в базе есть заведение кроме `DEMO_TENANT_ID` → код 2, `FOREIGN_TENANTS_REFUSAL` в stderr, stdout пуст, ничего не записано. Порядок: `APP_ENV=prod` (2, до подключения) → `Settings` (1) → транзакция: `ensure_seed_target` первым запросом → `apply_seed` → commit. Ошибка запроса проверки — код 1 через `describe_error`
**Решение (ADR-60.1):** проверка в CLI (`_run`), не в `apply_seed` (контракт загрузчика и db-тесты защиты чужих строк не меняются); READ COMMITTED без `LOCK TABLE` — окно гонки < 1 с, ручной сценарий, последствие ловит #71; `EXIT_FORBIDDEN = 2`, `EXIT_PROD_FORBIDDEN` — алиас; сообщение без числа/id/названий заведений и без строки подключения
**События/задачи:** нет
**ИИ-tools:** не затронуты
**Security:** NFR-1 — только `describe_error`; данные боевой базы не печатаются; флага отключения нет
**Тесты:** unit `tests/test_seed_guard.py` (новый), дополнения `tests/test_seed.py` — существующие CLI-тесты с подменой `apply_seed` должны подменять и `seed_cli.ensure_seed_target` (иначе запрос уйдёт в `db.invalid` → код 1); db — дополнения `tests/db/test_seed.py` (AC-1/E-4: код 2, счётчики не изменились; E-3: демо-строки не обновлены)
**Code stubs:** `backend/app/seed/guard.py` (`FOREIGN_TENANTS_REFUSAL`, `ForeignTenantsError`, `foreign_tenants_exist`, `ensure_seed_target`, `demo_tenant_exists`); правки — `app/seed/__main__.py`, `app/seed/__init__.py`, README
**Arch doc:** docs/arch/feature-60-demo-data-guard.md (ADR-60.1); DEC-014

---

## 💻 Реализация (developer)

**Branch:** feature/60-demo-seed-guard (worktree `worktree-f60-confirm`)
**Новые файлы:**
- backend/tests/test_seed_guard.py

**Изменённые файлы:**
- backend/app/seed/guard.py — `foreign_tenants_exist`, `ensure_seed_target`, `demo_tenant_exists` (для #71, по arch)
- backend/app/seed/__main__.py — `ensure_seed_target` первым запросом транзакции; `ForeignTenantsError` → код 2 до `except Exception`; `EXIT_FORBIDDEN = 2`, `EXIT_PROD_FORBIDDEN` — алиас; docstring
- backend/app/seed/__init__.py, README.md — проверка целевой базы, код 2
- backend/tests/test_seed.py — фикстура `seed_target_ok` для CLI-тестов с подменой `apply_seed`; код 2, порядок prod → проверка, ошибка БД в проверке → 1
- backend/tests/db/test_seed.py — guard на пустой / только демо / демо + другое / только другое; CLI: AC-1/E-4 (счётчики прежние, демо нет), E-3 (`updated_at` всех строк прежний)

**Build:** ruff OK · pytest unit 1410 passed · db 280 passed · frontend не затронут
