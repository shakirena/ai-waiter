# Agents Framework

Мультиагентная система разработки на базе Claude Code (проект **ai-waiter**: FastAPI + React/TS, см. CLAUDE.md). Иерархия Team Leads + рабочих агентов, Kanban-процесс с 6 Quality Gates, Security Review, DAG-зависимостями и автосинхронизацией GitHub Project board.

---

## Архитектура

### Иерархия агентов

```
                        ┌─────────────────┐
                        │    ЧЕЛОВЕК      │
                        │  (PM / Owner)   │
                        └────────┬────────┘
                                 │  /kanban  /swarm  /sweep  /feature  ...
                                 ▼
                  ┌──────────────────────────────────┐
                  │        Claude Code (оркестр)      │
                  │  Парсит команды → запускает       │
                  │  Team Leads.                      │
                  │  Shared: quality-gates,           │
                  │  dependency-resolver, board-sync  │
                  └──┬──────────┬──────────┬──────┬──┘
                     │          │          │      │
          ┌──────────┘ ┌────────┘  ┌───────┘  ┌──┘
          ▼            ▼           ▼           ▼
  ┌──────────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐
  │analysis-lead │ │ dev-lead │ │ qa-lead │ │ ops-lead │
  │  [G1, G2]    │ │ [G3, G4] │ │  [G5]  │ │   [G6]   │
  │  WIP: 5      │ │  WIP: 5  │ │ WIP: 5 │ │          │
  └──┬───────┬───┘ └────┬─────┘ └──┬──┬──┘ └────┬─────┘
     │       │          │          │  │           │
     ▼       ▼          ▼          ▼  ▼           ▼
 analyst architect  developer   tester test-  devops
 (sonnet) (opus)    (opus)      (sonnet) case- (sonnet)
                   [worktree]         writer
                        │            (sonnet)
                        ▼
                  security-reviewer
                    (sonnet)
                  ↑ запускает dev-lead
                    после разработки (G4)

  Отдельный поток (через /e2e):
  qa-lead → e2e-tester (opus) → e2e-tests/
```

### Два уровня

| Уровень | Агенты | Роль |
|---------|--------|------|
| **Координация** | analysis-lead, dev-lead, qa-lead, ops-lead | Управляют рабочими агентами, валидируют output, следят за WIP, enforc'ят Quality Gates |
| **Исполнение** | analyst, architect, developer, tester, test-case-writer, e2e-tester, security-reviewer, devops | Автономно выполняют задачи в своей компетенции |

**Shared-протоколы** — `quality-gates.md`, `dependency-resolver.md`, `kanban-board-sync.md` — читаются Team Leads напрямую, не являются агентами (~60K токенов экономии).

---

## Каталог агентов

### Team Leads (координация, модель: sonnet)

| Агент | Команда | Kanban-переход | Gates |
|-------|---------|----------------|-------|
| **analysis-lead** | analyst + architect | backlog → analysis → ready-for-dev | G1, G2 |
| **dev-lead** | developer(s) + security-reviewer | ready-for-dev → in-development → testing | G3, G4 |
| **qa-lead** | tester(s) + test-case-writer(s) | testing → ready-to-deploy | G5 |
| **ops-lead** | devops | ready-to-deploy → done | G6 |

### Рабочие агенты (исполнение)

| Агент | Модель | Задача | Isolation |
|-------|--------|--------|-----------|
| **analyst** | sonnet | Декомпозиция фич → User Stories + спецификации. SD-1..SD-5 правила. Kanban-метки. | — |
| **architect** | **opus** | ADR, ERD, API contracts, code stubs. Высокое качество архитектурных решений. | — |
| **developer** | **opus** | Backend + Frontend реализация по spec/arch. Unit-тесты. Build-verification. | **worktree** |
| **security-reviewer** | sonnet | OWASP Top 10, AI-specific (prompt injection, RAG), JWT/RBAC. Delta-scope только. | — |
| **tester** | sonnet | Unit-тесты ТОЛЬКО. 95% coverage новых файлов. < 2 мин. Mock всё внешнее. | — |
| **test-case-writer** | sonnet | TC-документация из specs/arch. Cross-reference sync. Обновляет traceability-tc.md. | — |
| **e2e-tester** | **opus** | Playwright Test (TypeScript) + Page Object. Из TC-docs → E2E тесты в `e2e-tests/`. Отдельно `/e2e`. | — |
| **devops** | sonnet | Docker build, CI/CD pipeline, staging/production deploy, health checks, monitoring. | — |
| **doc-sync** | sonnet | Traceability matrix. Spec↔code consistency. Запускается после разработки (dev-lead) и тестирования (qa-lead). | — |

