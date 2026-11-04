"""Database (ADR-7.9) без PostgreSQL: ленивый движок, параметры пула, ping и маскирование пароля."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import make_url
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.session import SERVER_SETTINGS, UNPARSABLE_URL_TEXT, Database, _mask_ip_literals, _url_secrets
from tests.conftest import make_settings

SECRET_URL = "postgresql+asyncpg://ai_waiter:pw-s3cret@db.invalid:5432/ai_waiter"


class _FakeConnection:
    def __init__(self, executed: list[str]) -> None:
        self.executed = executed

    async def execute(self, statement: Any) -> None:
        self.executed.append(str(statement))


class _FakeEngine:
    """Подменяет AsyncEngine: ``connect()`` либо выполняет запрос, либо бросает ошибку."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.executed: list[str] = []
        self.disposed = 0

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[_FakeConnection]:
        if self.error is not None:
            raise self.error
        yield _FakeConnection(self.executed)

    async def dispose(self) -> None:
        self.disposed += 1


def _database(url: str = SECRET_URL, **overrides: Any) -> Database:
    return Database(make_settings(database_url=url, **overrides))


def test_engine_is_created_lazily_once_with_pool_settings() -> None:
    db = _database(db_pool_size=7, db_max_overflow=3)
    assert db._engine is None
    engine = db.engine
    assert isinstance(engine, AsyncEngine)
    assert db.engine is engine
    assert engine.pool.size() == 7
    assert engine.pool._max_overflow == 3  # type: ignore[attr-defined]
    assert engine.pool._pre_ping is True  # type: ignore[attr-defined]
    assert engine.url.drivername == "postgresql+asyncpg"
    assert "pw-s3cret" not in repr(engine)


def test_engine_passes_server_settings() -> None:
    assert SERVER_SETTINGS == {"application_name": "ai-waiter", "timezone": "UTC"}


def test_sessionmaker_does_not_expire_on_commit() -> None:
    db = _database()
    maker = db.sessionmaker
    assert db.sessionmaker is maker
    assert maker.kw["expire_on_commit"] is False
    assert maker.kw["bind"] is db.engine


async def test_start_does_not_create_engine() -> None:
    db = _database()
    await db.start()
    assert db._engine is None


async def test_stop_without_engine_is_noop() -> None:
    db = _database()
    await db.stop()
    assert db._engine is None


async def test_stop_disposes_engine_and_allows_restart() -> None:
    db = _database()
    fake = _FakeEngine()
    db._engine = fake  # type: ignore[assignment]
    _ = db.sessionmaker
    await db.stop()
    await db.stop()
    assert fake.disposed == 1
    assert db._engine is None
    assert db._sessionmaker is None


async def test_session_yields_async_session_and_closes_it() -> None:
    db = _database()
    async with db.session() as session:
        assert isinstance(session, AsyncSession)
        assert session.bind is db.engine
    await db.stop()


async def test_ping_ok() -> None:
    db = _database()
    fake = _FakeEngine()
    db._engine = fake  # type: ignore[assignment]
    assert await db.ping() is True
    assert fake.executed == ["SELECT 1"]


async def test_ping_failure_returns_false_and_masks_password(caplog: pytest.LogCaptureFixture) -> None:
    db = _database()
    try:
        raise OSError(f"cannot connect to {SECRET_URL}")
    except OSError as cause:
        error = ConnectionError("password pw-s3cret rejected")
        error.__cause__ = cause
    db._engine = _FakeEngine(error)  # type: ignore[assignment]
    with caplog.at_level(logging.WARNING, logger="app.db.session"):
        assert await db.ping() is False
    [record] = caplog.records
    message = record.getMessage()
    assert "pw-s3cret" not in message
    assert "db.invalid" not in message
    assert "ai_waiter" not in message
    assert "ConnectionError: password *** rejected" in message
    assert "OSError: cannot connect to postgresql+asyncpg://***:***@***:***/***" in message
    assert record.exc_info is None
    assert getattr(record, "component", None) == "database"


