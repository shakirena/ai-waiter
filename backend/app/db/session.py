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

import ipaddress
import logging
import re
from collections.abc import AsyncIterator, Iterable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote, quote_plus

from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.engine import URL

    from app.core.config import Settings

logger = logging.getLogger(__name__)

# Параметры сеанса PostgreSQL: имя в pg_stat_activity и UTC для now()/timestamptz в выводе.
SERVER_SETTINGS: dict[str, str] = {"application_name": "ai-waiter", "timezone": "UTC"}

_MASK = "***"
# Строка подключения не разбирается (например, нечисловой порт): что маскировать в тексте, неизвестно.
UNPARSABLE_URL_TEXT = "строка подключения DATABASE_URL не разбирается (проверьте её формат), текст ошибки скрыт"


# --- #73: маскирование всех деталей подключения (arch: docs/arch/feature-73-describe-error-mask.md) ---

# Ключи query, которые asyncpg принимает как параметры подключения (решение 1 arch #73).
_QUERY_SECRET_KEYS = ("password",)
_QUERY_TOKEN_KEYS = ("port", "user", "database", "passfile")
# Кандидаты в IP-литералы (решение 4): подтверждаются ``ipaddress.ip_address``.
_IPV4_CANDIDATE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
# IPv6: серия hex-цифр, ``:`` и ``.`` (встроенный IPv4); наличие двух ``:`` проверяет обработчик.
_IPV6_CANDIDATE = re.compile(r"(?<![\w:.])[0-9A-Fa-f:.]+(?![\w:.])")


@dataclass(frozen=True, slots=True)
class _UrlSecrets:
    """Значения из ``DATABASE_URL``, которые нельзя показывать (решение 1–3 arch #73).

    ``substrings`` — пароль (из userinfo и ``?password=``) во всех вариантах кодирования; заменяется
    простой подстрокой, без границ токена. ``tokens`` — пользователь, хосты, явные порты, база и их
    значения из query (``host``, ``port``, ``user``, ``database``, ``passfile``); заменяются только
    целым токеном (рядом нет ``\\w``), без учёта регистра. Оба кортежа без пустых строк и
    отсортированы по убыванию длины."""

    substrings: tuple[str, ...]
    tokens: tuple[str, ...]


def _url_secrets(url: URL) -> _UrlSecrets:
    """Собрать секретные значения из разобранного ``DATABASE_URL`` (решение 1–2, 5 arch #73).

    Источники: ``url.password``, ``url.username``, ``url.host`` (целиком и по частям через запятую),
    ``url.port`` (только если указан явно — порт по умолчанию не маскируется), ``url.database``;
    из ``url.query`` (значение — строка или кортеж при повторе ключа): ``password`` → ``substrings``;
    ``host`` (``h``, ``h:p``, ``[v6]:p``, списки через запятую — хост и порт по отдельности и целиком),
    ``port``, ``user``, ``database``, ``passfile`` → ``tokens``. Каждое значение — в вариантах
    ``raw``, ``quote(v, safe="")``, ``quote_plus(v)``. Не бросает на разобранном ``URL``."""
    query = url.query
    secret_values = [url.password, *_query_values(query, _QUERY_SECRET_KEYS)]
    token_values: list[str | None] = [url.username, url.database]
    if url.port is not None:
        token_values.append(str(url.port))
    if url.host:
        token_values.extend(_host_values(url.host))
    for value in _query_values(query, ("host",)):
        token_values.extend(_host_values(value))
    token_values.extend(_query_values(query, _QUERY_TOKEN_KEYS))
    return _UrlSecrets(substrings=_variants(secret_values), tokens=_variants(token_values))


def _query_values(query: Mapping[str, str | tuple[str, ...]], keys: Iterable[str]) -> Iterator[str]:
    """Значения ключей query: строка или кортеж (повтор ключа)."""
    for key in keys:
        value = query.get(key)
        if isinstance(value, str):
            yield value
        elif value is not None:
            yield from value


def _host_values(value: str) -> Iterator[str]:
    """Хост целиком, его части через запятую и в каждой части — хост и порт (``h:p``, ``[v6]:p``).

    Часть с двумя и более ``:`` без скобок — IPv6 без порта, не разбивается."""
    yield value
    for part in value.split(","):
        part = part.strip()
        yield part
        if part.startswith("["):
            host, _, rest = part[1:].partition("]")
            yield host
            if rest.startswith(":"):
                yield rest[1:]
        elif part.count(":") == 1:
            yield from part.split(":")