> **Модель-стратегия:** opus — где максимальное качество кода/дизайна (architect, developer, e2e-tester). sonnet — где скорость важнее (координация, тесты, security, deploy).

---

## Kanban Flow

### Колонки

```
backlog → analysis → ready-for-dev → in-development → testing → ready-to-deploy → done
```

| Колонка | Label | Кто управляет | Что здесь |
|---------|-------|---------------|-----------|
| Backlog | `kanban:backlog` | Human / analyst | Новые фичи, баги, идеи |
| Analysis | `kanban:analysis` | analysis-lead | Декомпозиция + проектирование |
| Ready for Dev | `kanban:ready-for-dev` | analysis-lead | Stories с spec + arch doc |
| In Development | `kanban:in-development` | dev-lead | Разработка + security review |
| Testing | `kanban:testing` | qa-lead | Unit tests + TC docs |
| Ready to Deploy | `kanban:ready-to-deploy` | ops-lead | QA пройден, ждёт деплоя |
| Done | `kanban:done` | ops-lead | Задеплоено, issue закрыт |

### Двойная синхронизация (ОБЯЗАТЕЛЬНО)

При каждой смене колонки агент **обязан** обновить оба механизма:
1. **Label** — убрать старый `kanban:*`, добавить новый (через `gh issue edit`)
2. **Project Board Status** — через `gh project item-edit` (GraphQL)

**Порядок: СНАЧАЛА статус → ПОТОМ работа.**

Полный протокол: `.claude/agents/kanban-board-sync.md`.

---

## Quality Gates

Обязательная проверка при каждом переходе. Полный протокол: `.claude/agents/quality-gates.md`.

| Gate | Переход | Enforcer | Ключевые проверки |
|------|---------|----------|-------------------|
| **G1** | backlog → analysis | analysis-lead | Business value, AC, дубликаты, тип, приоритет |
| **G2** | analysis → ready-for-dev | analysis-lead | Spec (FR+NFR+Given/When/Then), SD-1..SD-5, arch doc, INVEST |
| **G3** | ready-for-dev → in-development | dev-lead | Build OK, AC testable (один G/W/T), deps resolved, WIP < 5 |
| **G4** | in-development → testing | dev-lead | Build+lint OK, unit tests написаны, `security:passed` label (security-reviewer прошёл) |
| **G5** | testing → ready-to-deploy | qa-lead | Coverage ≥ 95% (hotfix: ≥ 50%), AC верифицированы тестами, TC docs созданы, `security:passed` ОБЯЗАТЕЛЕН |
| **G6** | ready-to-deploy → done | ops-lead | Tests green, health OK, smoke OK, logs clean, rollback задокументирован |

### Verdicts

| Verdict | Значение | Действие |
|---------|----------|----------|
| **PASS** ✅ | Все проверки выполнены | Переход в следующую колонку |
| **NEEDS WORK** ⚠️ | Мелкие проблемы | Fix inline, повтори gate |
| **BLOCKED** 🚫 | Критическая проблема | СТОП, issue остаётся в текущей колонке |

Каждый gate оставляет **Quality Gate Report** comment в issue с реальным выводом команд (не утверждениями).

---

## Детальные флоу агентов

### Analysis Flow (`/analyze #N`)

