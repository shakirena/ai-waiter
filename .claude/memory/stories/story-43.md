# Story #43: Docker Compose для режима scaled: api, worker, postgres, redis, caddy

*Родитель: #6. Каждый агент дописывает свой раздел — не перезаписывает чужие.*

---

## 📋 Задача (analyst)

**AC:** Given на Linux-хосте установлен Docker, рядом с `deploy/docker-compose.yml` лежит `.env`, созданный из `.env.example`, и задан домен When выполняется `docker compose -f deploy/docker-compose.yml up -d --build` Then запускаются сервисы api, worker, postgres, redis и caddy, у каждого есть healthcheck, `GET https://{домен}/health` отвечает `200`, а данные postgres и медиафайлы лежат в именованных томах
**Роли:** администратор VPS
**ТЗ:** ТЗ раздел 8, ТЗ 9.2, ТЗ 9.3, NFR-8
**Ограничения:** Бэкапы БД и медиа (NFR-9, отдельная задача); Sentry, мониторинг; Скрипты службы Windows для режима single; Применение миграций Alembic (появится с #7)
**Зависимости:** #37, #40, #41
**Spec:** docs/specs/feature-6-project-scaffold.md
