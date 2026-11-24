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

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from app.models.enums import Lang

logger = logging.getLogger(__name__)

SESSION_FORMAT_VERSION: Final = "v1"
# Значение длиннее — не разбирается (настоящее значение ~250 символов).
MAX_SESSION_VALUE_LENGTH: Final = 1024
MIN_SECRET_LENGTH: Final = 32
# Допуск расхождения часов: iat в будущем не дальше этого (ADR-9.2).
CLOCK_SKEW: Final = timedelta(seconds=60)
RANDOM_KEY_BYTES: Final = 32

RANDOM_KEY_WARNING: Final = (
    "GUEST_SESSION_SECRET не задан: ключ подписи гостевых сессий случайный на процесс, "
    "после перезапуска гости входят заново по QR-коду"
)

EPOCH_UTC: Final = datetime(1970, 1, 1, tzinfo=UTC)
_SEPARATOR: Final = "."
_CLAIM_FIELDS: Final = frozenset({"vid", "tid", "tbl", "tia", "lang", "iat"})


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
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ожидается время с часовым поясом (timestamptz)")
    return (value - EPOCH_UTC) // timedelta(microseconds=1)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _epoch_seconds(value: datetime) -> int:
    return (value - EPOCH_UTC) // timedelta(seconds=1)


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
    return GuestSessionClaims(
        vid=visit_id,
        tid=tenant_id,
        tbl=table_id,
        tia=epoch_micros(token_issued_at),
        lang=lang,
        iat=_epoch_seconds(now or _utc_now()),
    )


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    """base64url без ``=``; посторонние символы — ``binascii.Error``."""
    padded = text + "=" * (-len(text) % 4)
    return base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _claims_from_json(data: Any) -> GuestSessionClaims | None:
    """Строгий разбор payload: ровно поля ``_CLAIM_FIELDS`` нужных типов, иначе ``None``."""
    if not isinstance(data, dict) or set(data) != _CLAIM_FIELDS:
        return None
    if not all(isinstance(data[key], str) for key in ("vid", "tid", "tbl", "lang")):
        return None
    if not (_is_int(data["tia"]) and _is_int(data["iat"])):
        return None
    try:
        return GuestSessionClaims(
            vid=uuid.UUID(data["vid"]),
            tid=uuid.UUID(data["tid"]),
            tbl=uuid.UUID(data["tbl"]),
            tia=data["tia"],
            lang=Lang(data["lang"]),
            iat=data["iat"],
        )
    except ValueError:
        return None


class GuestSessionCodec:
    """Подпись и проверка значения cookie гостя (HMAC-SHA256)."""

    def __init__(self, secret: bytes, *, ttl: timedelta) -> None:
        """``secret`` — ключ HMAC (≥ ``MIN_SECRET_LENGTH`` байт, иначе ``ValueError``); ``ttl`` — срок
        жизни сессии (``GUEST_SESSION_TTL_HOURS``), больше нуля."""
        if len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"ключ подписи гостевой сессии короче {MIN_SECRET_LENGTH} байт")
        if ttl <= timedelta(0):
            raise ValueError("срок жизни гостевой сессии должен быть больше нуля")
        self._secret = secret
        self._ttl = ttl
        self._ttl_seconds = ttl // timedelta(seconds=1)

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def _sign(self, payload: str) -> str:
        message = f"{SESSION_FORMAT_VERSION}{_SEPARATOR}{payload}".encode("ascii")
        return _b64encode(hmac.new(self._secret, message, hashlib.sha256).digest())

    def encode(self, claims: GuestSessionClaims) -> str:
        """``v1.<payload>.<sig>`` (см. docstring модуля)."""
        data = {
            "vid": str(claims.vid),
            "tid": str(claims.tid),
            "tbl": str(claims.tbl),
            "tia": claims.tia,
            "lang": claims.lang.value,
            "iat": claims.iat,
        }
        payload = _b64encode(json.dumps(data, separators=(",", ":")).encode("utf-8"))
        return _SEPARATOR.join((SESSION_FORMAT_VERSION, payload, self._sign(payload)))

    def decode(self, value: str | None, *, now: datetime | None = None) -> GuestSessionClaims | None:
        """Claims действующей сессии или ``None``: нет значения, длиннее ``MAX_SESSION_VALUE_LENGTH``,
        не тот формат/версия, неверная подпись, ``iat + ttl <= now`` или ``iat`` в будущем дальше
        допуска часов (60 с). Подпись проверяется до разбора JSON."""
        if not value or not isinstance(value, str) or len(value) > MAX_SESSION_VALUE_LENGTH:
            return None
        if not value.isascii():
            return None
        parts = value.split(_SEPARATOR)
        if len(parts) != 3 or parts[0] != SESSION_FORMAT_VERSION:
            return None
        _, payload, signature = parts
        if not payload or not signature:
            return None
        if not hmac.compare_digest(self._sign(payload).encode("ascii"), signature.encode("ascii")):
            return None
        try:
            data = json.loads(_b64decode(payload))
        except (binascii.Error, ValueError):  # битый base64, UTF-8 или JSON
            return None
        claims = _claims_from_json(data)
        if claims is None:
            return None
        now_seconds = _epoch_seconds(now or _utc_now())
        if claims.iat > now_seconds + CLOCK_SKEW // timedelta(seconds=1):
            return None
        if claims.iat + self._ttl_seconds <= now_seconds:
            return None
        return claims

    def remaining_seconds(self, claims: GuestSessionClaims, *, now: datetime | None = None) -> int:
        """Сколько целых секунд сессии осталось (``Max-Age`` переподписанной cookie, не меньше 1):
        смена языка не продлевает сессию (``iat`` не меняется)."""
        now_seconds = _epoch_seconds(now or _utc_now())
        return max(1, claims.iat + self._ttl_seconds - now_seconds)


def build_guest_session_codec(secret: str | None, *, ttl_hours: int) -> GuestSessionCodec:
    """Кодек приложения: ``secret`` — значение ``GUEST_SESSION_SECRET`` (UTF-8 → bytes).

    ``None`` — ключ ``secrets.token_bytes(32)`` и WARNING ``RANDOM_KEY_WARNING`` (допустимо только в
    ``single`` вне prod; при prod/scaled секрет обязателен — валидатор ``Settings``). Значение секрета в
    лог не пишется."""
    ttl = timedelta(hours=ttl_hours)
    if secret is None:
        logger.warning(RANDOM_KEY_WARNING)
        return GuestSessionCodec(secrets.token_bytes(RANDOM_KEY_BYTES), ttl=ttl)
    return GuestSessionCodec(secret.encode("utf-8"), ttl=ttl)