```
analysis-lead
  │
  ├── G1: backlog → analysis
  │     ✓ Business value, AC, дубликаты, тип, приоритет
  │
  ├── [ПАРАЛЛЕЛЬНО]
  │     ├── analyst
  │     │     ├── Декомпозиция фичи → User Stories
  │     │     ├── Каждая story: ровно ОДИН Given/When/Then (SD-1)
  │     │     ├── Запрет: size:xl, " и ", " and ", "and also" (SD-3, SD-5)
  │     │     └── docs/specs/feature-{N}-{name}.md
  │     │
  │     └── architect
  │           ├── docs/arch/feature-{N}-{name}.md
  │           ├── ERD, API contracts, ADR
  │           └── Code stubs по модулям
  │
  ├── G2: analysis → ready-for-dev
  │     ✓ Spec полный, stories INVEST, arch doc создан, SD-1..SD-5
  │
  └── doc-sync: обновить traceability.md
```

### Development Flow (`/develop #N`)

```
dev-lead
  │
  ├── Dependency Check: blockers resolved?
  ├── WIP Check: < 5 in-development?
  ├── Conflict Detection: git diff origin/main...feature/{N}
  │
  ├── G3: ready-for-dev → in-development
  │     ✓ Build OK, AC testable, deps resolved, WIP OK
  │
  ├── developer (isolation: worktree)
  │     ├── branch: feature/{N}-{short-name}
  │     ├── Context: CLAUDE.md + story-{N}.md (📋+🏗️) вместо spec+arch+ARCHITECTURE
  │     ├── Implement: Data Layer → Service → API → Frontend
  │     ├── Unit tests для service layer
  │     ├── Build verification (compile + lint + tests)
  │     └── Commit: feat(#{N}): description
  │
  ├── G4: code checks
  │     ✓ Build+lint OK, unit tests, нет orphaned файлов, нет TODO/FIXME
  │
  ├── security-reviewer (СИНХРОННО — дожидаемся результата)
  │     ├── Scope: только delta (изменённые файлы из developer comment + git diff)
  │     ├── OWASP Top 10, AI-specific, JWT/RBAC
  │     ├── PASS → label: security:passed
  │     └── FAIL → label: security:failed
  │                 → developer исправляет в том же branch
  │                 → повтор security-reviewer (max 3 цикла)
  │                 → если 3 цикла — BLOCKED, эскалируй человеку
  │
  ├── kanban:in-development → kanban:testing + Sync Board
  │   (ТОЛЬКО после security:passed)
  │
  └── doc-sync: обновить traceability matrix
```

### Testing Flow (`/test #N`)

```
qa-lead
  │
  ├── Pre-flight: build OK? developer comment с файлами есть?
  ├── Dependency Check: blockers resolved?
  ├── security:passed label CHECK (выставлен dev-lead)
  │     └── ОТСУТСТВУЕТ → BLOCKED: не тестировать, запросить /develop
  │
  ├── [ПАРАЛЛЕЛЬНО]
  │     ├── tester (sonnet)
  │     │     ├── Unit tests ТОЛЬКО (pytest + моки / Vitest, без реальной БД)
  │     │     ├── Coverage ≥ 95% новых файлов (pytest-cov / vitest)
  │     │     ├── Execution time < 2 мин
  │     │     ├── PASS → label: qa:passed (не трогать security:*)
  │     │     └── FAIL → label: qa:failed + Bug Issue
  │     │
  │     └── test-case-writer (sonnet)
  │           ├── Читает spec + arch + issue AC
  │           ├── docs/test-cases/feature-{N}-{name}.md
  │           ├── Для каждого AC: happy path + error case + RBAC test
  │           ├── Cross-reference sync: обновить Related TCs
  │           └── Обновить docs/test-cases/traceability-tc.md
  │
  ├── G5: testing → ready-to-deploy
  │     ✓ Coverage ≥ 95%, AC verified, TC docs created, security:passed present
  │     ✗ BLOCKED если security:passed label отсутствует
  │
  ├── PASS → kanban:testing → kanban:ready-to-deploy + qa:passed
  ├── FAIL → kanban:testing → kanban:in-development + qa:failed
  │
  └── doc-sync: обновить traceability (TC → тесты mapping)
```

