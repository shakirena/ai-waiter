"""QR-токен стола: генерация и перевыпуск (#9, ADR-9.5, ТЗ FR-1).

- ``generate_qr_token`` — ``secrets.token_urlsafe(QR_TOKEN_BYTES)``: 192 бита, 32 символа base64url,
  соответствует ``QR_TOKEN_PATTERN`` (≥ 128 бит). Новые столы (#16, #27) получают токен только отсюда;
  детерминированный ``app.seed.data.dev_token`` — только для dev.
- ``reissue_table_token`` — «отзыв» FR-1: старый токен перестаёт находиться сразу после commit,
  сессии по нему отвергаются по ``tia`` (ADR-9.2). История токенов не хранится.

Токен не пишется в лог — только ``tenant_id``/``table_id`` (Security, риск R-2).
"""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from typing import Final

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.guest.errors import TableNotFoundError
from app.models.enums import QR_TOKEN_PATTERN
from app.models.tenant import Table

logger = logging.getLogger(__name__)

QR_TOKEN_BYTES: Final = 24
# Повторы перевыпуска при коллизии по uq_tables_qr_token (практически невозможна), каждый — в SAVEPOINT.
REISSUE_ATTEMPTS: Final = 3

QR_TOKEN_RE: Final = re.compile(QR_TOKEN_PATTERN)
# Имя ограничения уникальности токена (naming convention, app/db/base.py).
QR_TOKEN_CONSTRAINT: Final = "uq_tables_qr_token"  # noqa: S105 — имя ограничения, не секрет


def generate_qr_token() -> str:
    """Новый QR-токен: ``secrets.token_urlsafe(QR_TOKEN_BYTES)``."""
    return secrets.token_urlsafe(QR_TOKEN_BYTES)


def is_valid_token_format(token: str) -> bool:
    """Проверка формата до запроса в БД (ADR-9.5): ``QR_TOKEN_RE.fullmatch(token)``.

    Именно ``fullmatch``: ``$`` в ``re.match`` пропускает завершающий ``\\n``. Токен регистрозависим
    и не нормализуется (пробелы, регистр — не совпадение, spec E-4)."""
    return isinstance(token, str) and QR_TOKEN_RE.fullmatch(token) is not None


def _is_token_collision(error: IntegrityError) -> bool:
    """Нарушено именно ``uq_tables_qr_token`` (имя ограничения из исключения asyncpg)."""
    cause = error.orig.__cause__ if error.orig is not None else None
    return getattr(cause, "constraint_name", None) == QR_TOKEN_CONSTRAINT


async def reissue_table_token(session: AsyncSession, *, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Table:
    """``UPDATE tables SET qr_token = :new, token_issued_at = now() WHERE tenant_id = :t AND id = :id RETURNING *``.

    Стола нет — ``TableNotFoundError``. ``IntegrityError`` по ``uq_tables_qr_token`` — повтор с новым
    токеном внутри ``session.begin_nested()``, всего до ``REISSUE_ATTEMPTS`` попыток; иначе исключение
    пробрасывается. Commit делает вызывающий (#27 — эндпоинт админки).

    ``token_issued_at`` — ``clock_timestamp()``, а не ``now()``: ``now()`` — время начала транзакции,
    и перевыпуск в той же транзакции, где стол создан или уже перевыпускался, не изменил бы
    ``token_issued_at`` — сессии со старым ``tia`` остались бы действительны (ADR-9.2, R-Q3)."""
    statement = (
        update(Table)
        .where(Table.tenant_id == tenant_id, Table.id == table_id)
        .returning(Table)
        .execution_options(populate_existing=True)
    )
    attempt = 0
    while True:
        attempt += 1
        try:
            async with session.begin_nested():
                result = await session.execute(
                    statement.values(qr_token=generate_qr_token(), token_issued_at=func.clock_timestamp())
                )
                table = result.scalar_one_or_none()
        except IntegrityError as exc:
            if not _is_token_collision(exc) or attempt >= REISSUE_ATTEMPTS:
                raise
            logger.warning(
                "Коллизия нового QR-токена, повтор генерации",
                extra={"tenant_id": str(tenant_id), "table_id": str(table_id), "attempt": attempt},
            )
            continue
        if table is None:
            raise TableNotFoundError
        logger.info("QR-токен стола перевыпущен", extra={"tenant_id": str(tenant_id), "table_id": str(table_id)})
        return table
