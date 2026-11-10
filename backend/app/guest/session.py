"""Гостевая сессия — подписанная cookie без таблицы в БД (#9, ADR-9.2).

Формат значения: ``v1.<payload>.<sig>``:

- ``payload`` — base64url без ``=`` от компактного JSON (``separators=(",", ":")``) с полями
  ``GuestSessionClaims``: ``vid``, ``tid``, ``tbl`` (UUID строкой), ``tia`` (``tables.token_issued_at``,
  целые микросекунды epoch), ``lang``, ``iat`` (секунды epoch). Личных данных нет (NFR-5);
- ``sig`` — base64url без ``=`` от ``HMAC-SHA256(secret, "v1." + payload)``; сверка через
  ``hmac.compare_digest``.

``decode`` никогда не бросает: неизвестная версия, битый base64/JSON, лишние/недостающие поля,
неверные типы, неверная подпись, истёкший ``iat + ttl`` → ``None`` («сессии нет»,
401 ``guest_session_required``). Проверки по БД (визит открыт, ``tia``, ``is_active``, демо) делает
``entry.load_guest_context``. Payload не зашифрован — в нём только UUID и язык.

Кодек от режима не зависит: один объект на приложение (``app.state.guest_session_codec``, создаёт
``create_app`` через ``build_guest_session_codec``). ``Settings`` модуль не читает.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from app.models.enums import Lang

logger = logging.getLogger(__name__)

SESSION_FORMAT_VERSION: Final = "v1"
# Значение длиннее — не разбирается (настоящее значение ~250 символов).
MAX_SESSION_VALUE_LENGTH: Final = 1024
MIN_SECRET_LENGTH: Final = 32

RANDOM_KEY_WARNING: Final = (
    "GUEST_SESSION_SECRET не задан: ключ подписи гостевых сессий случайный на процесс, "
    "после перезапуска гости входят заново по QR-коду"
)


@dataclass(frozen=True, slots=True)
class GuestSessionClaims:
    """Поля payload cookie (ADR-9.2)."""

    vid: uuid.UUID  # visits.id
    tid: uuid.UUID  # tenants.id
    tbl: uuid.UUID  # tables.id
    tia: int  # tables.token_issued_at, микросекунды epoch
    lang: Lang
    iat: int  # время выдачи, секунды epoch


def epoch_micros(value: datetime) -> int:
    """``timestamptz`` → целые микросекунды epoch, без потерь точности (не через ``float``):
    ``(value - EPOCH_UTC) // timedelta(microseconds=1)``. Наивное время — ``ValueError``."""
    raise NotImplementedError


def issue_claims(
    *,
    tenant_id: uuid.UUID,
    table_id: uuid.UUID,
    visit_id: uuid.UUID,
    token_issued_at: datetime,
    lang: Lang,
    now: datetime | None = None,
) -> GuestSessionClaims:
    """Claims новой сессии: ``tia = epoch_micros(token_issued_at)``, ``iat`` — ``now`` (по умолчанию —
    текущее UTC) в целых секундах."""
    raise NotImplementedError


class GuestSessionCodec:
    """Подпись и проверка значения cookie гостя (HMAC-SHA256)."""

    def __init__(self, secret: bytes, *, ttl: timedelta) -> None:
        """``secret`` — ключ HMAC (≥ ``MIN_SECRET_LENGTH`` байт, иначе ``ValueError``); ``ttl`` — срок
        жизни сессии (``GUEST_SESSION_TTL_HOURS``), больше нуля."""
        raise NotImplementedError

    @property
    def ttl(self) -> timedelta:
        raise NotImplementedError

    def encode(self, claims: GuestSessionClaims) -> str:
        """``v1.<payload>.<sig>`` (см. docstring модуля)."""
        raise NotImplementedError

    def decode(self, value: str | None, *, now: datetime | None = None) -> GuestSessionClaims | None:
        """Claims действующей сессии или ``None``: нет значения, длиннее ``MAX_SESSION_VALUE_LENGTH``,
        не тот формат/версия, неверная подпись, ``iat + ttl <= now`` или ``iat`` в будущем дальше
        допуска часов (60 с). Подпись проверяется до разбора JSON."""
        raise NotImplementedError

    def remaining_seconds(self, claims: GuestSessionClaims, *, now: datetime | None = None) -> int:
        """Сколько целых секунд сессии осталось (``Max-Age`` переподписанной cookie, не меньше 1):
        смена языка не продлевает сессию (``iat`` не меняется)."""
        raise NotImplementedError


def build_guest_session_codec(secret: str | None, *, ttl_hours: int) -> GuestSessionCodec:
    """Кодек приложения: ``secret`` — значение ``GUEST_SESSION_SECRET`` (UTF-8 → bytes).

    ``None`` — ключ ``secrets.token_bytes(32)`` и WARNING ``RANDOM_KEY_WARNING`` (допустимо только в
    ``single`` вне prod; при prod/scaled секрет обязателен — валидатор ``Settings``). Значение секрета в
    лог не пишется."""
    raise NotImplementedError
