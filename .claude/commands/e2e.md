# /e2e — E2E Tests

Запустить `e2e-tester` для создания E2E автотестов из TC документации.

## Входные данные

`/e2e #N` — E2E тесты для конкретной фичи  
`/e2e all` — E2E тесты для всех TC из traceability-tc.md

## Важно

E2E поток **отдельный от основного pipeline** — не блокирует деплой.  
Приложение должно быть запущено на `127.0.0.1:8000` (с фейковым LLM-провайдером).

## Предусловия

```bash
# Приложение запущено?
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health
# Должно вернуть 200

# TC документация существует?
ls docs/test-cases/feature-{N}-*.md
```

## Что произойдёт

Запускается **e2e-tester** (opus), который:

1. Читает `docs/test-cases/feature-{N}-{name}.md`
2. Создаёт/обновляет Page Objects в `e2e-tests/pages/`
3. Создаёт E2E тест классы (Playwright Test, TypeScript)
4. Автоматизирует Critical + High TC обязательно
5. Обновляет `traceability-tc.md` (колонка E2E Automated)

## Запуск E2E тестов

```bash
cd e2e-tests
npx playwright test
```

## Запуск агента

```
Agent({
  subagent_type: "e2e-tester",
  prompt: "Create E2E tests for feature #N of ai-waiter. Read TC docs at docs/test-cases/feature-{N}-*.md. App running at 127.0.0.1:8000. Use Playwright Test (TypeScript) + Page Object in e2e-tests/. Only [data-testid='*'] selectors."
})
```
