# Story #73: describe_error раскрывает детали подключения из DATABASE_URL

*Каждый агент дописывает свой раздел — не перезаписывает чужие.*

---

## 📋 Задача (analyst)

**AC:** Given `DATABASE_URL` = `postgresql+asyncpg://waiter_user:pw-s3cret@192.0.2.10:5433/waiter_db` и текст ошибки драйвера с хостом, портом, пользователем, базой и паролем. When вызывается `Database.describe_error`. Then все пять значений заменены на `***`, имя типа исключения и остальной текст сохранены.
**Роли:** администратор платформы / оператор (логи, stderr сида, отчёт menu_sync)
**ТЗ:** NFR-4, NFR-6, NFR-8; spec #60 NFR-1 (известное ограничение)
**Ограничения:** вне scope — REDIS_URL и другие секреты, IP из DNS-разрешения домена (E-13, открытый вопрос к architect), смена текста `UNPARSABLE_URL_TEXT`, G6
**Зависимости:** нет
**Spec:** docs/specs/feature-73-describe-error-mask.md
**Size:** S

---

## 🏗️ Архитектура (architect)

**Таблицы / миграция / API / env:** не меняются
**Решение (без отдельного ADR):** `make_url` → `_UrlSecrets`: пароль (userinfo и `?password=`) — подстрокой; пользователь, хосты (в том числе части через `,`, `?host=h:p`, `[v6]:p`), явный порт, база, `?port/user/database/passfile` — целым токеном `(?<!\w)…(?!\w)`, одним regex, длинные первыми, `IGNORECASE`; варианты raw/quote/quote_plus. Маскируется каждое `str(exc)` отдельно — имена типов не трогаются. Любой IPv4/IPv6-литерал маскируется по шаблону + `ipaddress` (E-13 в scope: разрешённый IP домена). Порт по умолчанию не маскируется. `UNPARSABLE_URL_TEXT` — без изменений (fail-closed и для `_url_secrets`)
**Найдено:** `?password=` и `?user=` из query переопределяют userinfo в asyncpg-диалекте; `?password=` сейчас не маскируется — закрывается здесь же
**Code stubs:** `backend/app/db/session.py` — `_UrlSecrets`, `_url_secrets`, `_mask_message`, `_mask_ip_literals` (не подключены); `backend/tests/test_db_session.py` — 5 тестов-заготовок со skip
**Arch doc:** docs/arch/feature-73-describe-error-mask.md

---

## 💻 Реализация (developer)

**Branch:** fix/73-describe-error-mask (PR #74)
**Новые файлы:** нет
**Изменённые файлы:**
- backend/app/db/session.py — `_url_secrets` (+ `_query_values`, `_host_values`, `_variants`), `_mask_message`, `_mask_ip_literals` (+ `_IPV4_CANDIDATE`, `_IPV6_CANDIDATE`, `_is_ip`), `describe_error` переключён, `_mask` удалён
- backend/app/api/health.py, backend/app/menu_sync/__main__.py — только docstring
- backend/tests/test_db_session.py — skip снят, +E-1…E-9, мультихост, сокет, `_mask_ip_literals`, оракул asyncpg
- backend/tests/test_health.py, test_demo_data.py, test_seed.py, tests/db/test_seed.py — проверки отсутствия хоста/пользователя
- docs/arch/feature-73-describe-error-mask.md — раздел «Реализация»

**Build:** ruff OK · format OK · pytest полный прогон 1776 passed, 3 skipped (unit без db/scaled — 1490 passed; db — 286 passed)
**Заметки:** часть `?host=` без скобок с двумя и более `:` считается IPv6 без порта (не разбивается на `h:p`), иначе последняя группа (`1`) стала бы токеном-портом. Документы #60 не трогались — doc-sync.

---
