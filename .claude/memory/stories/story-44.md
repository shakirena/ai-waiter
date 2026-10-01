# Story #44: GitHub Actions: линтер, тесты backend, frontend на Linux, Windows

*Родитель: #6. Каждый агент дописывает свой раздел — не перезаписывает чужие.*

---

## 📋 Задача (analyst)

**AC:** Given в репозитории есть `.github/workflows/ci.yml` и открыт pull request When запускается workflow с матрицей `ubuntu-latest` и `windows-latest` Then на обеих ОС выполняются `ruff check` и `pytest` (Python 3.12) в `backend/` и `npm ci`, `lint`, `test`, `build` (Node LTS) в `frontend/`, с кэшем зависимостей, а падение любого шага на любой ОС делает проверку красной
**Роли:** разработчик
**ТЗ:** ТЗ 9.2 (проверка в CI на Windows и Linux), ТЗ раздел 8 (GitHub Actions), NFR-8
**Ограничения:** Сборка и публикация Docker-образов; Деплой; E2E-тесты Playwright; Проверки, требующие PostgreSQL (появятся с #7)
**Зависимости:** #37, #41
**Spec:** docs/specs/feature-6-project-scaffold.md