### Deploy Flow (`/deploy staging`)

```
ops-lead
  │
  ├── G6 Pre-flight
  │     ✓ kanban:ready-to-deploy + qa:passed + security:passed
  │     ✓ Build проходит
  │     ✗ СТОП если любой check fails
  │
  ├── devops (sonnet)
  │     ├── Pre-deploy: тесты + build
  │     ├── Docker build / artifact
  │     ├── Deploy (команды из CLAUDE.md)
  │     ├── Health check endpoint
  │     ├── Smoke test основного API
  │     └── Logs check (нет ERROR/WARN в первые 60s)
  │
  ├── G6 Post-deploy
  │     ✓ Health OK, Smoke OK, Logs clean
  │     ✗ Health FAIL → НЕМЕДЛЕННЫЙ ROLLBACK (BLOCKED)
  │
  ├── kanban:ready-to-deploy → kanban:done + deployed:staging (issue closed)
  └── Все stories фичи done → закрыть parent feature issue

  Production:
  ├── ops-lead готовит Production Checklist + rollback команду в comment
  ├── Пишет: "Awaiting approval. Post `APPROVE PRODUCTION DEPLOY` to proceed."
  ├── ЖДЁТ человека (не продолжает без комментария)
  └── После `APPROVE PRODUCTION DEPLOY` → запускает devops для prod
```

### Hotfix Flow

Hotfix пропускает G1 и G2 (analysis phase). Входит напрямую в G3.

```
Условия: type:hotfix + priority:critical + kanban:ready-for-dev (MANAGER выставил вручную)

G3 (dev-lead)
  → developer реализует
  → G4 (build + code checks)
  → security-reviewer ОБЯЗАТЕЛЕН (coverage threshold снижен, но security нет)
  → G5 (qa-lead, coverage ≥ 50%)
  → G6 (ops-lead)
```

### E2E Flow (`/e2e #N`)

```
Отдельный поток — не блокирует деплой stories.

qa-lead (или прямой вызов)
  → e2e-tester (opus)
        ├── Читает docs/test-cases/feature-{N}-{name}.md
        ├── Создаёт/обновляет Page Objects в e2e-tests/
        ├── Генерирует E2E спеки (Playwright Test, TypeScript; LLM — фейковый провайдер)
        ├── Только [data-testid='*'] селекторы
        ├── Critical + High TCs автоматизируются обязательно
        └── Обновляет TC traceability (E2E Automated: Yes)
```

---

## Правила декомпозиции (SD-1..SD-5)

Каждая User Story обязана следовать этим правилам. Проверяются на G2.

| Правило | Суть |
|---------|------|
| **SD-1** | Ровно ОДИН Given/When/Then блок. Не больше одного сценария. |
| **SD-2** | INVEST: Independent, Negotiable, Valuable, Estimable, Small, Testable |
| **SD-3** | Максимум 3 рабочих дня. `size:xl` ЗАПРЕЩЁН для stories. |
| **SD-4** | Обязательный шаблон: User Story + один G/W/T + Вне Scope + Technical Notes |
| **SD-5** | Запрещённые паттерны в title: ` и `, ` and `. В AC: "and also", два Given-блока. |

---

## DAG-зависимости

Синтаксис в body issue:

```
Blocked by: #10, #12
Depends on: #10
Requires: #10, #12, #15
```

| Состояние | Действие |
|-----------|----------|
| Blocker closed / kanban:done | Не блокирует — можно обрабатывать |
| Blocker open и не done | BLOCKED — skip, не запускай агента |
| Circular dependency | Manual intervention — нельзя авторазрешить |
| Depth > 10 уровней | BLOCKED — предупреди человека |

Интеграция:
- **analyst** добавляет `Blocked by: #N` при создании зависимых stories
- **dev-lead** и **qa-lead** — dependency check перед запуском агентов (Step 2.5)
- **`/board`** — визуализация заблокированных issues

---

## Label System

### Kanban-колонки

