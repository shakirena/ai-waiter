"""Движок SQLAlchemy 2 (async, asyncpg) и фабрика сессий (ADR-7.9).

``Database`` создаётся в ``build_container`` и живёт в ``Container.database``; подключение
ленивое — создание объекта и ``start()`` не ходят в сеть, поэтому недоступный PostgreSQL
не роняет процесс, а ``/health/ready`` сообщает ``"database": "fail"``.

Сессии: ``async_sessionmaker(engine, expire_on_commit=False)``. Транзакцию фиксирует сервис
явным ``await session.commit()`` (NFR-3: заказ коммитится до вызова ИИ); незафиксированное
откатывается при закрытии сессии в ``get_session`` (``app/api/deps.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from app.core.config import Settings


class Database:
    """Обёртка над ``AsyncEngine`` и ``async_sessionmaker``; интерфейс как у компонентов
    Container (``start``/``stop``/``ping``)."""

    def __init__(self, settings: Settings) -> None:
        """``create_async_engine(DATABASE_URL, pool_size=DB_POOL_SIZE, max_overflow=DB_MAX_OVERFLOW,
        pool_pre_ping=True, connect_args={"server_settings": {"application_name": "ai-waiter",
        "timezone": "UTC"}})``. Без смены event loop policy (asyncpg работает с Proactor на Windows)."""
        raise NotImplementedError

    @property
    def engine(self) -> AsyncEngine:
        raise NotImplementedError

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        raise NotImplementedError

    async def start(self) -> None:
        """Ничего не подключает (движок ленивый); оставлено для единого жизненного цикла."""
        raise NotImplementedError

    async def stop(self) -> None:
        """``await engine.dispose()``."""
        raise NotImplementedError

    async def ping(self) -> bool:
        """``SELECT 1``; таймаут 2 с накладывает ``/health/ready``. Исключение → ``False``."""
        raise NotImplementedError

    async def session(self) -> AsyncIterator[AsyncSession]:
        """Асинхронный генератор одной сессии (используется ``get_session``)."""
        raise NotImplementedError
        yield  # pragma: no cover — делает функцию генератором
