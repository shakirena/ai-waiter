# Test Cases: Story #42 — Раздача собранного frontend процессом backend в режиме single

**Feature:** #6 «Каркас проекта» (story #42, AC-6)
**Spec:** docs/specs/feature-6-project-scaffold.md
**Arch:** docs/arch/feature-6-project-scaffold.md
**Created:** 2026-10-02

Обозначения в поле «Автоматизация»: **Авто** — выполняется unit-тестом в CI; **Ручной** — шаги выполняются вручную; **Статус прогона** — результат на дату создания документа.

---

## TC-42-001: SPA fallback для маршрутов интерфейсов

**Priority:** Critical
**Type:** Functional
**AC:** AC-6 (Given собранный `frontend/dist`, `APP_MODE=single`, `FRONTEND_DIST_DIR` / When запросы `/t/demo`, `/staff` / Then возвращается `index.html`)
**E2E Automated:** No
**Автоматизация:** Авто — `backend/tests/test_spa.py::test_spa_routes_fall_back_to_index`, `test_head_falls_back_to_index`. Ручной смоук — выполнен.
**Статус прогона:** PASS (смоук на `python -m app`: `/t/demo`, `/staff`, `/admin` → 200 `text/html`, `Cache-Control: no-cache`, в теле `id="root"`)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `npm run build`, запустить backend, `GET /t/demo` | 200, `index.html` |
| 2 | `GET /staff`, `GET /admin` | То же |
| 3 | `HEAD /t/demo` | 200 без тела |

---

## TC-42-002: Кэширование статики

**Priority:** High
**Type:** Functional
**AC:** AC-6 (статические файлы отдаются с заголовками кэширования)
**E2E Automated:** No
**Автоматизация:** Авто — `test_spa.py::test_hashed_assets_are_immutable`, `test_entry_files_are_no_cache`, `test_not_modified_keeps_cache_header`, `test_immutable_value_matches_adr`. Ручной смоук — выполнен.
**Статус прогона:** PASS (`/assets/*.js` → `public, max-age=31536000, immutable`; `index.html`, `sw.js`, `manifest.webmanifest` → `no-cache`)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `GET /assets/<хешированный файл>` | 200, `Cache-Control: public, max-age=31536000, immutable` |
| 2 | `GET /sw.js`, `/manifest.webmanifest`, `/` | `Cache-Control: no-cache` (service worker обновляется) |
| 3 | Повторный запрос с `If-None-Match` | 304 с теми же заголовками кэша |

---

## TC-42-003: Пути API не перехватываются

**Priority:** Critical
**Type:** Negative / Security
**AC:** AC-6 (пути под `/api`, `/integration`, `/health` отвечают как API)
**E2E Automated:** No
**Автоматизация:** Авто — `test_spa.py::test_reserved_and_missing_files_are_json_404`, `test_reserved_path_is_404_for_any_method`, `test_api_routes_are_not_intercepted`, `test_reserved_path_behind_root_path`, `test_reserved_prefixes_match_vite_config`, `test_spa_is_mounted_last`, `test_non_get_on_spa_route_is_405`. Ручной смоук — выполнен.
**Статус прогона:** PASS (`/api/nope` → 404, `/integration/v1/x` → 404, `/health` → JSON)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `GET /api/несуществующий` | 404 JSON, не `index.html` |
| 2 | `GET /integration/v1/x` | 404 JSON |
| 3 | `POST /staff` | 405 (SPA отвечает только на GET/HEAD) |
| 4 | Сверить список зарезервированных префиксов с `vite.config.ts` | Списки совпадают |

---

## TC-42-004: Защита от обхода каталога

**Priority:** Critical
**Type:** Security
**AC:** AC-6 (+ NFR-2)
**E2E Automated:** No
**Автоматизация:** Авто — `test_spa.py::test_path_traversal_never_leaks_files`, `test_dot_dot_prefix_is_rejected_before_lookup`, `test_symlink_outside_dist_is_not_followed`, `test_escapes_root`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `GET /..%2f..%2f.env` и подобные варианты | Файл вне `dist` не отдаётся |
| 2 | Символическая ссылка в `dist`, ведущая наружу | Не разыменовывается |

---

## TC-42-005: Отсутствует каталог сборки

**Priority:** High
**Type:** Negative
**AC:** AC-6 (при отсутствии каталога сборки приложение стартует и пишет предупреждение)
**E2E Automated:** No
**Автоматизация:** Авто — `test_spa.py::test_missing_build_warns_and_app_starts`, `test_serve_frontend_false_does_not_mount`, `test_index_removed_after_start_is_404`.
**Статус прогона:** PASS

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Запустить приложение с `FRONTEND_DIST_DIR` на пустой каталог | Старт успешен, одно предупреждение в логе |
| 2 | `GET /health` | 200 |
| 3 | `SERVE_FRONTEND=false` | SPA не монтируется |

---

## Related TCs
- TC-41-002 (сборка, которую раздаёт backend)
- TC-37-001 (`/health`)
