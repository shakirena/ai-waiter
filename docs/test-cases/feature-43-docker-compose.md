# Test Cases: Story #43 — Docker Compose для режима scaled: api, worker, postgres, redis, caddy

**Feature:** #6 «Каркас проекта» (story #43, AC-7)
**Spec:** docs/specs/feature-6-project-scaffold.md
**Arch:** docs/arch/feature-6-project-scaffold.md
**Created:** 2026-10-02

Обозначения в поле «Автоматизация»: **Авто** — выполняется unit-тестом в CI; **Ручной** — шаги выполняются вручную; **Статус прогона** — результат на дату создания документа.

---

## TC-43-001: Состав сервисов, healthcheck и тома (статическая проверка)

**Priority:** Critical
**Type:** Functional
**AC:** AC-7 (запускаются api, worker, postgres, redis, caddy; у каждого есть healthcheck; данные postgres и медиа в именованных томах)
**E2E Automated:** No
**Автоматизация:** Авто — `backend/tests/test_repo_artifacts.py`: `test_compose_has_exactly_the_required_services`, `test_every_service_has_healthcheck` (5 сервисов), `test_state_lives_in_named_volumes`, `test_api_waits_for_storages_and_caddy_waits_for_api`, `test_compose_forces_scaled_mode_and_requires_secrets`. Ручной — `docker compose config` выполнен.
**Статус прогона:** PASS (статика). `docker compose -f deploy/docker-compose.yml config --services` → postgres, redis, api, caddy, worker.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Разобрать `deploy/docker-compose.yml` | Ровно пять сервисов: api, worker, postgres, redis, caddy |
| 2 | Проверить `healthcheck` каждого сервиса | Заданы `test` и `retries` |
| 3 | Проверить тома | `pgdata` у postgres, `media` у api и worker; данные не в bind-mount |
| 4 | Проверить `depends_on` | api ждёт `service_healthy` у postgres и redis; caddy — у api |
| 5 | Запустить `config` без обязательных переменных | Ошибка с названием переменной (`PUBLIC_DOMAIN`, `POSTGRES_*`, `EDGE_SUBNET`) |

---

## TC-43-002: Сетевая изоляция и безопасность контейнеров

**Priority:** High
**Type:** Security
**AC:** AC-7 (+ NFR-2: контейнеры без root)
**E2E Automated:** No
**Автоматизация:** Авто — `test_repo_artifacts.py::test_only_caddy_publishes_ports`, `test_containers_forbid_privilege_escalation`, `test_dockerfile_runs_as_non_root_numeric_user`, `test_no_ip_addresses_or_keys_in_infrastructure_files`.
**Статус прогона:** PASS (статика)

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Найти сервисы с `ports` | Только caddy (80, 443) |
| 2 | Проверить `security_opt` | `no-new-privileges:true` у api, worker и caddy |
| 3 | Проверить `USER` в Dockerfile | Числовой непривилегированный (10001:10001) |
| 4 | Поиск IP-адресов и ключей в compose, Caddyfile, `.env.example` | Не найдено |

---

## TC-43-003: Запуск стека на Docker и /health по домену

**Priority:** Critical
**Type:** Functional
**AC:** AC-7 (When `docker compose up -d --build` / Then все сервисы healthy, `GET https://{домен}/health` = 200)
**E2E Automated:** No
**Автоматизация:** Ручной.
**Статус прогона:** НЕ ВЫПОЛНЕН — на тестовой машине (Windows 11) демон Docker не запущен, а AC требует Linux-хост и домен. Требует ручной проверки (см. отчёт QA и README, раздел «Режим scaled»).

### Preconditions
- Linux-хост с Docker, домен, указывающий на хост, открыты порты 80 и 443.
- `deploy/.env` создан из `.env.example`, заполнены `POSTGRES_*` (случайный пароль), `PUBLIC_DOMAIN`, `EDGE_SUBNET`.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | `docker compose -f deploy/docker-compose.yml up -d --build` | Образ собирается (frontend собирается внутри многоэтапной сборки), контейнеры запущены |
| 2 | `docker compose -f deploy/docker-compose.yml ps` | Все пять сервисов в состоянии `healthy` |
| 3 | `curl https://{домен}/health` | 200, `{"status":"ok","mode":"scaled",...}` |
| 4 | `curl https://{домен}/health/ready` | 200, `checks.redis = ok` |
| 5 | `docker compose ... down` и повторный `up` | Данные postgres и медиа сохранились (именованные тома) |
| 6 | `docker compose ... exec api id` | Не root (uid 10001) |

---

## Related TCs
- TC-40-001 (worker и Redis)
- TC-45-002 (описание запуска scaled в README)
