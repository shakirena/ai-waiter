# Story #{N}: {title}

*Шаблон. Каждый агент дописывает свой раздел — не перезаписывает чужие.*

---

## 📋 Задача (analyst)

**AC:** Given ... When ... Then ...
**Роли:** {гость / официант / администратор / владелец платформы / коннектор}
**ТЗ:** {FR-x, INT-x, AI-x, NFR-x}
**Ограничения:** {что вне scope}
**Зависимости:** #{N} (если есть)
**Spec:** docs/specs/feature-{N}-{name}.md

---

## 🏗️ Архитектура (architect)

**Таблицы:** {table (новая/изменена), tenant_id: да}
**Миграция:** {alembic revision}
**API:** {METHOD /path — кто — коды ответов}
**События/задачи:** {EventBus-события, задачи TaskScheduler}
**ИИ-tools:** {если затронуты}
**Security:** {tenant-изоляция, роль, rate-limit}
**Code stubs:** {файлы}
**Arch doc:** docs/arch/feature-{N}-{name}.md

---

## 💻 Реализация (developer)

**Branch:** feature/{N}-{name}
**Новые файлы:**
- backend/app/...
- backend/alembic/versions/...
- backend/tests/...
- frontend/src/...

**Изменённые файлы:**
- ...

**Build:** ruff OK · pytest X passed · frontend build OK

---

## 🔒 Security Review (security-reviewer)

**Verdict:** PASS / FAIL
**Checked files:** {список}
**Findings:** CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: N
**Notes:** {ключевые наблюдения}

---

## ✅ QA (qa-lead)

**Coverage:** X% (target ≥ 95%)
**Tests:** X passed, 0 failed
**Execution time:** Xs
**TC doc:** docs/test-cases/feature-{N}-{name}.md
**TCs:** {N} total, {M} automated
