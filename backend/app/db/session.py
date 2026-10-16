"""Движок SQLAlchemy 2 (async, asyncpg) и фабрика сессий (ADR-7.9).

``Database`` создаётся в ``build_container`` и живёт в ``Container.database``. Подключение
ленивое: ни создание объекта, ни ``start()`` не ходят в сеть и не создают движок — он
появляется при первом обращении к ``engine``/``sessionmaker``/``ping``. Поэтому недоступный
PostgreSQL не роняет процесс, а ``/health/ready`` сообщает ``"database": "fail"``.

Сессии: ``async_sessionmaker(engine, expire_on_commit=False)``. Транзакцию фиксирует сервис
явным ``await session.commit()`` (NFR-3: заказ коммитится до вызова ИИ); незафиксированное
откатывается при закрытии сессии в ``get_session`` (``app/api/deps.py``).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from urllib.parse import quote, quote_plus

from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)

# Параметры сеанса PostgreSQL: имя в pg_stat_activity и UTC для now()/timestamptz в выводе.
SERVER_SETTINGS: dict[str, str] = {"application_name": "ai-waiter", "timezone": "UTC"}

_MASK = "***"
# Строка подключения не разбирается (например, нечисловой порт): где в тексте пароль, неизвестно.
UNPARSABLE_URL_TEXT = "строка подключения DATABASE_URL не разбирается (проверьте её формат), текст ошибки скрыт"


class Database:
    """Обёртка над ``AsyncEngine`` и ``async_sessionmaker``; интерфейс как у компонентов
    Container (``start``/``stop``/``ping``)."""

    def __init__(self, settings: Settings) -> None:
        self._url = settings.database_url.get_secret_value()
        self._pool_size = settings.db_pool_size
        self._max_overflow = settings.db_max_overflow
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        """Движок создаётся при первом обращении. Без смены event loop policy: asyncpg работает
        с Proactor на Windows (ADR-5)."""
        if self._engine is None:
            self._engine = create_async_engine(
                self._url,
                pool_size=self._pool_size,
                max_overflow=self._max_overflow,
                pool_pre_ping=True,
                connect_args={"server_settings": dict(SERVER_SETTINGS)},
            )
        return self._engine

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:
            self._sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)
        return self._sessionmaker

    async def start(self) -> None:
        """Ничего не подключает (движок ленивый); оставлено для единого жизненного цикла."""

    async def stop(self) -> None:
        """Закрыть пул соединений, если движок создавался. Повторный вызов безопасен."""
        engine, self._engine, self._sessionmaker = self._engine, None, None
        if engine is not None:
            await engine.dispose()

    async def ping(self) -> bool:
        """``SELECT 1``. Ошибка → ``False`` и предупреждение в лог (пароль замаскирован);
        таймаут накладывает вызывающий (``/health/ready`` — 2 с), отмена не перехватывается."""
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning("База данных недоступна: %s", self.describe_error(exc), extra={"component": "database"})
            return False
        return True

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Одна сессия; при выходе закрывается, незафиксированная транзакция откатывается."""
        async with self.sessionmaker() as session:
            yield session

    def describe_error(self, exc: BaseException) -> str:
        """Текст ошибки для лога: тип и сообщение по цепочке причин, пароль из ``DATABASE_URL``
        заменён на ``***`` (в том числе в URL-кодированном виде)."""
        parts: list[str] = []
        seen: set[int] = set()
        current: BaseException | None = exc
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            message = str(current)
            parts.append(f"{type(current).__name__}: {message}" if message else type(current).__name__)
            if current.__cause__ is not None:
                current = current.__cause__
            else:
                current = None if current.__suppress_context__ else current.__context__
        return self._mask(" <- ".join(parts))

    def _mask(self, value: str) -> str:
        try:
            password = make_url(self._url).password
        except Exception:  # ArgumentError, ValueError порта: пароль не выделить — текст не показываем
            return UNPARSABLE_URL_TEXT
        if not password:
            return value
        for variant in sorted({password, quote(password, safe=""), quote_plus(password)}, key=len, reverse=True):
            value = value.replace(variant, _MASK)
        return value