| Label | Цвет | Колонка |
|-------|------|---------|
| `kanban:backlog` | зелёный | Backlog |
| `kanban:analysis` | синий | Analysis |
| `kanban:ready-for-dev` | фиолетовый | Ready for Dev |
| `kanban:in-development` | жёлтый | In Development |
| `kanban:testing` | розовый | Testing |
| `kanban:ready-to-deploy` | оранжевый | Ready to Deploy |
| `kanban:done` | тёмно-зелёный | Done |

### Типы

| Label | Когда |
|-------|-------|
| `type:feature` | Feature Request (родительский issue) |
| `type:epic` | Эпик (несколько features) |
| `type:story` | User Story (дочерний issue) |
| `type:bug` | Bug Report |
| `type:tech-debt` | Технический долг |
| `type:hotfix` | Срочное исправление (пропускает G1/G2) |
| `type:spike` | Research / исследование |

### Приоритеты, размеры, компоненты

| Группа | Labels |
|--------|--------|
| Приоритеты | `priority:critical`, `priority:high`, `priority:medium`, `priority:low` |
| Размеры | `size:xs` (< 2ч), `size:s` (пол-дня), `size:m` (1–2 дня), `size:l` (3–5 дней) |
| Компоненты | `backend`, `frontend`, `ai`, `connector`, `infra`, `security`, `content` (существующие метки репозитория, без префикса) |

### Статусы

| Label | Выставляет | Значение |
|-------|-----------|----------|
| `qa:in-progress` | qa-lead / tester | QA в процессе |
| `qa:passed` | qa-lead | Unit tests прошли, coverage ≥ 95% |
| `qa:failed` | qa-lead / tester | Tests упали |
| `security:passed` | **security-reviewer** (через dev-lead) | Security review пройден |
| `security:failed` | **security-reviewer** (через dev-lead) | Найдены CRITICAL/HIGH уязвимости |
| `deployed:staging` | devops | Задеплоено на staging |
| `deployed:production` | devops | Задеплоено на production |

> **ВАЖНО:** `security:*` labels выставляет ТОЛЬКО security-reviewer. qa-lead ТОЛЬКО проверяет наличие — никогда не пишет эти labels.

---

## WIP Limits

| Колонка | Лимит | Кто проверяет |
|---------|-------|---------------|
| In Development | **5** | dev-lead перед запуском developer(ов) |
| Testing | **5** | qa-lead перед запуском tester(ов) |

При превышении — Team Lead предупреждает и НЕ берёт новые задачи.

---

## Команды (Skills)

### Kanban pipeline

| Команда | Агент | Что делает |
|---------|-------|------------|
| `/feature <описание>` | analyst | Создаёт GitHub Issue с AC, приоритетом, размером |
| `/analyze #N` | **analysis-lead** → analyst + architect | Декомпозиция → Stories + Spec + Architecture. Gates: G1, G2 |
| `/develop #N [#M ...]` | **dev-lead** → developer(s) + security-reviewer | Реализация + security review. Gates: G3, G4 |
| `/test #N [all]` | **qa-lead** → tester + test-case-writer | Unit tests (95%) + TC docs. Gate: G5 |
| `/deploy [staging\|production\|all]` | **ops-lead** → devops | Build → deploy → health check. Gate: G6 |
| `/e2e #N [all]` | **e2e-tester** | E2E автотесты из TC docs в `e2e-tests/` |

### Автоматизация

| Команда | Что делает |
|---------|------------|
| `/kanban <описание>` | Полный pipeline: Feature → Analysis → Develop → Test → Deploy (все 6 gates) |
| `/swarm [develop\|test\|analyze\|dry-run]` | Все Team Leads ПАРАЛЛЕЛЬНО по всей доске |
| `/sweep [колонка\|dry-run]` | Автопилот right-to-left (deploy → test → dev → analysis) |
| `/board` | Kanban-доска: колонки, WIP, блокировки, зависимости, метрики |
| `/pick <колонка>` | Взять следующую задачу по приоритету (critical → high → medium → low) |

### Настройка

