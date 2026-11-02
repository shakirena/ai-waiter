"""Проверки целевой базы для демо-данных (#60, #71; arch ``docs/arch/feature-60-demo-data-guard.md``).

Только запросы на переданной ``AsyncSession``: транзакцией управляет вызывающий.

- ``ensure_seed_target`` (#60, ADR-60.1) — сид вызывает её в своей транзакции до первой
  записи: в базе есть заведение, кроме ``DEMO_TENANT_ID``, → ``ForeignTenantsError``
  (CLI: код 2, ``FOREIGN_TENANTS_REFUSAL``, транзакция откатывается).
- ``demo_tenant_exists`` (#71, ADR-60.2) — есть ли в базе демо-заведение; её вызывает
  ``app.api.demo_data.DemoDataMonitor`` при ``APP_ENV=prod``.

``DEMO_TENANT_ID`` берётся из ``app.seed.data`` и не дублируется. В текстах — ни строки
подключения, ни числа, идентификаторов и названий найденных заведений (это данные боевой базы).
"""

from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.seed.data import DEMO_TENANT_ID

FOREIGN_TENANTS_REFUSAL = (
    "В целевой базе уже есть заведения, кроме демо-заведения: демо-данные в такую базу не загружаются, "
    "ничего не записано. Сид предназначен только для базы разработки — проверьте --database-url "
    "и DATABASE_URL."
)


class ForeignTenantsError(RuntimeError):
    """В целевой базе есть заведение, кроме ``DEMO_TENANT_ID``: сид запрещён (#60)."""

    def __init__(self) -> None:
        super().__init__(FOREIGN_TENANTS_REFUSAL)


async def foreign_tenants_exist(session: AsyncSession) -> bool:
    """``SELECT EXISTS (SELECT 1 FROM tenants WHERE id <> DEMO_TENANT_ID)`` (Core ``select(exists()…)``).

    Один запрос, без блокировок (ADR-60.1: READ COMMITTED). Гонку с параллельной записью
    заведения проверка не закрывает; #71 лишь обнаруживает её последствие — демо-заведение
    в prod-базе (readiness 503 и предупреждение в логе). Ошибку БД
    (нет таблицы ``tenants``, нет соединения) не перехватывает — CLI превращает её в код 1."""
    return bool(await session.scalar(select(exists().where(Tenant.id != DEMO_TENANT_ID))))


async def ensure_seed_target(session: AsyncSession) -> None:
    """Вызывается сидом в его транзакции до ``apply_seed``; ``foreign_tenants_exist`` → ``ForeignTenantsError``."""
    if await foreign_tenants_exist(session):
        raise ForeignTenantsError


async def demo_tenant_exists(session: AsyncSession) -> bool:
    """``SELECT EXISTS (SELECT 1 FROM tenants WHERE id = DEMO_TENANT_ID)`` — поиск по первичному ключу.

    Транзакцию не открывает и не фиксирует (только чтение); ошибки не перехватывает —
    это делает ``DemoDataMonitor`` (неизвестный результат ≠ «демо нет», ADR-60.2)."""
    return bool(await session.scalar(select(exists().where(Tenant.id == DEMO_TENANT_ID))))
