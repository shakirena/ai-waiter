# Test Cases: Story #41 — Frontend: каркас React, Vite, TypeScript, Tailwind с PWA-манифестом

**Feature:** #6 «Каркас проекта» (story #41, AC-5)
**Spec:** docs/specs/feature-6-project-scaffold.md
**Arch:** docs/arch/feature-6-project-scaffold.md
**Created:** 2026-10-02

Обозначения в поле «Автоматизация»: **Авто** — выполняется unit-тестом в CI; **Ручной** — шаги выполняются вручную; **Статус прогона** — результат на дату создания документа.

---

## TC-41-001: Проверки frontend: lint, тесты, сборка

**Priority:** Critical
**Type:** Functional
**AC:** AC-5 (Given `npm ci` / When `npm run lint`, `npm run test -- --run`, `npm run build` / Then все без ошибок)
**E2E Automated:** No
**Автоматизация:** Авто — шаги CI `frontend (ubuntu-latest)` и `frontend (windows-latest)`; локально повторено.
**Статус прогона:** PASS (lint без замечаний, `tsc -b` без ошибок, 21 тест Vitest, сборка Vite успешна, 10 записей precache)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | В `frontend/` выполнить `npm ci` | Зависимости установлены по `package-lock.json` |
| 2 | `npm run lint` и `npm run typecheck` | Без ошибок и предупреждений |
| 3 | `npm run test -- --run` | Все тесты проходят |
| 4 | `npm run build` | Создан `dist/` с `index.html`, `manifest.webmanifest`, `sw.js`, `registerSW.js`, чанками по маршрутам |

---

## TC-41-002: Маршруты /t/:token, /staff, /admin показывают заглушки

**Priority:** Critical
**Type:** Functional
**AC:** AC-5 (каждый маршрут показывает свою заглушку; code splitting по маршрутам — NFR-3)
**E2E Automated:** No
**Автоматизация:** Авто — `frontend/src/App.test.tsx`: `/t/demo`, `/t/demo/menu`, `/staff`, `/staff/orders`, `/admin`, `/admin/menu` лениво загружают нужную заглушку (`React.lazy` + Suspense); `/t/abc123` показывает токен стола из адреса; `main.test.tsx` — монтирование в `#root`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Открыть `/t/demo` | Заглушка гостя, токен `demo` виден |
| 2 | Открыть `/staff` | Заглушка официанта |
| 3 | Открыть `/admin` | Заглушка админки |
| 4 | Каждая страница в сборке | Отдельный JS-чанк (`GuestPage-*.js`, `StaffPage-*.js`, `AdminPage-*.js`) |

---

## TC-41-003: Неизвестные маршруты и отсутствие #root

**Priority:** Medium
**Type:** Negative
**AC:** AC-5
**E2E Automated:** No
**Автоматизация:** Авто — `App.test.tsx`: `/`, `/unknown`, `/t`, `/staffroom` показывают «Страница не найдена»; `main.test.tsx`: без `#root` — ошибка «Элемент #root не найден».
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Открыть `/t` (без токена) или `/staffroom` | Страница «Страница не найдена» |
| 2 | Загрузить `main.tsx` при отсутствии `#root` | Исключение с понятным текстом |

---

## TC-41-004: PWA — манифест и service worker

**Priority:** High
**Type:** Functional / Security
**AC:** AC-5 (сборка содержит `manifest.webmanifest` с name, icons, `display: standalone`, `start_url`, и service worker)
**E2E Automated:** No
**Автоматизация:** Авто — `frontend/pwa-config.test.ts`: настоящая сборка во временный каталог; манифест (`name`, `start_url=/`, `display=standalone`, иконки 192 и 512, `maskable`), наличие `sw.js` и `registerSW.js`, denylist навигации service worker для `/api`, `/integration`, `/health`, `/ws`, `/docs`, `/redoc`, `/openapi.json`; прокси dev server только для путей backend.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Собрать frontend, открыть `dist/manifest.webmanifest` | JSON с name «AI Waiter», `display: standalone`, `start_url: /`, иконки 192x192 и 512x512 |
| 2 | Открыть `dist/sw.js` | Навигационный fallback `/index.html`, API-пути в denylist |
| 3 | Запросить с service worker путь `/api/...` | Запрос идёт в сеть, а не получает `index.html` |

---

## TC-41-005: Клиент API — /health и ошибки

**Priority:** Medium
**Type:** Functional / Negative
**AC:** AC-5 (клиент к backend без жёстких адресов)
**E2E Automated:** No
**Автоматизация:** Авто — `frontend/src/api/client.test.ts`: запрос относительного `/health`, передача `AbortSignal`, `ApiError` с кодом при не-2xx, пробрасывание сетевой ошибки.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `getHealth()` при ответе 200 | Возвращается тело `{status, mode, version}` |
| 2 | Ответ 503 | `ApiError` с кодом 503 |
| 3 | Сетевая ошибка `fetch` | Ошибка пробрасывается без подмены |

---

## TC-41-006: Вёрстка на ширине 360 px (mobile-first)

**Priority:** Medium
**Type:** Functional
**AC:** AC-5 (вёрстка работает на ширине 360 px; NFR-3)
**E2E Automated:** No
**Автоматизация:** Ручной — требует браузера; автотест будет добавлен в E2E (`/e2e`).
**Статус прогона:** НЕ ВЫПОЛНЕН в этой сессии (нужен ручной просмотр, см. отчёт QA)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `npm run dev`, открыть `/t/demo` в DevTools с шириной 360 px | Нет горизонтальной прокрутки, текст читаем |
| 2 | То же для `/staff` и `/admin` | То же |
| 3 | Открыть в Chrome «Установить приложение» | Предлагается установка PWA с иконкой |

---

## Related TCs
- TC-42-001 (backend раздаёт эту сборку)