async def test_ping_does_not_swallow_cancellation() -> None:
    db = _database()
    db._engine = _FakeEngine(asyncio.CancelledError())  # type: ignore[assignment]
    with pytest.raises(asyncio.CancelledError):
        await db.ping()


def test_describe_error_masks_url_encoded_password() -> None:
    db = _database("postgresql+asyncpg://u:p%40ss%2Fword@db.invalid/x")
    text = db.describe_error(RuntimeError("raw p@ss/word, quoted p%40ss%2Fword"))
    assert "p@ss/word" not in text
    assert "p%40ss%2Fword" not in text
    assert text == "RuntimeError: raw ***, quoted ***"


def test_describe_error_without_password_and_empty_message() -> None:
    db = _database("postgresql+asyncpg://u@db.invalid/x")
    try:
        try:
            raise ValueError("inner")
        except ValueError:
            raise TimeoutError from None
    except TimeoutError as exc:
        assert db.describe_error(exc) == "TimeoutError"


def test_describe_error_follows_implicit_context_once() -> None:
    db = _database()
    try:
        try:
            raise KeyError("first")
        except KeyError:
            raise RuntimeError("second")  # noqa: B904 — проверяется неявный __context__
    except RuntimeError as exc:
        exc.__context__.__context__ = exc  # type: ignore[union-attr]  — цикл не зацикливает обход
        assert db.describe_error(exc) == "RuntimeError: second <- KeyError: 'first'"


def test_describe_error_with_unparsable_url_hides_text() -> None:
    """Нечисловой порт: ``make_url`` бросает и в ``_mask`` — где пароль, неизвестно, текст не показывается."""
    db = _database("postgresql+asyncpg://u:Unparsable-Pa55@db.invalid:port/x")
    text = db.describe_error(ValueError("invalid literal for int(): 'port' in u:Unparsable-Pa55@db.invalid"))
    assert text == UNPARSABLE_URL_TEXT
    assert "Unparsable-Pa55" not in text


# ---------------------------------------------------------------- #73: маскирование всех деталей подключения
# arch: docs/arch/feature-73-describe-error-mask.md (решения 1–6), spec: AC-1, E-1…E-13.

URL_73 = "postgresql+asyncpg://waiter_user:pw-s3cret@192.0.2.10:5433/waiter_db"


def test_describe_error_masks_all_url_parts() -> None:
    """AC-1: хост, порт, пользователь, база и пароль → ``***``; тип и остальной текст сохранены."""
    db = _database(URL_73)
    error = OSError(
        'connection to server at "192.0.2.10", port 5433 failed: '
        'password pw-s3cret rejected for user "waiter_user" database "waiter_db"'
    )
    assert db.describe_error(error) == (
        'OSError: connection to server at "***", port *** failed: password *** rejected for user "***" database "***"'
    )


def test_describe_error_masks_whole_url_leaving_scheme() -> None:
    """E-10: в тексте вся строка подключения — остаётся только схема с драйвером."""
    db = _database(URL_73)
    assert db.describe_error(RuntimeError(f"cannot connect to {URL_73}")) == (
        "RuntimeError: cannot connect to postgresql+asyncpg://***:***@***:***/***"
    )


def test_describe_error_keeps_exception_type_names() -> None:
    """E-4 и решение 3: имя типа не маскируется, даже если пользователь совпадает с ним."""
    db = _database("postgresql+asyncpg://OSError:pw@db.example.com/x")
    text = db.describe_error(OSError('auth failed for user "OSError"; RuntimeErrorx'))
    assert text == 'OSError: auth failed for user "***"; RuntimeErrorx'


def test_describe_error_masks_query_hosts_ports_and_password() -> None:
    """E-7 и решение 1: ``?host=h:p`` (повтор ключа), ``[v6]:p`` и ``?password=`` маскируются."""
    db = _database("postgresql+asyncpg://w@/x?host=192.0.2.10:5432&host=[2001:db8::2]:5434&password=q-pw")
    text = db.describe_error(OSError("h 192.0.2.10:5432 [2001:db8::2]:5434 port 5434 q-pw"))
    assert text.startswith("OSError: h ")
    for value in ("192.0.2.10", "5432", "2001:db8::2", "5434", "q-pw"):
        assert value not in text


