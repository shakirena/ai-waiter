"""QR-токен стола: генерация и перевыпуск (#9, ADR-9.5, ТЗ FR-1).

- ``generate_qr_token`` — ``secrets.token_urlsafe(QR_TOKEN_BYTES)``: 192 бита, 32 символа base64url,
  соответствует ``QR_TOKEN_PATTERN`` (≥ 128 бит). Новые столы (#16, #27) получают токен только отсюда;
  детерминированный ``app.seed.data.dev_token`` — только для dev.
- ``reissue_table_token`` — «отзыв» FR-1: старый токен перестаёт находиться сразу после commit,
  сессии по нему отвергаются по ``tia`` (ADR-9.2). История токенов не хранится.

Токен не пишется в лог — только ``tenant_id``/``table_id`` (Security, риск R-2).
"""

from __future__ import annotations

import re
import uuid
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import QR_TOKEN_PATTERN
from app.models.tenant import Table

QR_TOKEN_BYTES: Final = 24
# Повторы перевыпуска при коллизии по uq_tables_qr_token (практически невозможна), каждый — в SAVEPOINT.
REISSUE_ATTEMPTS: Final = 3

QR_TOKEN_RE: Final = re.compile(QR_TOKEN_PATTERN)


def generate_qr_token() -> str:
    """Новый QR-токен: ``secrets.token_urlsafe(QR_TOKEN_BYTES)``."""
    raise NotImplementedError


def is_valid_token_format(token: str) -> bool:
    """Проверка формата до запроса в БД (ADR-9.5): ``QR_TOKEN_RE.fullmatch(token)``.

    Именно ``fullmatch``: ``$`` в ``re.match`` пропускает завершающий ``\\n``. Токен регистрозависим
    и не нормализуется (пробелы, регистр — не совпадение, spec E-4)."""
    raise NotImplementedError


async def reissue_table_token(session: AsyncSession, *, tenant_id: uuid.UUID, table_id: uuid.UUID) -> Table:
    """``UPDATE tables SET qr_token = :new, token_issued_at = now() WHERE tenant_id = :t AND id = :id RETURNING *``.

    Стола нет — ``TableNotFoundError``. ``IntegrityError`` по ``uq_tables_qr_token`` — повтор с новым
    токеном внутри ``session.begin_nested()``, всего до ``REISSUE_ATTEMPTS`` попыток; иначе исключение
    пробрасывается. Commit делает вызывающий (#27 — эндпоинт админки)."""
    raise NotImplementedError