| Команда | Что делает |
|---------|------------|
| `/setup-board` | Создать 29 workflow-меток + настроить Status-колонки доски #7. Один раз. |
| `/init` | Полная инициализация агентской системы на проекте. Один раз. (Не путать со встроенным `/init` для CLAUDE.md.) |
| `/refresh-agents` | Синхронизировать агентов из другого проекта-источника |

### /sweep vs /swarm

| | `/sweep` | `/swarm` |
|---|----------|----------|
| Порядок | Right-to-left (сначала deploy, потом test, потом dev) | Все Team Leads одновременно |
| Безопасность | Порядок гарантирован, минимум race conditions | Возможны race conditions на labels |
| Когда | Обычная обработка всей доски | Нужна максимальная скорость |

---

## Agent Memory System

Shared persistent memory для мультиагентной системы. Экономит ~60-70% токенов на context loading.

### Структура

```
.claude/memory/
├── project-summary.md     # ~500 токенов сжатый ARCHITECTURE.md. Читают все агенты вместо полного файла.
├── active-sprint.md       # Текущий WIP (In Development / Testing). Обновляет dev-lead + qa-lead.
├── decisions.md           # Кросс-story архитектурные решения. Дописывает architect + developer.
└── stories/
    ├── _template.md       # Шаблон для новых stories
    └── story-{N}.md       # Аккумулируется по pipeline. Каждый агент дописывает свой раздел.
```

### Accumulating story-N.md

```
analyst      → создаёт story-N.md, раздел 📋 Задача (~200 токенов)
architect    → дописывает раздел 🏗️ Архитектура (~300 токенов)
developer    → дописывает раздел 💻 Реализация (~300 токенов)
security     → дописывает раздел 🔒 Security Review (~100 токенов)
qa-lead      → дописывает раздел ✅ QA (~150 токенов)
```

Итог: ~1050 токенов вместо spec(3K)+arch(3K)+issue(2K)+ARCHITECTURE(8K) = **-15K токенов на story**.

### Obsidian Integration

Папка `.claude/memory/` открывается как Obsidian Vault (File → Open Folder as Vault). Плагины Dataview, Tasks, Graph View — для навигации между stories и decisions.

### Правила

- Агенты **дописывают** свой раздел — не перезаписывают чужие
- `decisions.md` — только решения, влияющие на **2+ stories**
- `active-sprint.md` — обновляют Team Leads, не рабочие агенты
- Память читается ПЕРВОЙ (до ARCHITECTURE.md и specs)

---

## Артефакты

| Этап | Агент | Артефакт |
|------|-------|----------|
| Analysis | analyst | `docs/specs/feature-{N}-{name}.md` |
| Analysis | architect | `docs/arch/feature-{N}-{name}.md` |
| Analysis | architect | Code stubs (по модулям проекта, стиль из CLAUDE.md) |
| Development | developer | Backend + Frontend код |
| Development | developer | DB migrations |
| Development | developer | `.claude/handoffs/story-{N}-dev.md` (для QA) |
| Memory | analyst | `.claude/memory/stories/story-{N}.md` (раздел 📋) |
| Memory | architect | `.claude/memory/stories/story-{N}.md` (раздел 🏗️) |
| Memory | developer | `.claude/memory/stories/story-{N}.md` (раздел 💻) |
| Memory | security-reviewer | `.claude/memory/stories/story-{N}.md` (раздел 🔒) |
| Memory | qa-lead | `.claude/memory/stories/story-{N}.md` (раздел ✅) |
| Security | security-reviewer | Comment в issue: Security Review Report |
| Security | security-reviewer | Bug issues (type:bug, priority:critical) при FAIL |
| Testing | tester | Unit test файлы |
| Testing | test-case-writer | `docs/test-cases/feature-{N}-{name}.md` |
| Testing | test-case-writer | `docs/test-cases/traceability-tc.md` |
| E2E | e2e-tester | `e2e-tests/src/` (Page Objects + Scenarios) |
| Deploy | devops | Docker / CI configs |
| All gates | Team Leads | Quality Gate Report comments в issues |
| All stages | doc-sync | `docs/traceability.md` |