def test_describe_error_masks_resolved_ip_literals() -> None:
    """E-13 и решение 4: в URL домен, драйвер печатает IP — любой литерал IP маскируется; время — нет."""
    db = _database("postgresql+asyncpg://w:pw@db.example.com/x")
    text = db.describe_error(OSError("Connect call failed ('192.0.2.10', 5432) [2001:db8::1] at 12:30:45"))
    assert text == "OSError: Connect call failed ('***', 5432) [***] at 12:30:45"


def test_describe_error_does_not_mask_default_port() -> None:
    """E-1: порт не указан — ``5432`` драйвера остаётся; хост, пользователь и база маскируются."""
    db = _database("postgresql+asyncpg://waiter_user:pw@db.example.com/waiter_db")
    text = db.describe_error(OSError('server "db.example.com" port 5432: user "waiter_user" db "waiter_db"'))
    assert text == 'OSError: server "***" port 5432: user "***" db "***"'


def test_describe_error_masks_explicit_default_port() -> None:
    """Решение 5: явно указанный порт маскируется, даже если он равен порту по умолчанию."""
    db = _database("postgresql+asyncpg://w:pw@db.example.com:5432/x")
    assert db.describe_error(OSError("port 5432 failed")) == "OSError: port *** failed"


@pytest.mark.parametrize(
    ("url", "message", "expected"),
    [
        # E-2: пользователь и база совпадают.
        ("postgresql+asyncpg://waiter:pw@db.example.com/waiter", "user waiter db waiter", "user *** db ***"),
        # E-3: одно значение — подстрока другого; хвостов вроде ***_db нет.
        (
            "postgresql+asyncpg://waiter:pw@db.example.com/waiter_db",
            'user "waiter" database "waiter_db"',
            'user "***" database "***"',
        ),
        ("postgresql+asyncpg://w:pw@db.example.com/db", "host db.example.com database db", "host *** database ***"),
    ],
)
def test_describe_error_overlapping_values_masked_without_tails(url: str, message: str, expected: str) -> None:
    assert _database(url).describe_error(RuntimeError(message)) == f"RuntimeError: {expected}"


@pytest.mark.parametrize(
    ("url", "message", "expected"),
    [
        # Security review #73 (LOW): пароль — часть пользователя или IP; хвостов ad*** и 192.0.2.*** нет.
        ("postgresql+asyncpg://admin:min@db.example.com/x", 'role "admin" failed', 'role "***" failed'),
        (
            "postgresql+asyncpg://u:10@192.0.2.10/x",
            "Connect call failed ('192.0.2.10', 5432)",
            "Connect call failed ('***', 5432)",
        ),
        # Пароль вплотную к токену: токен ищется и в копии с вырезанным паролем.
        ("postgresql+asyncpg://admin:pw-s3cret@db.example.com/x", "adminpw-s3cret", "******"),
        # Пароль внутри домена, домен — токен целиком.
        ("postgresql+asyncpg://u:example@db.example.com/x", "host db.example.com", "host ***"),
    ],
)
def test_describe_error_password_inside_other_values_leaves_no_tails(url: str, message: str, expected: str) -> None:
    assert _database(url).describe_error(RuntimeError(message)) == f"RuntimeError: {expected}"


def test_describe_error_token_boundaries() -> None:
    """E-4: отдельный токен через дефис маскируется, значение внутри числа или слова — нет."""
    db = _database("postgresql+asyncpg://u:pw@db.example.com:5432/waiter")
    text = db.describe_error(RuntimeError("app ai-waiter port 15432 user u in RuntimeErrorU waiterdb"))
    assert text == "RuntimeError: app ai-*** port 15432 user *** in RuntimeErrorU waiterdb"


