# Story #6: Каркас проекта: backend, frontend, CI, режимы single/scaled

*Родительская feature; дочерние stories #37–#45 (см. docs/specs/feature-6-project-scaffold.md).*

---

## 🏗️ Архитектура (architect)

**Таблицы:** нет (модель данных, движок БД и Alembic — #7)
**Миграция:** нет
**API:** GET /health — все — 200; GET /health/ready — все — 200 / 503 (checks: redis; database добавит #7)
**События/задачи:** механизмы без доменных событий: `Event` + `tenant_channel()`, единый `TaskRegistry` (`app/tasks/__init__.py:registry`), `@registry.periodic(every_minutes=N)`
**ИИ-tools:** не затронуты (в Settings зарезервированы ANTHROPIC_API_KEY, AI_MODEL)
**Security:** секреты — SecretStr из env; single слушает 127.0.0.1; в scaled наружу только caddy; /health без внутренних деталей; SPA fallback не отдаёт HTML для /api, /integration, /health, /ws; граница Redis — ruff TID251 + test_import_boundaries.py
**Code stubs:**
- backend/pyproject.toml, backend/.python-version
- backend/app/{__init__,__main__,main}.py
- backend/app/core/{config,events,scheduler,ratelimit,container,log}.py
- backend/app/core/single/{__init__,events,scheduler,ratelimit}.py
- backend/app/core/scaled/{__init__,events,scheduler,ratelimit,worker}.py
- backend/app/api/{__init__,deps,health}.py, backend/app/web/{__init__,spa}.py, backend/app/tasks/__init__.py
- backend/tests/{conftest,test_config,test_container,test_events,test_scheduler,test_ratelimit,test_health,test_spa,test_import_boundaries}.py
- frontend/{package.json,vite.config.ts,tsconfig*.json,eslint.config.js,index.html}, frontend/src/{main.tsx,App.tsx,App.test.tsx,index.css,api/types.ts,api/client.ts,test/setup.ts}
- deploy/{Dockerfile,docker-compose.yml,Caddyfile}, .github/workflows/ci.yml, .env.example, .gitattributes
**Arch doc:** docs/arch/feature-6-project-scaffold.md

**Соответствие stories:** #37 — config, main, __main__, health, log, .env.example; #38 — интерфейсы, container, deps, tasks, test_import_boundaries; #39 — core/single/*; #40 — core/scaled/*; #41 — frontend/*; #42 — web/spa.py; #43 — deploy/*; #44 — ci.yml, .gitattributes; #45 — README (раздел «Команды» в arch doc).
**Developer:** сгенерировать и закоммитить `backend/uv.lock` (`uv lock`) и `frontend/package-lock.json` (`npm install`) — CI использует `--frozen` / `npm ci`; иконки PWA `frontend/public/icons/icon-{192,512}.png`.
