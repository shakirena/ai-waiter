# Story #42: Раздача собранного frontend процессом backend в режиме single

*Родитель: #6. Каждый агент дописывает свой раздел — не перезаписывает чужие.*

---

## 📋 Задача (analyst)

**AC:** Given выполнена сборка `frontend/dist`, приложение запущено с `APP_MODE=single` и `FRONTEND_DIST_DIR`, указывающим на неё When клиент запрашивает `/t/demo`, `/staff`, `/assets/<файл>` и `/api-несуществующий-путь` под `/api` Then маршруты интерфейсов возвращают `index.html` (SPA fallback), статические файлы отдаются с заголовками кэширования, пути под `/api`, `/integration` и `/health` не перехватываются и отвечают как API; при отсутствии каталога сборки приложение стартует и пишет предупреждение
**Роли:** администратор сервера заведения
**ТЗ:** ТЗ 9.1, ТЗ 9.2, NFR-8
**Ограничения:** Раздача статики в режиме `scaled` (её отдаёт Caddy); Раздача медиафайлов блюд (слой хранения — отдельная задача); Настройка службы Windows и туннеля
**Зависимости:** #37, #41
**Spec:** docs/specs/feature-6-project-scaffold.md

---

## 💻 Реализация (developer)

**Branch:** wt/42-spa (от feature/6-project-scaffold)
**Новые файлы:** —

**Изменённые файлы:**
- backend/app/web/spa.py — `RESERVED_PREFIXES`, `is_reserved` (граница сегмента, повторные `/` схлопываются: `//api/x` зарезервирован, `/apiary` — нет), `cache_control_for` (`assets/` → `public, max-age=31536000, immutable`, остальные файлы → `no-cache`), `SPAStaticFiles` (`html=False`, `follow_symlink=False`; зарезервированный путь → 404 до поиска файла и для любого метода; путь, выходящий за dist (`..`, абсолютный, диск Windows) → 404; файл найден → заголовок кэша в `file_response`, в т.ч. для 304; нет файла и есть расширение → 404; иначе `index.html` 200 no-cache; `index.html` удалён после старта → 404), `mount_spa` (нет `dist/index.html` → warning с `frontend_dist_dir`, `False`, ничего не монтируется)
- backend/tests/test_spa.py — 85 тестов: `is_reserved`, кэш-политика, fallback для `/`, `/t/…`, `/staff`, `/admin/…`, HEAD/POST, immutable/no-cache/304, JSON 404 для зарезервированных и отсутствующих файлов, `/health` и `/openapi.json` не перехватываются, `root_path`, path traversal через сырой ASGI-scope (`/../`, `%2f`, `%2e%2e`, `\`, `C:/`, NUL), symlink за пределы dist, монтирование последним, отсутствие сборки (warning, старт, `/health` 200), синхронизация `RESERVED_PREFIXES` с `BACKEND_PREFIXES` в `frontend/vite.config.ts` (разбор регуляркой)

`main.py` и `vite.config.ts` не менялись: `mount_spa` уже вызывается последним, списки префиксов совпадали.

**Build:** ruff check OK · ruff format --check OK · pytest test_spa + тесты #37/#38 — 244 passed · покрытие `app/web/spa.py` 100 % · frontend `npm run lint` OK, `npm run build` OK · ручная проверка `python -m app` на собранном dist: `/t/demo`, `/staff` → index.html no-cache; `/assets/index-*.js` → immutable; `/manifest.webmanifest`, `/sw.js` → no-cache; `/api/unknown`, `/missing.png` → JSON 404; `/health` → 200 JSON; `/..%2f..%2fpyproject.toml`, `/%2e%2e/…`, `/..%5c…`, `/assets/..%2f…` → JSON 404

**Решения и отклонения:**
- `html=False` вместо `html=True` из заглушки: иначе каталоги (`/assets`) перенаправляются на `/assets/`, а при наличии `404.html` подставлялся бы он; оба случая теперь закрывает fallback.
- Константа `NO_CACHE_FILES` удалена: `no-cache` получают все файлы вне `assets/` (index.html, sw.js, manifest.webmanifest, registerSW.js, workbox-*.js, иконки) — у них постоянные имена, иначе браузер застрянет на старой версии PWA. ETag/Last-Modified дают дешёвую перепроверку.
- Путь SPA с точкой в последнем сегменте (`/t/abc.def`) считается файлом → 404. QR-токены не должны содержать `.` (учесть при генерации токенов).

**Для следующих stories:**
- Новый backend-префикс — в `RESERVED_PREFIXES` и `BACKEND_PREFIXES` (`frontend/vite.config.ts`); тест `test_reserved_prefixes_match_vite_config` упадёт при расхождении.
- Роутеры подключать в `create_app` до `mount_spa` — после `Mount("/")` маршруты недостижимы (тест `test_spa_is_mounted_last`).