def test_describe_error_tokens_are_case_insensitive_password_is_not() -> None:
    """E-5: хост и пользователь — без учёта регистра; пароль — с учётом (другой регистр — не тот пароль)."""
    db = _database("postgresql+asyncpg://Waiter:Pw-Secret@db.example.com/x")
    text = db.describe_error(OSError("DB.Example.COM WAITER Pw-Secret pw-secret"))
    assert text == "OSError: *** *** *** pw-secret"


def test_describe_error_masks_ipv6_host_in_brackets() -> None:
    """E-6: IPv6 в URL — маскируется в скобках и без; скобки вокруг ``***`` допустимы."""
    db = _database("postgresql+asyncpg://w:pw@[2001:db8::1]:5433/x")
    text = db.describe_error(OSError("at [2001:db8::1]:5433 and 2001:DB8::1 port 5433"))
    assert text == "OSError: at [***]:*** and *** port ***"


def test_describe_error_url_without_password() -> None:
    """E-8: без пароля маскируются хост, пользователь и база; сообщение без значений не меняется."""
    db = _database("postgresql+asyncpg://waiter@db.example.com/waiter_db")
    assert db.describe_error(OSError('user "waiter" on db.example.com/waiter_db')) == 'OSError: user "***" on ***/***'
    assert db.describe_error(OSError("timeout expired")) == "OSError: timeout expired"


def test_describe_error_masks_url_encoded_user_and_database() -> None:
    """E-9: пользователь и база маскируются в декодированном и закодированном виде."""
    db = _database("postgresql+asyncpg://svc%2Bwaiter:pw@db.example.com/my%2Fdb")
    text = db.describe_error(OSError("svc+waiter svc%2Bwaiter my/db my%2Fdb"))
    assert text == "OSError: *** *** *** ***"


def test_describe_error_masks_multihost_netloc() -> None:
    """Список хостов в netloc (``h1,h2:port``) — целиком и каждый хост по отдельности."""
    db = _database("postgresql+asyncpg://w:pw@192.0.2.10,db2.example.com:5433/x")
    text = db.describe_error(OSError("hosts 192.0.2.10,db2.example.com; failed db2.example.com:5433"))
    assert text == "OSError: hosts ***; failed ***:***"


def test_describe_error_masks_unix_socket_path() -> None:
    """``?host=/var/run/postgresql`` — путь сокета маскируется как токен, имя файла сокета остаётся."""
    db = _database("postgresql+asyncpg://w:pw@/x?host=/var/run/postgresql")
    text = db.describe_error(OSError("connect to /var/run/postgresql/.s.PGSQL.5432 failed"))
    assert text == "OSError: connect to ***/.s.PGSQL.5432 failed"


def test_describe_error_masks_query_user_database_and_passfile() -> None:
    """E-7: ``?user=``, ``?database=``, ``?port=`` и ``?passfile=`` — как userinfo, база и порт."""
    db = _database(
        "postgresql+asyncpg://w@db.example.com/x?user=other_user&database=other_db&port=6543&passfile=pgpass.conf"
    )
    text = db.describe_error(OSError("other_user other_db 6543 pgpass.conf ssl"))
    assert text == "OSError: *** *** *** *** ssl"


def test_describe_error_does_not_mask_other_query_values() -> None:
    """Решение 1: прочие параметры query (``ssl``, ``prepared_statement_cache_size``) не маскируются."""
    db = _database("postgresql+asyncpg://w:pw@db.example.com/x?ssl=require&prepared_statement_cache_size=0")
    assert db.describe_error(OSError("ssl require, cache 0")) == "OSError: ssl require, cache 0"


def test_describe_error_masks_each_message_in_cause_chain() -> None:
    """Решение 3: маскируется каждое сообщение цепочки; разделитель и имена типов — как есть."""
    db = _database(URL_73)
    try:
        raise OSError("at 192.0.2.10")
    except OSError as cause:
        error = ConnectionError('user "waiter_user"')
        error.__cause__ = cause
    assert db.describe_error(error) == 'ConnectionError: user "***" <- OSError: at ***'


