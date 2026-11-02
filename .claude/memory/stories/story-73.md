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
