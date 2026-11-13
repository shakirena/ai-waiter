"""Сервисы ``app.guest`` без БД (#76, #78, #79): ветви, недостижимые на настоящем PostgreSQL без
искусственных условий — исчерпание попыток открыть визит, отказ до запроса в БД, «чужая»
``IntegrityError`` при перевыпуске токена."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.guest import entry, tokens, visits
from app.guest.errors import GuestSessionInvalidError, QrInvalidError, VisitOpenConflictError
from app.guest.session import GuestSessionClaims
from app.models.enums import Lang
from app.seed.data import DEMO_TENANT_ID


class _EmptyResult:
    def scalar_one_or_none(self) -> None:
        return None


class EmptySession:
    """Каждый запрос возвращает пустой результат: «визит закрыли между шагами» на каждой попытке."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _EmptyResult:
        self.statements.append(statement)
        return _EmptyResult()


class ForbiddenSession:
    """Запрос в БД — ошибка теста: проверка должна отказать раньше."""

    async def execute(self, statement: Any) -> Any:
        raise AssertionError("запрос в БД не ожидался")

    async def commit(self) -> None:
        raise AssertionError("commit не ожидался")


async def test_get_or_open_visit_gives_up_after_attempts() -> None:
    session = EmptySession()
    with pytest.raises(VisitOpenConflictError):
        await visits.get_or_open_visit(
            session,  # type: ignore[arg-type]
            tenant_id=uuid.uuid4(),
            table_id=uuid.uuid4(),
            lang=Lang.AZ,
        )
    assert len(session.statements) == 2 * visits.OPEN_VISIT_ATTEMPTS  # UPDATE + INSERT на попытку


@pytest.mark.parametrize("token", ["", "short", "a" * 65, "a" * 30 + "\n"])
async def test_enter_table_rejects_format_without_query(token: str) -> None:
    with pytest.raises(QrInvalidError):
        await entry.enter_table(
            ForbiddenSession(),  # type: ignore[arg-type]
            token=token,
            requested_lang=None,
            session_claims=None,
            accept_language=None,
            reject_demo=False,
        )


async def test_load_guest_context_rejects_demo_before_query() -> None:
    """FR-4: демо-проверка — сравнение с константой, без запроса в БД (ADR-9.6)."""
    claims = GuestSessionClaims(vid=uuid.uuid4(), tid=DEMO_TENANT_ID, tbl=uuid.uuid4(), tia=0, lang=Lang.RU, iat=0)
    with pytest.raises(GuestSessionInvalidError, match="demo"):
        await entry.load_guest_context(ForbiddenSession(), claims, reject_demo=True)  # type: ignore[arg-type]


class _ConstraintError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__("violation")
        self.constraint_name = name


def _integrity_error(constraint: str) -> IntegrityError:
    orig = Exception("asyncpg wrapper")
    orig.__cause__ = _ConstraintError(constraint)
    return IntegrityError("UPDATE tables", {}, orig)


class FailingNestedSession:
    def __init__(self, error: IntegrityError) -> None:
        self.error = error
        self.attempts = 0

    @asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        yield

    async def execute(self, statement: Any) -> Any:
        self.attempts += 1
        raise self.error


async def test_reissue_reraises_other_integrity_error_immediately() -> None:
    session = FailingNestedSession(_integrity_error("fk_tables_tenant_id_hall_id_halls"))
    with pytest.raises(IntegrityError):
        await tokens.reissue_table_token(session, tenant_id=uuid.uuid4(), table_id=uuid.uuid4())  # type: ignore[arg-type]
    assert session.attempts == 1


async def test_reissue_integrity_error_without_orig_is_not_collision() -> None:
    error = IntegrityError("UPDATE tables", {}, Exception("x"))
    error.orig = None  # type: ignore[assignment]
    session = FailingNestedSession(error)
    with pytest.raises(IntegrityError):
        await tokens.reissue_table_token(session, tenant_id=uuid.uuid4(), table_id=uuid.uuid4())  # type: ignore[arg-type]
    assert session.attempts == 1


async def test_reissue_collision_retries_up_to_limit() -> None:
    session = FailingNestedSession(_integrity_error(tokens.QR_TOKEN_CONSTRAINT))
    with pytest.raises(IntegrityError):
        await tokens.reissue_table_token(session, tenant_id=uuid.uuid4(), table_id=uuid.uuid4())  # type: ignore[arg-type]
    assert session.attempts == tokens.REISSUE_ATTEMPTS