def test_describe_error_url_secrets_failure_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Решение 6: исключение в ``_url_secrets`` даёт ``UNPARSABLE_URL_TEXT``, как ошибка ``make_url``."""

    def broken(url: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("app.db.session._url_secrets", broken)
    assert _database(URL_73).describe_error(OSError("pw-s3cret")) == UNPARSABLE_URL_TEXT


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("at 192.0.2.10:5432", "at ***:5432"),
        ("('198.51.100.7', 5432)", "('***', 5432)"),
        ("[2001:db8::1]:5433", "[***]:5433"),
        ("host ::1 port", "host *** port"),
        ("addr 2001:db8::7: refused", "addr ***: refused"),
        ("mapped ::ffff:192.0.2.10.", "mapped ***."),
        ("zone fe80::1%eth0", "zone ***%eth0"),
        ("seq 192.0.2.4.5", "seq ***.5"),
        ("time 12:30:45", "time 12:30:45"),
        ("bad 1.2.300.4", "bad 1.2.300.4"),
        ("v1.2 and 10.0", "v1.2 and 10.0"),
        ("ab:cd:ef deadbeef", "ab:cd:ef deadbeef"),
        ("no ip here", "no ip here"),
    ],
)
def test_mask_ip_literals(text: str, expected: str) -> None:
    assert _mask_ip_literals(text) == expected


ORACLE_URLS = [
    URL_73,
    "postgresql+asyncpg://waiter:pw@db.example.com/waiter_db",
    "postgresql+asyncpg://us%40er:p%40ss@[2001:db8::1]:5433/my%2Fdb",
    "postgresql+asyncpg://w:pw@192.0.2.10,192.0.2.11:5433/x",
    "postgresql+asyncpg://w:pw@/x?host=/var/run/postgresql",
    "postgresql+asyncpg://w:pw@/x?host=192.0.2.10:5432&host=192.0.2.11:5433",
    "postgresql+asyncpg://w:pw@/x?host=192.0.2.10&port=6543",
    "postgresql+asyncpg://w@db.example.com/x?user=other&password=pw2&database=other_db",
]


@pytest.mark.parametrize("url", ORACLE_URLS)
def test_url_secrets_cover_asyncpg_connect_args(url: str) -> None:
    """Оракул: всё, что диалект asyncpg передаёт драйверу как host/port/user/password/database, маскируется."""
    secrets = _url_secrets(make_url(url))
    opts = PGDialect_asyncpg().create_connect_args(make_url(url))[1]
    checked = 0
    for key in ("host", "port", "user", "password", "database"):
        raw = opts.get(key)
        for value in raw if isinstance(raw, list) else [raw]:
            if value is None:
                continue
            checked += 1
            if key == "password":
                assert value in secrets.substrings, (key, value)
            else:
                assert str(value) in secrets.tokens, (key, value)
    assert checked >= 3


def test_describe_error_masks_query_ipv6_host_without_port() -> None:
    """E-6, E-7: ``?host=[2001:db8::3]`` без порта — адрес маскируется, остальной текст сохранён (G5 #73)."""
    db = _database("postgresql+asyncpg://w:pw@/x?host=[2001:db8::3]")
    secrets = _url_secrets(make_url("postgresql+asyncpg://w:pw@/x?host=[2001:db8::3]"))
    assert "2001:db8::3" in secrets.tokens
    assert db.describe_error(OSError("cannot reach 2001:db8::3 for w")) == "OSError: cannot reach *** for ***"


def test_describe_error_with_password_only_masks_password_and_ip_literals() -> None:
    """FR-1, E-13: в URL только пароль (нет пользователя, хоста, порта и базы) — токенов нет,
    маскируются пароль и литералы IP, остальной текст не меняется (G5 #73)."""
    url = "postgresql+asyncpg://:only-pw@"
    assert _url_secrets(make_url(url)).tokens == ()
    db = _database(url)
    assert db.describe_error(OSError("bad only-pw at 192.0.2.7 for user x")) == "OSError: bad *** at *** for user x"
