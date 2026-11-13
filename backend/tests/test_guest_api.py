"""Гостевой API ``/api/guest/v1`` без БД (#75–#83; ADR-9.1, 9.2, 9.6, 9.7).

Сервисы ``app.guest.entry`` подменяются: здесь проверяются HTTP-слой и зависимость ``current_guest`` —
формат ответов и ошибок, атрибуты cookie, ``Cache-Control: no-store``, флаг ``reject_demo``,
rate-limit входа (429, ``Retry-After``, fail-open), 503 при недоступной БД, CSRF (только JSON).
Сценарии с настоящей БД — ``tests/db/test_guest_entry.py``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.exc import DBAPIError, IntegrityError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.api import guest as guest_api
from app.api.guest_auth import (
    GUEST_COOKIE_NAME,
    UNKNOWN_CLIENT_IP,
    GuestContext,
    client_ip_key,
    current_guest,
)
from app.core.config import Settings
from app.core.ratelimit import RateLimiter, RateLimitResult
from app.core.scheduler import TaskRegistry
from app.guest import entry as guest_entry
from app.guest.entry import EntryResult, GuestVisitView
from app.guest.errors import (
    GuestSessionInvalidError,
    LangNotSupportedError,
    QrInvalidError,
    TableInactiveError,
    VisitClosedError,
    VisitOpenConflictError,
)
from app.guest.session import GuestSessionClaims, GuestSessionCodec, issue_claims
from app.main import create_app
from app.models.enums import Lang
from app.models.tenant import Table, Tenant
from app.models.visit import Visit
from tests.conftest import make_settings
from tests.doubles import FakeRateLimiter, make_fake_container

ENTRY = "/api/guest/v1/entry"
SESSION = "/api/guest/v1/session"
LANG = "/api/guest/v1/session/lang"
TOKEN = "Abcdefghijklmnopqrstuvwxyz012345"  # формат QR_TOKEN_PATTERN, 32 символа
PROD = {"app_env": "prod", "public_base_url": "https://menu.example.com"}
TTL_SECONDS = 12 * 3600

TENANT_ID = uuid.UUID("01929a6e-0000-7000-8000-0000000000a1")
TABLE_ID = uuid.UUID("01929a6e-0000-7000-8000-0000000000b1")
VISIT_ID = uuid.UUID("01929a6e-0000-7000-8000-0000000000c1")
OPENED_AT = datetime(2026, 11, 4, 14, 5, tzinfo=UTC)
ISSUED_AT = datetime(2026, 11, 1, 8, 0, 0, 123456, tzinfo=UTC)


def _tenant(languages: list[str] | None = None) -> Tenant:
    return Tenant(id=TENANT_ID, name="Демо-ресторан", languages=languages or ["az", "ru"], currency="AZN")


def _table() -> Table:
    return Table(
        id=TABLE_ID,
        tenant_id=TENANT_ID,
        hall_id=uuid.uuid4(),
        name="Стол 1",
        type="table",
        price_tier="vip",
        external_id="pos-1",
        qr_token=TOKEN,
        token_issued_at=ISSUED_AT,
        is_active=True,
    )


def _visit() -> Visit:
    return Visit(id=VISIT_ID, tenant_id=TENANT_ID, table_id=TABLE_ID, status="open", lang="ru", opened_at=OPENED_AT)


def _claims(lang: Lang = Lang.RU, *, iat: datetime | None = None) -> GuestSessionClaims:
    return issue_claims(
        tenant_id=TENANT_ID,
        table_id=TABLE_ID,
        visit_id=VISIT_ID,
        token_issued_at=ISSUED_AT,
        lang=lang,
        now=iat or datetime.now(UTC),
    )


def _entry_result(*, created: bool = True, lang: Lang = Lang.RU) -> EntryResult:
    return EntryResult(
        tenant=_tenant(), table=_table(), visit=_visit(), created=created, lang=lang, claims=_claims(lang)
    )


def _view(lang: Lang = Lang.RU, *, languages: list[str] | None = None, iat: datetime | None = None) -> GuestVisitView:
    return GuestVisitView(tenant=_tenant(languages), table=_table(), visit=_visit(), claims=_claims(lang, iat=iat))


class Recorder:
    """Подмена сервисной функции: записывает аргументы, возвращает результат или бросает исключение."""

    def __init__(self, result: Any = None, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


class ScriptedLimiter(FakeRateLimiter):
    def __init__(self, result: RateLimitResult | None = None, error: Exception | None = None) -> None:
        super().__init__()
        self.result = result
        self.error = error
        self.keys: list[tuple[str, int, timedelta]] = []

    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult:
        self.keys.append((key, limit, window))
        if self.error is not None:
            raise self.error
        return self.result or RateLimitResult(allowed=True, limit=limit, remaining=limit - 1, retry_after=0.0)


def _build_app(settings: Settings, limiter: RateLimiter | None = None) -> FastAPI:
    """Приложение с контейнером-двойником без lifespan (prod-lifespan не нужен этим тестам)."""
    application = create_app(settings, registry=TaskRegistry())
    application.state.container = make_fake_container(settings, rate_limiter=limiter)  # type: ignore[arg-type]
    return application


@pytest.fixture
async def make_client() -> AsyncIterator[Callable[..., Any]]:
    clients: list[AsyncClient] = []

    async def factory(
        settings: Settings | None = None, *, limiter: RateLimiter | None = None, raise_errors: bool = True
    ) -> tuple[AsyncClient, FastAPI]:
        application = _build_app(settings or make_settings(), limiter)
        transport = ASGITransport(app=application, raise_app_exceptions=raise_errors)
        client = AsyncClient(transport=transport, base_url="http://testserver")
        clients.append(client)
        return client, application

    yield factory
    for client in clients:
        await client.aclose()


@pytest.fixture
def enter_table(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder(result=_entry_result())
    monkeypatch.setattr(guest_entry, "enter_table", recorder)
    return recorder


@pytest.fixture
def load_context(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder(result=_view())
    monkeypatch.setattr(guest_entry, "load_guest_context", recorder)
    return recorder


def _codec(application: FastAPI) -> GuestSessionCodec:
    codec: GuestSessionCodec = application.state.guest_session_codec
    return codec


def _cookie_header(application: FastAPI, claims: GuestSessionClaims | None = None) -> dict[str, str]:
    return {"Cookie": f"{GUEST_COOKIE_NAME}={_codec(application).encode(claims or _claims())}"}


def _set_cookie_attrs(response: Response) -> tuple[str, dict[str, str]]:
    """``Set-Cookie`` → (значение, атрибуты в нижнем регистре)."""
    [header] = response.headers.get_list("set-cookie")
    name_value, *attrs = [part.strip() for part in header.split(";")]
    name, _, value = name_value.partition("=")
    assert name == GUEST_COOKIE_NAME
    parsed: dict[str, str] = {}
    for attr in attrs:
        key, _, val = attr.partition("=")
        parsed[key.lower()] = val
    return value, parsed


def _assert_error(response: Response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json() == {"detail": {"code": code}}
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers


# ================================================================ POST /entry


async def test_entry_success_body_and_cookie(make_client: Callable[..., Any], enter_table: Recorder) -> None:
    """AC-1 (#75): 200, данные заведения/стола/визита без внутренних идентификаторов, HttpOnly-cookie."""
    client, application = await make_client()
    response = await client.post(ENTRY, json={"token": TOKEN}, headers={"Accept-Language": "ru-RU"})
    assert response.status_code == 200
    assert response.json() == {
        "tenant": {"name": "Демо-ресторан", "languages": ["az", "ru"], "default_lang": "az", "currency": "AZN"},
        "table": {"name": "Стол 1", "type": "table"},
        "visit": {"id": str(VISIT_ID), "opened_at": "2026-11-04T14:05:00Z", "is_new": True},
        "lang": "ru",
    }
    for leaked in (str(TENANT_ID), str(TABLE_ID), TOKEN, "vip", "pos-1", "tenant_id", "price_tier"):
        assert leaked not in response.text
    assert response.headers["cache-control"] == "no-store"

    value, attrs = _set_cookie_attrs(response)
    assert attrs == {"httponly": "", "max-age": str(TTL_SECONDS), "path": "/api/guest/", "samesite": "strict"}
    assert "domain" not in attrs and "secure" not in attrs  # test-окружение, http://localhost
    assert _codec(application).decode(value) == enter_table.result.claims
    assert TOKEN not in value

    [(_, kwargs)] = enter_table.calls
    assert kwargs == {
        "token": TOKEN,
        "requested_lang": None,
        "session_claims": None,
        "accept_language": "ru-RU",
        "reject_demo": False,
    }


async def test_entry_rejoin_returns_is_new_false(make_client: Callable[..., Any], enter_table: Recorder) -> None:
    enter_table.result = _entry_result(created=False, lang=Lang.AZ)
    client, _ = await make_client()
    response = await client.post(ENTRY, json={"token": TOKEN, "lang": "az"})
    assert response.json()["visit"]["is_new"] is False
    assert response.json()["lang"] == "az"
    assert enter_table.calls[0][1]["requested_lang"] is Lang.AZ


async def test_entry_passes_claims_of_existing_cookie(make_client: Callable[..., Any], enter_table: Recorder) -> None:
    """Шаг 2 выбора языка: действующая cookie передаётся сервису; битая — как отсутствующая."""
    client, application = await make_client()
    claims = _claims(Lang.AZ)
    await client.post(ENTRY, json={"token": TOKEN}, headers=_cookie_header(application, claims))
    await client.post(ENTRY, json={"token": TOKEN}, headers={"Cookie": f"{GUEST_COOKIE_NAME}=v1.bad.sig"})
    assert [kwargs["session_claims"] for _, kwargs in enter_table.calls] == [claims, None]


@pytest.mark.parametrize(
    ("overrides", "secure", "reject_demo"),
    [
        ({}, False, False),
        ({"app_env": "dev"}, False, False),
        (PROD, True, True),
        ({**PROD, "guest_cookie_secure": False}, False, True),
        ({"guest_cookie_secure": True}, True, False),
    ],
)
async def test_entry_secure_cookie_and_reject_demo_flags(
    make_client: Callable[..., Any],
    enter_table: Recorder,
    overrides: dict[str, Any],
    secure: bool,
    reject_demo: bool,
) -> None:
    """ADR-9.2: ``Secure`` по ``GUEST_COOKIE_SECURE`` (по умолчанию в prod); FR-4: ``reject_demo`` только в prod."""
    client, _ = await make_client(make_settings(**overrides))
    response = await client.post(ENTRY, json={"token": TOKEN})
    _, attrs = _set_cookie_attrs(response)
    assert ("secure" in attrs) is secure
    assert enter_table.calls[0][1]["reject_demo"] is reject_demo


async def test_entry_ttl_from_settings(make_client: Callable[..., Any], enter_table: Recorder) -> None:
    client, _ = await make_client(make_settings(guest_session_ttl_hours=2))
    _, attrs = _set_cookie_attrs(await client.post(ENTRY, json={"token": TOKEN}))
    assert attrs["max-age"] == "7200"


async def test_entry_invalid_token_responses_are_identical(
    make_client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-3 (#77): неверный формат (настоящий сервис, без БД) и неизвестный/перевыпущенный/демо токен
    (подменённый сервис) отвечают одинаково: код, тело, заголовки, без cookie."""
    client, _ = await make_client()
    by_format = await client.post(ENTRY, json={"token": "short"})
    monkeypatch.setattr(guest_entry, "enter_table", Recorder(error=QrInvalidError()))
    unknown = await client.post(ENTRY, json={"token": TOKEN})
    for response in (by_format, unknown):
        _assert_error(response, 404, "qr_invalid")
    assert by_format.content == unknown.content
    assert dict(by_format.headers) == dict(unknown.headers)


async def test_entry_format_check_does_not_touch_database(make_client: Callable[..., Any]) -> None:
    """E-4: токен не по формату отвергается до запроса в БД (FakeSession не умеет выполнять запросы)."""
    client, _ = await make_client()
    for token in ("a" * 21, "a" * 65, " " + "a" * 30, "a" * 30 + "\n", "a" * 30 + "="):
        _assert_error(await client.post(ENTRY, json={"token": token}), 404, "qr_invalid")


async def test_entry_table_inactive(make_client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """E-5: отключённый стол — 403 ``table_inactive`` без данных заведения и стола."""
    monkeypatch.setattr(guest_entry, "enter_table", Recorder(error=TableInactiveError()))
    client, _ = await make_client()
    _assert_error(await client.post(ENTRY, json={"token": TOKEN}), 403, "table_inactive")


async def test_entry_visit_conflict_is_try_again(
    make_client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(guest_entry, "enter_table", Recorder(error=VisitOpenConflictError()))
    client, _ = await make_client()
    with caplog.at_level(logging.WARNING, logger="app.api.guest"):
        _assert_error(await client.post(ENTRY, json={"token": TOKEN}), 503, "try_again")
    assert any(r.levelno == logging.WARNING for r in caplog.records)


@pytest.mark.parametrize(
    "body",
    [{}, {"token": ""}, {"token": "a" * 129}, {"token": TOKEN, "lang": "en"}, {"token": 123}],
    ids=["missing", "empty", "too-long", "lang", "type"],
)
async def test_entry_body_validation_is_standard_422(
    make_client: Callable[..., Any], enter_table: Recorder, body: dict[str, Any]
) -> None:
    client, _ = await make_client()
    response = await client.post(ENTRY, json=body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert response.headers["cache-control"] == "no-store"
    assert enter_table.calls == []


async def test_entry_rejects_non_json_body(make_client: Callable[..., Any], enter_table: Recorder) -> None:
    """NFR-5 (CSRF): form и text/plain — 422, сервис не вызывается."""
    client, _ = await make_client()
    form = await client.post(ENTRY, data={"token": TOKEN})
    text = await client.post(ENTRY, content=f'{{"token": "{TOKEN}"}}', headers={"Content-Type": "text/plain"})
    assert form.status_code == text.status_code == 422
    assert enter_table.calls == []


async def test_entry_get_is_not_allowed(make_client: Callable[..., Any], enter_table: Recorder) -> None:
    """ADR-9.1, E-16: превью ссылок делают GET — визит не открывается."""
    client, _ = await make_client()
    response = await client.get(ENTRY)
    assert response.status_code == 405
    assert enter_table.calls == []


# ---------------------------------------------------------------- 503: БД недоступна (E-15)


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("server closed the connection")),
        InterfaceError("SELECT 1", {}, Exception("connection is closed")),
        DBAPIError("SELECT 1", {}, Exception("lost"), connection_invalidated=True),
        PoolTimeoutError("QueuePool limit"),
        ConnectionRefusedError("connect to db.invalid failed"),
        TimeoutError(),
    ],
    ids=["operational", "interface", "invalidated", "pool-timeout", "refused", "timeout"],
)
async def test_database_unavailable_is_try_again_without_details(
    make_client: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    monkeypatch.setattr(guest_entry, "enter_table", Recorder(error=error))
    monkeypatch.setattr(guest_entry, "load_guest_context", Recorder(error=error))
    client, application = await make_client()
    with caplog.at_level(logging.WARNING, logger="app.api.guest"):
        entry = await client.post(ENTRY, json={"token": TOKEN})
        session = await client.get(SESSION, headers=_cookie_header(application))
    for response in (entry, session):
        _assert_error(response, 503, "try_again")
        assert "db.invalid" not in response.text
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert all(type(error).__name__ in r.getMessage() for r in warnings)


async def test_database_error_text_is_masked_in_log(
    make_client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """В лог — через ``Database.describe_error`` (#73), а без контейнера — только имя класса."""
    monkeypatch.setattr(guest_entry, "enter_table", Recorder(error=ConnectionRefusedError("secret-host")))
    client, application = await make_client()
    application.state.container.database.describe_error = lambda exc: "ConnectionRefusedError: ***"
    with caplog.at_level(logging.WARNING, logger="app.api.guest"):
        await client.post(ENTRY, json={"token": TOKEN})
    assert "secret-host" not in caplog.text
    assert "***" in caplog.text


def test_describe_db_error_without_container() -> None:
    class _State:
        pass

    class _App:
        state = _State()

    class _Request:
        app = _App()

    assert guest_api._describe_db_error(_Request(), OSError("x")) == "OSError"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "error",
    [RuntimeError("boom"), IntegrityError("INSERT", {}, Exception("dup")), DBAPIError("SELECT", {}, Exception("x"))],
    ids=["runtime", "integrity", "dbapi-not-invalidated"],
)
async def test_other_errors_are_500(
    make_client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(guest_entry, "enter_table", Recorder(error=error))
    client, _ = await make_client(raise_errors=False)
    response = await client.post(ENTRY, json={"token": TOKEN})
    assert response.status_code == 500


# ---------------------------------------------------------------- rate-limit входа (ADR-9.7)


async def test_entry_rate_limited(make_client: Callable[..., Any], enter_table: Recorder) -> None:
    """E-18: превышение — 429 ``rate_limited``, ``Retry-After`` вверх до целых секунд, сервис не вызывается."""
    limiter = ScriptedLimiter(RateLimitResult(allowed=False, limit=30, remaining=0, retry_after=12.2))
    client, _ = await make_client(limiter=limiter)
    response = await client.post(ENTRY, json={"token": TOKEN})
    _assert_error(response, 429, "rate_limited")
    assert response.headers["retry-after"] == "13"
    assert enter_table.calls == []
    assert limiter.keys == [("guest_entry:ip:127.0.0.1", 30, timedelta(seconds=60))]


async def test_entry_retry_after_is_at_least_one(make_client: Callable[..., Any], enter_table: Recorder) -> None:
    limiter = ScriptedLimiter(RateLimitResult(allowed=False, limit=30, remaining=0, retry_after=0.0))
    client, _ = await make_client(limiter=limiter)
    assert (await client.post(ENTRY, json={"token": TOKEN})).headers["retry-after"] == "1"


async def test_entry_rate_limit_counts_invalid_bodies(make_client: Callable[..., Any], enter_table: Recorder) -> None:
    """Считаются все попытки (ADR-9.7): лимит — зависимость, она выполняется до валидации тела."""
    limiter = ScriptedLimiter()
    client, _ = await make_client(make_settings(guest_entry_rate_limit=5), limiter=limiter)
    await client.post(ENTRY, json={"token": ""})
    await client.post(ENTRY, json={"token": TOKEN})
    assert [limit for _, limit, _ in limiter.keys] == [5, 5]


async def test_entry_rate_limit_disabled(make_client: Callable[..., Any], enter_table: Recorder) -> None:
    limiter = ScriptedLimiter(RateLimitResult(allowed=False, limit=1, remaining=0, retry_after=1.0))
    client, _ = await make_client(make_settings(guest_entry_rate_limit=0), limiter=limiter)
    assert (await client.post(ENTRY, json={"token": TOKEN})).status_code == 200
    assert limiter.keys == []


async def test_entry_rate_limiter_failure_is_fail_open(
    make_client: Callable[..., Any], enter_table: Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    """E-19: сбой лимитера не блокирует вход; WARNING с именами классов, без текста исключения."""
    error = ConnectionError("redis://:password@redis.invalid:6379")
    error.__cause__ = OSError("inner detail")
    client, _ = await make_client(limiter=ScriptedLimiter(error=error))
    with caplog.at_level(logging.WARNING, logger="app.api.guest"):
        response = await client.post(ENTRY, json={"token": TOKEN})
    assert response.status_code == 200
    [record] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "ConnectionError <- OSError" in record.getMessage()
    assert "password" not in caplog.text and "inner detail" not in caplog.text


def test_exception_chain_names_uses_context_and_stops_on_cycles() -> None:
    try:
        try:
            raise KeyError("a")
        except KeyError:
            raise ValueError("b")  # noqa: B904 — нужен __context__, а не __cause__
    except ValueError as exc:
        assert guest_api._exception_chain_names(exc) == "ValueError <- KeyError"
    cyclic = RuntimeError("x")
    cyclic.__cause__ = cyclic
    assert guest_api._exception_chain_names(cyclic) == "RuntimeError"
    suppressed = RuntimeError("y")
    suppressed.__context__ = KeyError("z")
    suppressed.__suppress_context__ = True
    assert guest_api._exception_chain_names(suppressed) == "RuntimeError"


async def test_entry_rate_limit_with_real_single_limiter() -> None:
    """Настоящий ``RateLimiter`` режима single (lifespan): третья попытка за минуту — 429."""
    application = create_app(make_settings(guest_entry_rate_limit=2), registry=TaskRegistry())
    async with application.router.lifespan_context(application):
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as ac:
            codes = [(await ac.post(ENTRY, json={"token": "bad"})).status_code for _ in range(3)]
    assert codes == [404, 404, 429]


async def test_entry_without_client_address_uses_unknown_key(enter_table: Recorder) -> None:
    limiter = ScriptedLimiter()
    application = _build_app(make_settings(), limiter)

    async def without_client(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await application({**scope, "client": None}, receive, send)

    async with AsyncClient(transport=ASGITransport(app=without_client), base_url="http://testserver") as ac:
        assert (await ac.post(ENTRY, json={"token": TOKEN})).status_code == 200
    assert limiter.keys[0][0] == f"guest_entry:ip:{UNKNOWN_CLIENT_IP}"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", "127.0.0.1"),
        ("203.0.113.7", "203.0.113.7"),
        ("2001:db8:1:2:3:4:5:6", "2001-0db8-0001-0002-0000-0000-0000-0000"),
        ("2001:db8:1:2::ffff", "2001-0db8-0001-0002-0000-0000-0000-0000"),  # тот же /64
        ("::ffff:198.51.100.1", "198.51.100.1"),
        ("fe80::1%eth0", "fe80-0000-0000-0000-0000-0000-0000-0000"),
        (None, UNKNOWN_CLIENT_IP),
        ("", UNKNOWN_CLIENT_IP),
        ("testclient", UNKNOWN_CLIENT_IP),
        ("1.2.3.4:80", UNKNOWN_CLIENT_IP),
    ],
)
def test_client_ip_key(host: str | None, expected: str) -> None:
    key = client_ip_key(host)
    assert key == expected
    assert ":" not in key and " " not in key


# ================================================================ GET /session и current_guest


async def test_session_returns_view_without_set_cookie(make_client: Callable[..., Any], load_context: Recorder) -> None:
    """AC-6 (#80): данные из сессии; cookie не переподписывается."""
    client, application = await make_client()
    claims = _claims(Lang.AZ)
    load_context.result = GuestVisitView(tenant=_tenant(), table=_table(), visit=_visit(), claims=claims)
    response = await client.get(SESSION, headers=_cookie_header(application, claims))
    assert response.status_code == 200
    assert response.json() == {
        "tenant": {"name": "Демо-ресторан", "languages": ["az", "ru"], "default_lang": "az", "currency": "AZN"},
        "table": {"name": "Стол 1", "type": "table"},
        "visit": {"id": str(VISIT_ID), "opened_at": "2026-11-04T14:05:00Z"},
        "lang": "az",
    }
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    [(args, kwargs)] = load_context.calls
    assert args[1] == claims
    assert kwargs == {"reject_demo": False}


async def test_session_ignores_client_supplied_ids(make_client: Callable[..., Any], load_context: Recorder) -> None:
    """NFR-2: ``tenant_id``/``visit_id`` из запроса не используются — только claims cookie."""
    client, application = await make_client()
    await client.get(
        SESSION,
        params={"tenant_id": str(uuid.uuid4()), "visit_id": str(uuid.uuid4())},
        headers=_cookie_header(application),
    )
    assert load_context.calls[0][0][1].tid == TENANT_ID


async def test_session_reject_demo_in_prod(make_client: Callable[..., Any], load_context: Recorder) -> None:
    client, application = await make_client(make_settings(**PROD))
    await client.get(SESSION, headers=_cookie_header(application))
    assert load_context.calls[0][1] == {"reject_demo": True}


@pytest.mark.parametrize(
    "cookie",
    [None, "", "garbage", "v1.a.b", "v2.a.b"],
)
async def test_session_required(make_client: Callable[..., Any], load_context: Recorder, cookie: str | None) -> None:
    """E-14: нет cookie, она повреждена или подделана — 401 ``guest_session_required`` без запроса в БД."""
    client, _ = await make_client()
    headers = {} if cookie is None else {"Cookie": f"{GUEST_COOKIE_NAME}={cookie}"}
    _assert_error(await client.get(SESSION, headers=headers), 401, "guest_session_required")
    assert load_context.calls == []


async def test_session_with_foreign_secret_or_expired(make_client: Callable[..., Any], load_context: Recorder) -> None:
    client, application = await make_client()
    other = GuestSessionCodec(b"x" * 32, ttl=timedelta(hours=12))
    forged = {"Cookie": f"{GUEST_COOKIE_NAME}={other.encode(_claims())}"}
    expired = _cookie_header(application, _claims(iat=datetime.now(UTC) - timedelta(hours=13)))
    for headers in (forged, expired):
        _assert_error(await client.get(SESSION, headers=headers), 401, "guest_session_required")
    assert load_context.calls == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (GuestSessionInvalidError("token_reissued"), "guest_session_invalid"),
        (GuestSessionInvalidError("not_found"), "guest_session_invalid"),
        (VisitClosedError(), "visit_closed"),
    ],
)
async def test_session_invalid_and_closed(
    make_client: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    code: str,
) -> None:
    monkeypatch.setattr(guest_entry, "load_guest_context", Recorder(error=error))
    client, application = await make_client()
    headers = _cookie_header(application)
    with caplog.at_level(logging.INFO, logger="app.api.guest_auth"):
        response = await client.get(SESSION, headers=headers)
    _assert_error(response, 401, code)
    assert str(VISIT_ID) not in response.text
    [record] = [r for r in caplog.records if r.name == "app.api.guest_auth"]
    assert record.levelno == logging.INFO
    assert record.code == code  # type: ignore[attr-defined]
    assert headers["Cookie"].split("=", 1)[1] not in caplog.text


async def test_current_guest_builds_context() -> None:
    view = _view(Lang.AZ)
    assert await current_guest(view) == GuestContext(
        tenant_id=TENANT_ID,
        table_id=TABLE_ID,
        visit_id=VISIT_ID,
        lang=Lang.AZ,
        price_tier="vip",
        languages=(Lang.AZ, Lang.RU),
        currency="AZN",
    )


# ================================================================ PUT /session/lang


async def test_change_lang_resigns_cookie_without_extending(
    make_client: Callable[..., Any], load_context: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-9 (#83): 200 с новым языком и переподписанной cookie; ``iat`` прежний, ``Max-Age`` — остаток."""
    issued = datetime.now(UTC) - timedelta(hours=2)
    load_context.result = _view(Lang.RU, iat=issued)
    change = Recorder(result=_view(Lang.AZ, iat=issued))
    monkeypatch.setattr(guest_entry, "change_lang", change)
    client, application = await make_client()
    response = await client.put(
        LANG, json={"lang": "az"}, headers=_cookie_header(application, load_context.result.claims)
    )
    assert response.status_code == 200
    assert response.json()["lang"] == "az"
    assert "is_new" not in response.json()["visit"]
    assert response.headers["cache-control"] == "no-store"
    value, attrs = _set_cookie_attrs(response)
    claims = _codec(application).decode(value)
    assert claims is not None and claims.lang is Lang.AZ
    assert claims.iat == load_context.result.claims.iat
    assert TTL_SECONDS - 2 * 3600 - 5 <= int(attrs["max-age"]) <= TTL_SECONDS - 2 * 3600
    assert attrs["httponly"] == "" and attrs["samesite"] == "strict" and attrs["path"] == "/api/guest/"
    [(args, _)] = change.calls
    assert args[1] is load_context.result and args[2] is Lang.AZ


async def test_change_lang_not_supported(
    make_client: Callable[..., Any], load_context: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E-12: язык вне ``tenants.languages`` — 422 ``lang_not_supported``, cookie не меняется."""
    monkeypatch.setattr(guest_entry, "change_lang", Recorder(error=LangNotSupportedError()))
    client, application = await make_client()
    _assert_error(
        await client.put(LANG, json={"lang": "az"}, headers=_cookie_header(application)), 422, "lang_not_supported"
    )


@pytest.mark.parametrize("body", [{"lang": "en"}, {"lang": None}, {}])
async def test_change_lang_invalid_value(
    make_client: Callable[..., Any], load_context: Recorder, monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]
) -> None:
    change = Recorder()
    monkeypatch.setattr(guest_entry, "change_lang", change)
    client, application = await make_client()
    response = await client.put(LANG, json=body, headers=_cookie_header(application))
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert response.headers["cache-control"] == "no-store"
    assert change.calls == []


async def test_change_lang_requires_json_body(
    make_client: Callable[..., Any], load_context: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Security arch (CSRF): ``text/plain`` и form — 422, а не 200."""
    change = Recorder()
    monkeypatch.setattr(guest_entry, "change_lang", change)
    client, application = await make_client()
    headers = _cookie_header(application)
    text = await client.put(LANG, content='{"lang": "az"}', headers={**headers, "Content-Type": "text/plain"})
    form = await client.put(LANG, data={"lang": "az"}, headers=headers)
    assert text.status_code == form.status_code == 422
    assert change.calls == []


async def test_change_lang_requires_session(make_client: Callable[..., Any], load_context: Recorder) -> None:
    client, _ = await make_client()
    _assert_error(await client.put(LANG, json={"lang": "az"}), 401, "guest_session_required")


# ================================================================ подключение и OpenAPI


async def test_router_and_codec_are_wired(app: FastAPI) -> None:
    assert {ENTRY, SESSION, LANG} <= set(app.openapi()["paths"])
    assert isinstance(app.state.guest_session_codec, GuestSessionCodec)


async def test_openapi_has_guest_paths_without_internal_details(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    assert {ENTRY, SESSION, LANG} <= set(schema["paths"])
    guest_text = str({path: schema["paths"][path] for path in (ENTRY, SESSION, LANG)}).lower()
    assert "demo" not in guest_text and "reject" not in guest_text
