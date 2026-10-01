# /feature — Создать Feature Request

Создай GitHub Issue для новой фичи.

## Входные данные

`/feature <описание фичи>`

## Алгоритм

1. Прочитать описание фичи из аргумента команды
2. Прочитать CLAUDE.md для контекста проекта (стек, роли, архитектурные правила) и `docs/TZ.md`
3. Прочитать `gh issue list --label type:feature` — проверить дубликаты

4. Создать GitHub Issue:

```bash
gh issue create \
  --title "{чёткое название фичи}" \
  --body "$(cat <<'EOF'
## Описание
{расширенное описание}

## Business Value
{зачем нужно, кому выгодно}

## Acceptance Criteria
- AC-1: {критерий 1}
- AC-2: {критерий 2}
- AC-3: {критерий 3}

## Роли
- Кто использует: {гость / официант / администратор / владелец платформы / коннектор}

## Вне Scope
- {что не входит}
EOF
)" \
  --label "type:feature,kanban:backlog,priority:medium"
```

5. Спросить у пользователя (или установить самостоятельно исходя из описания):
   - Приоритет: `priority:critical/high/medium/low`
   - Размер (если очевиден): `size:s/m/l`
   - Компоненты: `backend`, `frontend`, `ai`, `connector`, `infra`, `security`, `content`

6. Вывести номер созданного issue и ссылку.

## Следующий шаг

После создания: `/analyze #{N}` для декомпозиции фичи.
