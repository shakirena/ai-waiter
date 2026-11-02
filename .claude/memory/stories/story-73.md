# Story #73: describe_error не скрывает хост, порт и пользователя из DATABASE_URL

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
