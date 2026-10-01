# Story #41: Frontend: каркас React, Vite, TypeScript, Tailwind с PWA-манифестом

*Родитель: #6. Каждый агент дописывает свой раздел — не перезаписывает чужие.*

---

## 📋 Задача (analyst)

**AC:** Given в `frontend/` выполнен `npm ci` When выполняются `npm run lint`, `npm run test -- --run`, `npm run build`, затем открываются маршруты `/t/demo`, `/staff` и `/admin` в собранном приложении Then все три команды завершаются без ошибок, каждый маршрут показывает свою заглушку-страницу, сборка содержит `manifest.webmanifest` (name, icons, `display: standalone`, `start_url`) и service worker, а вёрстка работает на ширине 360 px
**Роли:** гость, официант или администратор (через будущий интерфейс)
**ТЗ:** ТЗ раздел 8 (frontend), NFR-2, NFR-8
**Ограничения:** Реальные экраны чата, ленты официанта и админки; Раздача сборки backend-ом (отдельная story); Офлайн-кэширование данных, push-уведомления; Авторизация и запросы к API
**Зависимости:** нет
**Spec:** docs/specs/feature-6-project-scaffold.md

---

## 💻 Реализация (developer)

**Branch:** wt/41-frontend (worktree от feature/6-project-scaffold)
**Новые файлы:**
- frontend/package-lock.json
- frontend/public/icons/icon-192.png, frontend/public/icons/icon-512.png
- frontend/scripts/generate-icons.mjs (`npm run icons`, генерация PNG без зависимостей)
- frontend/src/components/PlaceholderPage.tsx
- frontend/src/pages/GuestPage.tsx, StaffPage.tsx, AdminPage.tsx, NotFoundPage.tsx
- frontend/src/api/client.test.ts

**Изменённые файлы:**
- frontend/src/App.tsx (React.lazy + Suspense, NotFound в основном чанке)
- frontend/src/App.test.tsx, frontend/src/test/setup.ts (явный `cleanup`, т. к. `globals: false`)
- frontend/src/api/client.ts (`getHealth` → `GET /health`, `ApiError` на не-2xx)
- frontend/src/index.css, frontend/index.html (иконки), frontend/vite.config.ts (иконки any + maskable, includeAssets), frontend/package.json (скрипт `icons`)

**Build:** npm ci OK · lint OK · typecheck OK · vitest 15 passed · build OK (manifest.webmanifest, sw.js, icons в dist) · vite preview: /t/demo, /staff, /admin → 200 index.html · headless Chrome 360 px: scrollWidth = 360 на всех маршрутах, SW зарегистрирован

**Заметки:** тексты заглушек только на русском, i18n AZ/RU — со стори экранов гостя (#13). `npm audit`: 2 moderate в dev-зависимости vitest 3 (GHSA-82fw-gwwq-j7x9), исправление — vitest 5 (major), не обновлялось. Команды фронтенда для раздела «Команды» CLAUDE.md — в arch doc, CLAUDE.md не менялся.