---

## Принципы системы

1. **Автономность** — каждый агент Senior-уровня, работает без подтверждений от человека
2. **Иерархия** — Team Leads координируют и enforc'ят gates; рабочие агенты исполняют
3. **Status-first** — СНАЧАЛА обновить kanban-статус (label + board), ПОТОМ начинать работу
4. **Security-as-review** — security-reviewer запускается dev-lead после кода (до Testing), не в QA
5. **One feature, one branch, one PR** — все stories фичи в `feature/{N}-{name}`, один PR
6. **Evidence-driven** — Quality Gate Reports содержат реальный вывод команд, не утверждения
7. **Параллелизм** — независимые stories всегда параллельно; developer в worktree
8. **WIP-контроль** — строго ≤ 5 in-development, ≤ 5 in-testing
9. **Label ownership** — каждый label пишет только один агент (см. таблицу Label System)
10. **DAG-aware** — зависимые stories автоматически skip'ятся если blocker не resolved
11. **Circuit breaker** — max 3 попытки исправить (security fix loop, build fix) → эскалация человеку
12. **Build gate** — developer, tester, devops проверяют build перед ключевыми действиями
13. **Unit-only testing** — tester пишет ТОЛЬКО unit tests. Integration → developer. E2E → /e2e. Load → отдельно.
14. **Memory-first context loading** — агенты читают `.claude/memory/story-N.md` (~800 токенов) ВМЕСТО spec+arch+issue+ARCHITECTURE (~16K токенов). Экономия 90K токенов на 3 stories × pipeline.
15. **Accumulating story files** — каждый агент дописывает свой раздел в `story-N.md`. Следующий агент читает весь файл — не перечитывает первоисточники.

---

## Структура файлов

```
.claude/
├── AGENTS_FRAMEWORK.md          # ← этот файл
├── settings.json                # Permissions (gh, git, build tools, docker, ...)
├── agents/
│   │   — Team Leads —
│   ├── analysis-lead.md         # [sonnet] Координирует analyst + architect. G1, G2.
│   ├── dev-lead.md              # [sonnet] Координирует developer(s) + security-reviewer. G3, G4.
│   ├── qa-lead.md               # [sonnet] Координирует tester + test-case-writer. G5.
│   ├── ops-lead.md              # [sonnet] Координирует devops. G6.
│   │   — Рабочие агенты —
│   ├── analyst.md               # [sonnet] Декомпозиция, спецификации, Kanban-метки
│   ├── architect.md             # [opus]   ADR, ERD, API contracts, code stubs
│   ├── developer.md             # [opus]   Backend + Frontend. Worktree isolation.
│   ├── security-reviewer.md     # [sonnet] OWASP, AI-specific, JWT/RBAC. Через dev-lead.
│   ├── tester.md                # [sonnet] Unit tests ONLY. 95% coverage. < 2 мин.
│   ├── test-case-writer.md      # [sonnet] TC-документация. Cross-reference sync.
│   ├── e2e-tester.md            # [opus]   Playwright (TS) E2E. Только /e2e.
│   ├── devops.md                # [sonnet] Docker, CI/CD, deploy, monitoring
│   ├── doc-sync.md              # [sonnet] Traceability matrix. Spec↔code consistency.
│   ├── integration-tester.md    # [opus]   НЕ АКТИВЕН. Будущее использование.
│   │   — Shared-протоколы (не агенты) —
│   ├── quality-gates.md         # G1–G6 чеклисты, verdicts, report template
│   ├── dependency-resolver.md   # DAG-зависимости, circular detection, auto-dispatch
│   └── kanban-board-sync.md     # GraphQL-мутации для Project board sync
├── memory/                      # Shared persistent memory (Obsidian-compatible)
│   ├── project-summary.md       # Сжатый ARCHITECTURE.md (~500 токенов)
│   ├── active-sprint.md         # Текущий WIP — обновляют Team Leads
│   ├── decisions.md             # Кросс-story архитектурные решения
│   └── stories/
│       ├── _template.md         # Шаблон
│       └── story-{N}.md         # Аккумулируется: 📋🏗️💻🔒✅
└── commands/
    ├── feature.md               # /feature  — Feature Request
    ├── analyze.md               # /analyze  — Analysis (analysis-lead)
    ├── develop.md               # /develop  — Development (dev-lead)
    ├── test.md                  # /test     — Testing (qa-lead)
    ├── deploy.md                # /deploy   — CI/CD & Deploy (ops-lead)
    ├── e2e.md                   # /e2e      — E2E автотесты (e2e-tester)
    ├── kanban.md                # /kanban   — Full Pipeline (все 5 этапов)
    ├── swarm.md                 # /swarm    — Все Team Leads параллельно
    ├── sweep.md                 # /sweep    — Right-to-left автопилот
    ├── board.md                 # /board    — Kanban-доска + метрики
    ├── pick.md                  # /pick     — Взять задачу по приоритету
    ├── setup-board.md           # /setup-board — Init 29 labels + board
    ├── init.md                  # /init     — Полная инициализация системы
    └── refresh-agents.md        # /refresh-agents — Синхронизация агентов
```

