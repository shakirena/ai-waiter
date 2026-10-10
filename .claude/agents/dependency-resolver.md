# Dependency Resolver — Shared Protocol

Этот файл читается Team Leads напрямую. Не является агентом.

---

## Синтаксис зависимостей в body issue

```
Blocked by: #10, #12
Depends on: #10
Requires: #10, #12, #15
```

---

## Алгоритм разрешения зависимостей

### Шаг 1: Извлечь зависимости

```bash
gh issue view #{N} --json body -q '.body' | grep -E "Blocked by:|Depends on:|Requires:"
```

### Шаг 2: Проверить статус каждого блокера

```bash
gh issue view #{BLOCKER_N} --json state,labels -q '{state: .state, labels: [.labels[].name]}'
```

### Шаг 3: Принять решение

| Состояние блокера | Решение |
|-------------------|---------|
| `state: closed` ИЛИ label `kanban:done` | ✅ Не блокирует — продолжай |
| `state: open` И НЕТ `kanban:done` | 🚫 BLOCKED — skip issue #{N} |
| Circular dependency (A→B→A) | 🚫 BLOCKED — эскалируй человеку |
| Depth > 10 уровней | 🚫 BLOCKED — предупреди человека |

---

## Обнаружение circular dependencies

```bash
# Построй граф: для каждого blocker проверь его blockers рекурсивно
# Если встречаешь уже просмотренный issue — circular dependency
```

При обнаружении circular — оставь comment:
```
🚫 BLOCKED: Circular dependency detected
Chain: #{A} → #{B} → #{A}
Requires manual resolution.
```

---

## Формат skip-report

Когда issue пропускается из-за блокера:

```
⏭️ Skipping #{N}: {title}
Reason: Blocked by #{BLOCKER_N} ({state})
Action: Process #{BLOCKER_N} first, then retry #{N}
```

---

## Добавление зависимостей (analyst)

При создании зависимых User Stories analyst добавляет в body:

```markdown
## Dependencies
Blocked by: #{parent-story-N}

**Reason:** Этот story зависит от модели данных, созданной в #{parent-story-N}
```
