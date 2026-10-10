# Story #56: Проверка доступности БД в /health/ready

*Parent: #7. Blocked by: #48. Arch: docs/arch/feature-7-data-model.md (ADR-7.9, API Contracts).*

---

## 💻 Реализация (developer)

**Branch:** feature/7-data-model
**Новые файлы:**
- backend/tests/db/test_health_db.py

**Изменённые файлы:**
- backend/app/api/health.py — ключ `"database"` (`ok`/`fail`) через `container.database.ping()` в обоих режимах; проверки БД и Redis идут параллельно (`asyncio.gather`), каждая с таймаутом 2 с
- backend/tests/test_health.py — ожидания с `"database": "ok"`; новые тесты: fail в single и scaled, ошибка без деталей в теле, таймаут, параллельность, настоящий `Database` с маскированием пароля в логе, liveness без БД
- README.md — примеры ответа `/health/ready`, пояснение про `503` и `"database":"fail"`

**Решения:**
- Имя ключа — `database` (ADR-7.9, контракт API в arch doc), а не `db` из текста AC issue #56.
- Тело ответа без текстов ошибок; детали пишет `Database.ping()` (пароль → `***`, без traceback), `/health/ready` добавляет warning с `component=database`.
- `/health` (liveness) к БД не обращается.

**Build:** ruff OK · ruff format OK · pytest -m "not db and not scaled" 498 passed · pytest -m db 11 passed (локальная ai_waiter_test)