def _variants(values: Iterable[str | None]) -> tuple[str, ...]:
    """Варианты кодирования без пустых строк и повторов, длинные первыми."""
    result: set[str] = set()
    for value in values:
        if value:
            result.update({value, quote(value, safe=""), quote_plus(value)})
    result.discard("")
    return tuple(sorted(result, key=lambda item: (-len(item), item)))


def _mask_message(message: str, secrets: _UrlSecrets) -> str:
    """Замаскировать одно сообщение исключения (без имени типа) — решение 3–4 arch #73.

    Совпадения ищутся по исходному тексту: (1) ``secrets.substrings`` — подстроки; (2) ``secrets.tokens`` —
    одно регулярное выражение ``(?<!\\w)(?:t1|t2|…)(?!\\w)`` с ``re.escape``, длинные первыми,
    ``re.IGNORECASE``; (3) литералы IP (``_ip_spans``). Токены и IP ищутся ещё и в копии, где пароль
    заменён небуквенными символами (``adminpw`` при пароле ``pw`` → токен ``admin``). Пересекающиеся
    участки объединяются и заменяются на ``***`` за один проход, поэтому пароль, совпавший с частью
    пользователя или IP, не оставляет хвостов (``ad***``, ``192.0.2.***`` — security review #73, LOW)."""
    spans: list[tuple[int, int]] = []
    for secret in secrets.substrings:
        spans.extend(match.span() for match in re.finditer(re.escape(secret), message))
    hidden = message
    for begin, end in spans:
        hidden = hidden[:begin] + "\0" * (end - begin) + hidden[end:]
    token_pattern = None
    if secrets.tokens:
        alternatives = "|".join(re.escape(token) for token in sorted(secrets.tokens, key=len, reverse=True))
        token_pattern = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)
    for variant in {message, hidden}:
        if token_pattern is not None:
            spans.extend(match.span() for match in token_pattern.finditer(variant))
        spans.extend(_ip_spans(variant))
    return _replace_spans(message, spans)


def _mask_ip_literals(text: str) -> str:
    """Заменить на ``***`` любые литералы IPv4/IPv6 в тексте, не только из URL (решение 4 arch #73).

    Кандидаты ищутся регулярными выражениями и подтверждаются ``ipaddress.ip_address`` — строки вида
    ``12:30:45`` или ``1.2.300.4`` не трогаются. Нужно для случая «в URL домен, а драйвер печатает
    разрешённый IP»: ``Connect call failed ('192.0.2.10', 5432)``."""
    return _replace_spans(text, _ip_spans(text))


def _ip_spans(text: str) -> Iterator[tuple[int, int]]:
    """Участки текста с литералами IPv6 и IPv4. У кандидата IPv6 хвостовые точки (конец предложения)
    и одиночное ``:`` (``…::7: x``) в участок не входят."""
    for match in _IPV6_CANDIDATE.finditer(text):
        body = match.group().rstrip(".")
        if body.endswith(":") and not body.endswith("::"):
            body = body[:-1]
        if body.count(":") >= 2 and _is_ip(body):
            yield match.start(), match.start() + len(body)
    for match in _IPV4_CANDIDATE.finditer(text):
        if _is_ip(match.group()):
            yield match.span()


def _replace_spans(text: str, spans: Iterable[tuple[int, int]]) -> str:
    """Заменить участки на ``***``; пересекающиеся участки объединяются в один."""
    pieces: list[str] = []
    position = 0  # конец последнего замаскированного участка
    for begin, end in sorted(spans):
        if begin < position:  # пересекается с уже замаскированным участком — расширить его
            position = max(position, end)
            continue
        pieces.extend((text[position:begin], _MASK))
        position = end
    pieces.append(text[position:])
    return "".join(pieces)


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


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
        """``SELECT 1``. Ошибка → ``False`` и предупреждение в лог (детали подключения → ``***``);
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
        """Текст ошибки для лога: тип и сообщение по цепочке причин; детали подключения из
        ``DATABASE_URL`` (хост, явный порт, пользователь, база, пароль — в том числе из query
        и URL-кодированные) и любые IP-литералы заменены на ``***`` (#73). Имена типов не
        маскируются. URL не разбирается → ``UNPARSABLE_URL_TEXT``, текст ошибки не показывается."""
        try:
            secrets = _url_secrets(make_url(self._url))
        except Exception:  # ArgumentError, ValueError порта: что маскировать, неизвестно — текст не показываем
            return UNPARSABLE_URL_TEXT
        parts: list[str] = []
        seen: set[int] = set()
        current: BaseException | None = exc
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            message = str(current)
            name = type(current).__name__
            parts.append(f"{name}: {_mask_message(message, secrets)}" if message else name)
            if current.__cause__ is not None:
                current = current.__cause__
            else:
                current = None if current.__suppress_context__ else current.__context__
        return " <- ".join(parts)
