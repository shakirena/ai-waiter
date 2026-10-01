# /refresh-agents — Синхронизация агентов

Синхронизировать агентов из другого проекта-источника или обновить до последней версии фреймворка.

## Входные данные

`/refresh-agents` — обновить из текущего AGENTS_FRAMEWORK.md  
`/refresh-agents <source-path>` — синхронизировать из другого проекта

## Алгоритм

### 1. Проверить текущее состояние

```bash
ls .claude/agents/*.md | wc -l
ls .claude/commands/*.md | wc -l
```

### 2. Синхронизация из AGENTS_FRAMEWORK.md

Прочитать `.claude/AGENTS_FRAMEWORK.md` и сверить:
- Список агентов из секции "Каталог агентов" → файлы в `.claude/agents/`
- Список команд из секции "Команды" → файлы в `.claude/commands/`

Вывести diff что отсутствует.

### 3. Синхронизация из другого проекта

```bash
SOURCE="{source-path}/.claude"
# Скопировать agents (не перезаписывать project-specific данные)
cp $SOURCE/agents/*.md .claude/agents/
cp $SOURCE/commands/*.md .claude/commands/
# НЕ копировать: memory/, settings.json
```

### 4. Проверить после синхронизации

```bash
ls .claude/agents/*.md
ls .claude/commands/*.md
```

### 5. Обновить project-specific части

После копирования проверить и адаптировать под текущий стек:
- Команды сборки (ruff/pytest, npm) — из раздела «Команды» CLAUDE.md
- Структура `backend/`, `frontend/`, `e2e-tests/`
- БД конфигурация
- Роли (гость, официант, администратор, владелец платформы, коннектор) и tenant-изоляция

## Результат

```
Agents refreshed:
  Updated: analysis-lead.md, dev-lead.md, ...
  Added: {new-agent}.md
  Project-specific: CLAUDE.md context verified
```
