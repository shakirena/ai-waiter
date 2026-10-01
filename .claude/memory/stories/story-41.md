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