---

## Настройка на новом проекте

> **ai-waiter: инициализировано 2026-09-30.** Агенты и команды взяты из `paint-shop-cms` и адаптированы под стек проекта. Остались шаги 3–4 (GitHub) и раздел «Команды» в CLAUDE.md после issue #6.

### 1. Минимальный settings.json

```json
{
  "permissions": {
    "allow": [
      "Bash(git *)", "Bash(gh *)",
      "Bash(python *)", "Bash(pytest *)", "Bash(ruff *)", "Bash(alembic *)", "Bash(npm *)", "Bash(npx *)",
      "Bash(docker *)", "Bash(docker-compose *)", "Bash(docker compose *)",
      "Bash(grep *)", "Bash(find *)", "Bash(cat *)", "Bash(ls *)",
      "Bash(mkdir *)", "Bash(cp *)", "Bash(mv *)", "Bash(curl *)"
    ],
    "deny": [
      "Bash(rm -rf /)", "Bash(git push --force)"
    ]
  }
}
```

### 2. CLAUDE.md — обязательные разделы

Агенты читают CLAUDE.md для получения контекста проекта. Обязательно указать:
- Стек (язык, фреймворк, БД, очереди)
- Структура модулей / monorepo layout
- Build-команды (`ruff`, `pytest`, `npm run build` и т.д.)
- Test-команды (unit, integration)
- Ролевая модель (RBAC: какие роли, какие права)
- Deploy-команды / инфраструктура

### 3. GitHub CLI и scopes

```bash
gh auth login
gh auth refresh -s repo,project,read:org
gh auth status  # проверить scopes
```

### 4. Инициализация доски

```bash
/setup-board   # создаёт 29 меток + настраивает колонки доски #7
```

### 5. Первая фича

```bash
/feature <описание новой фичи>
/analyze #1
/develop #2 #3 #4
/test all
/deploy staging
```

Или всё одной командой: `/kanban <описание>`

---

## Типичные сценарии

| Задача | Команды |
|--------|---------|
| Новая фича от идеи до staging | `/kanban <описание>` |
| Новая фича пошагово | `/feature` → `/analyze` → `/develop` → `/test` → `/deploy` |
| Обработать всю доску безопасно | `/board` → `/sweep dry-run` → `/sweep` |
| Максимальная параллельность | `/swarm` |
| Несколько stories параллельно | `/develop #3 #4 #5` → `/test all` → `/deploy staging` |
| Зависимые stories (Entity→Service→API) | `/develop #3 #4 #5 #6` (dev-lead сам определит порядок) |
| Срочный hotfix | Поставь `type:hotfix` + `kanban:ready-for-dev` → `/develop #N` → `/test #N` → `/deploy staging` |
| E2E тесты после деплоя | `/e2e #N` или `/e2e all` |
| Утренний check-in | `/board` |
| Разблокировать доску | `/board` → найти blocked → `/develop #blocker` → `/sweep` |
