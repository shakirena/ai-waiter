# Quality Gates — Shared Protocol

Этот файл читается Team Leads напрямую. Не является агентом.

---

## Структура каждого gate

1. Выполни все проверки из чеклиста.
2. Собери реальный вывод команд (не утверждения).
3. Оставь **Quality Gate Report** comment в issue.
4. Вынеси вердикт: PASS ✅ / NEEDS WORK ⚠️ / BLOCKED 🚫.

### Verdicts

| Verdict | Значение | Действие |
|---------|----------|----------|
| **PASS** ✅ | Все проверки выполнены | Переход в следующую колонку |
| **NEEDS WORK** ⚠️ | Мелкие проблемы | Fix inline, повтори gate |
| **BLOCKED** 🚫 | Критическая проблема | СТОП, issue остаётся в текущей колонке |

### Шаблон Quality Gate Report

```
## Quality Gate Report — G{N}: {переход}

**Issue:** #{N} — {title}
**Date:** {date}
**Enforcer:** {agent-name}

### Checks

| # | Check | Status | Evidence |
|---|-------|--------|----------|
| 1 | ... | ✅/❌ | {реальный вывод команды} |

### Verdict: PASS ✅ / NEEDS WORK ⚠️ / BLOCKED 🚫

{Комментарий если не PASS}
```

---

## G1: backlog → analysis

**Enforcer:** analysis-lead  
**Команды проверки:** `gh issue view #{N}`

| # | Проверка |
|---|----------|
| 1 | Business value понятна: зачем нужна фича, кому выгодна |
| 2 | Acceptance Criteria присутствуют (хотя бы 2-3 AC) |
| 3 | Нет дубликатов: `gh issue list --label type:feature` не показывает аналогичные |
| 4 | Тип выставлен: `type:feature`, `type:bug`, `type:tech-debt`, `type:hotfix`, `type:spike` |
| 5 | Приоритет выставлен: `priority:critical/high/medium/low` |

---

## G2: analysis → ready-for-dev

**Enforcer:** analysis-lead  
**Файлы:** `docs/specs/feature-{N}-{name}.md`, `docs/arch/feature-{N}-{name}.md`

| # | Проверка |
|---|----------|
| 1 | Spec существует и содержит FR + NFR + Given/When/Then для каждого AC |
| 2 | SD-1: каждая User Story — ровно ОДИН Given/When/Then блок |
| 3 | SD-2: каждая story проходит INVEST (Independent, Negotiable, Valuable, Estimable, Small, Testable) |
| 4 | SD-3: нет `size:xl` у stories, максимум 3 рабочих дня |
| 5 | SD-4: шаблон соблюдён (User Story + G/W/T + Вне Scope + Technical Notes) |
| 6 | SD-5: в title нет ` и ` / ` and `; в AC нет "and also" и двух Given-блоков |
| 7 | Arch doc существует: ERD, API contracts, ADR при необходимости |
| 8 | Code stubs созданы architect'ом |
| 9 | Компонент-label выставлен (`backend`/`frontend`/`ai`/`connector`/`infra`/`security`/`content`) |
| 10 | Ссылки на разделы ТЗ (FR/INT/AI/NFR) есть в spec и не противоречат `docs/TZ.md` |

---

## G3: ready-for-dev → in-development

**Enforcer:** dev-lead  
**Команды проверки:**

```bash
# Build OK (команды — раздел «Команды» в CLAUDE.md)
(cd backend && ruff check . && python -c "import app.main") && (cd frontend && npx tsc --noEmit)
# Dependency check
gh issue view #{N} | grep -E "Blocked by|Depends on|Requires"
# WIP check
gh issue list --label "kanban:in-development" | wc -l
```

| # | Проверка |
|---|----------|
| 1 | Build проходит (backend импортируется, ruff OK; frontend tsc OK) — exit code 0 |
| 2 | Все AC testable: каждый AC имеет ровно один G/W/T (SD-1) |
| 3 | Зависимости resolved: блокирующие issues закрыты или `kanban:done` |
| 4 | WIP < 5: `kanban:in-development` не более 4 открытых issues |
| 5 | Конфликтов нет: `git diff origin/main...feature/{N}` без критических конфликтов |

---

## G4: in-development → testing

**Enforcer:** dev-lead  
**Команды проверки:**

```bash
# Lint + tests + build
(cd backend && ruff check . && ruff format --check . && pytest -q)
(cd frontend && npm run lint && npx tsc --noEmit && npm run test -- --run && npm run build)
# Миграции обратимы (если есть новые)
(cd backend && alembic upgrade head && alembic downgrade -1 && alembic upgrade head)
# No orphaned files
git status --short
# No TODO/FIXME в delta
git diff main...HEAD | grep -E "^\+.*(TODO|FIXME)"
# Нет секретов/IP в delta (репозиторий публичный)
git diff main...HEAD | grep -E "^\+.*([0-9]{1,3}\.){3}[0-9]{1,3}|sk-ant-|PASSWORD=.+"
```

| # | Проверка |
|---|----------|
| 1 | Lint + unit tests + build OK — exit code 0 |
| 2 | Unit tests написаны для service/router слоя |
| 3 | Нет orphaned файлов в git (нет незакомиченного мусора) |
| 4 | Нет TODO/FIXME в новых файлах; нет секретов, IP, данных заведения |
| 4a | Новые Alembic-миграции проходят upgrade/downgrade |
| 5 | `security:passed` label выставлен security-reviewer'ом |
| 6 | Developer оставил comment с полным списком изменённых файлов |

---

## G5: testing → ready-to-deploy

**Enforcer:** qa-lead  
**Команды проверки:**

```bash
# Coverage
(cd backend && pytest -q --cov=app --cov-report=term-missing)
(cd frontend && npm run test -- --run --coverage)
# TC docs
ls docs/test-cases/feature-{N}-*.md
```

| # | Проверка |
|---|----------|
| 1 | Coverage ≥ 95% новых файлов (pytest-cov / vitest); для hotfix ≥ 50% |
| 2 | Все AC верифицированы тестами (каждый AC имеет тест) |
| 3 | TC docs созданы: `docs/test-cases/feature-{N}-{name}.md` |
| 4 | `traceability-tc.md` обновлён |
| 5 | `security:passed` label присутствует (проверить, НЕ выставлять!) |
| 6 | `qa:passed` label выставлен tester'ом |
| 7 | Все тесты выполняются < 2 мин |

**BLOCKED** немедленно если `security:passed` отсутствует.

---

## G6: ready-to-deploy → done

**Enforcer:** ops-lead  
**Команды проверки:**

```bash
# Pre-deploy tests
(cd backend && pytest -q) && (cd frontend && npm run build)
# Health check (после деплоя)
curl -f http://127.0.0.1:8000/health
# Smoke — см. agents/devops.md, шаг 4
# Logs check
docker compose -f deploy/docker-compose.yml logs --since 60s api worker | grep -E "ERROR|CRITICAL|Traceback" || echo "logs clean"
```

| # | Проверка |
|---|----------|
| 1 | `kanban:ready-to-deploy` + `qa:passed` + `security:passed` присутствуют |
| 2 | Все тесты зелёные |
| 3 | `/health` отвечает 200 |
| 4 | Smoke test основных маршрутов пройден |
| 5 | В логах нет ERROR/WARN первые 60 секунд |
| 6 | Rollback команда задокументирована в comment |
| 7 | При Production: ждать `APPROVE PRODUCTION DEPLOY` от человека |
