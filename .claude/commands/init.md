# /init (agents) — Полная инициализация агентной системы

Инициализировать мультиагентную систему на проекте. **Выполняется один раз.**

> Примечание: эта команда инициализирует агентную систему, не путать со встроенной командой `/init` для создания CLAUDE.md.

## Что делает

1. Проверяет структуру `.claude/` директории
2. Создаёт недостающие директории
3. Инициализирует memory файлы
4. Проверяет GitHub CLI авторизацию
5. Проверяет build инструменты
6. Запускает `/setup-board` если labels не созданы

## Алгоритм

### 1. Проверить структуру

```bash
ls .claude/agents/
ls .claude/commands/
ls .claude/memory/
ls .claude/memory/stories/
```

### 2. Инициализировать memory

```bash
# project-summary.md — если не существует
# Создать из CLAUDE.md + текущей структуры проекта
cat CLAUDE.md
ls backend/ frontend/ 2>/dev/null
```

Создать `.claude/memory/project-summary.md` (если нет) — сжатый контекст проекта.

### 3. Проверить GitHub CLI

```bash
gh auth status
gh repo view --json name,owner
```

### 4. Проверить build

Команды из раздела «Команды» CLAUDE.md. До каркаса (issue #6) кода нет — шаг пропускается с пометкой.

```bash
(cd backend && ruff check . && pytest -q) && (cd frontend && npm run build)
```

### 5. Проверить labels

```bash
gh label list --limit 200 | grep -c "^kanban:"
```

Если < 7 → предложить запустить `/setup-board`.

### 6. Создать docs структуру

```bash
mkdir -p docs/specs docs/arch docs/test-cases
```

## После инициализации

```
✅ .claude/ structure verified
✅ Memory initialized: project-summary.md, active-sprint.md, decisions.md
✅ GitHub CLI: authorized as {user}
✅ Build: OK / ⏭ пропущен (кода ещё нет)
✅ Labels: 29 workflow + 7 компонентов
✅ docs/ structure created

System ready. Start with:
  /feature <описание первой фичи>
```
