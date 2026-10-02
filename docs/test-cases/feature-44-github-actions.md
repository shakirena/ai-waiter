# Test Cases: Story #44 — GitHub Actions: линтер, тесты backend, frontend на Linux, Windows

**Feature:** #6 «Каркас проекта» (story #44, AC-8)
**Spec:** docs/specs/feature-6-project-scaffold.md
**Arch:** docs/arch/feature-6-project-scaffold.md
**Created:** 2026-10-02

Обозначения в поле «Автоматизация»: **Авто** — выполняется unit-тестом в CI; **Ручной** — шаги выполняются вручную; **Статус прогона** — результат на дату создания документа.

---

## TC-44-001: Матрица ОС и состав шагов

**Priority:** Critical
**Type:** Functional
**AC:** AC-8 (Given `.github/workflows/ci.yml`, открыт PR / When workflow с матрицей `ubuntu-latest` и `windows-latest` / Then на обеих ОС выполняются `ruff check` и `pytest` (Python 3.12), `npm ci`, `lint`, `test`, `build` (Node LTS), с кэшем)
**E2E Automated:** No
**Автоматизация:** Авто — `backend/tests/test_repo_artifacts.py::test_ci_matrix_covers_linux_and_windows`, `test_ci_backend_runs_ruff_and_pytest_on_python_312`, `test_ci_frontend_runs_install_lint_test_build_with_cache`, `test_ci_has_services_job_for_db_and_scaled_markers`. Фактический прогон — PR #47.
**Статус прогона:** PASS. PR #47: `backend (ubuntu-latest)`, `backend (windows-latest)`, `frontend (ubuntu-latest)`, `frontend (windows-latest)`, `backend (postgres + redis)` — все pass.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Открыть PR в `chore/feature-6-design` | Запускаются 5 джобов |
| 2 | Проверить шаги backend на обеих ОС | `uv sync --frozen --extra scaled`, проверка версии Python 3.12, `ruff check`, `ruff format --check`, `pytest -m "not db and not scaled"` |
| 3 | Проверить шаги frontend на обеих ОС | `npm ci`, `lint`, `typecheck`, `test`, `build`, кэш npm |

---

## TC-44-002: Падение шага делает проверку красной

**Priority:** High
**Type:** Negative
**AC:** AC-8 (падение любого шага на любой ОС делает проверку красной)
**E2E Automated:** No
**Автоматизация:** Авто (статика) — `test_ci_does_not_swallow_failures` (нет `continue-on-error`), `fail-fast: false` в `test_ci_matrix_covers_linux_and_windows`. Фактическое подтверждение: PR #46 (`chore/feature-6-design → main`) красный, так как в нём заглушки без каркаса.
**Статус прогона:** PASS (статика); красный CI PR #46 подтверждает, что падение шага не маскируется.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Внести ошибку линтера в ветку PR | Шаг `ruff check` падает, проверка красная |
| 2 | Падение на одной ОС | Другая ОС не отменяется (`fail-fast: false`), общий результат красный |
| 3 | Код 5 pytest («тесты не выбраны») в джобе db/scaled | Единственный код, воспринимаемый как успех; остальные ненулевые коды — красная проверка |

---

## TC-44-003: Безопасность workflow

**Priority:** High
**Type:** Security
**AC:** AC-8 (+ NFR-2)
**E2E Automated:** No
**Автоматизация:** Авто — `test_ci_token_is_read_only` (`permissions: contents: read`), `test_no_ip_addresses_or_keys_in_infrastructure_files` (для `ci.yml`).
**Статус прогона:** PASS. Замечание: версии actions закреплены хешем коммита.

### Steps
| # | Action | Expected Result |
|---|--------|----------------|
| 1 | Проверить `permissions` | Только чтение содержимого |
| 2 | Поиск секретов в workflow | Секреты не используются; учётные данные сервис-контейнеров CI одноразовые |

---

## Related TCs
- TC-37-001, TC-41-001 (шаги, которые выполняет CI)
