"""Кодек гостевой сессии (#80, ADR-9.2): подпись, подмена, версия, TTL, допуск часов, формат payload."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.guest.session import (
    MAX_SESSION_VALUE_LENGTH,
    MIN_SECRET_LENGTH,
    RANDOM_KEY_WARNING,
    GuestSessionClaims,
    GuestSessionCodec,
    build_guest_session_codec,
    epoch_micros,
    issue_claims,
)
from app.models.enums import Lang

SECRET = b"s" * MIN_SECRET_LENGTH
NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)
TTL = timedelta(hours=12)


def _claims(**overrides: object) -> GuestSessionClaims:
    values: dict[str, object] = {
        "vid": uuid.UUID("01929a6e-0000-7000-8000-000000000001"),
        "tid": uuid.UUID("01929a6e-0000-7000-8000-000000000002"),
        "tbl": uuid.UUID("01929a6e-0000-7000-8000-000000000003"),
        "tia": 1_762_776_000_123_456,
        "lang": Lang.RU,
        "iat": int(NOW.timestamp()),
    }
    values.update(overrides)
    return GuestSessionClaims(**values)  # type: ignore[arg-type]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign(payload: str, secret: bytes = SECRET) -> str:
    return _b64(hmac.new(secret, f"v1.{payload}".encode("ascii"), hashlib.sha256).digest())


def _forge(data: object, secret: bytes = SECRET) -> str:
    """Значение cookie с произвольным payload, подписанное верным ключом (проверка разбора JSON)."""
    payload = _b64(json.dumps(data, separators=(",", ":")).encode("utf-8"))
    return f"v1.{payload}.{_sign(payload, secret)}"


@pytest.fixture
def codec() -> GuestSessionCodec:
    return GuestSessionCodec(SECRET, ttl=TTL)


# ---------------------------------------------------------------- epoch_micros / issue_claims


def test_epoch_micros_is_exact_and_zone_independent() -> None:
    value = datetime(2026, 11, 10, 12, 0, 0, 123456, tzinfo=UTC)
    baku = value.astimezone(timezone(timedelta(hours=4)))
    assert epoch_micros(value) == epoch_micros(baku) == 1_794_312_000_123_456


def test_epoch_micros_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="часовым поясом"):
        epoch_micros(datetime(2026, 11, 10, 12, 0, 0))  # noqa: DTZ001 — проверяется отказ


def test_issue_claims_fills_tia_and_iat() -> None:
    issued = datetime(2026, 11, 1, 8, 0, 0, 1, tzinfo=UTC)
    ids = [uuid.uuid4() for _ in range(3)]
    claims = issue_claims(
        tenant_id=ids[0], table_id=ids[1], visit_id=ids[2], token_issued_at=issued, lang=Lang.AZ, now=NOW
    )
    assert claims == GuestSessionClaims(
        vid=ids[2], tid=ids[0], tbl=ids[1], tia=epoch_micros(issued), lang=Lang.AZ, iat=int(NOW.timestamp())
    )


def test_issue_claims_defaults_to_current_time() -> None:
    before = int(datetime.now(UTC).timestamp())
    claims = issue_claims(
        tenant_id=uuid.uuid4(), table_id=uuid.uuid4(), visit_id=uuid.uuid4(), token_issued_at=NOW, lang=Lang.RU
    )
    assert before <= claims.iat <= int(datetime.now(UTC).timestamp())


# ---------------------------------------------------------------- конструктор и фабрика


def test_codec_rejects_short_secret() -> None:
    with pytest.raises(ValueError, match="короче"):
        GuestSessionCodec(b"x" * (MIN_SECRET_LENGTH - 1), ttl=TTL)


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1)])
def test_codec_rejects_non_positive_ttl(ttl: timedelta) -> None:
    with pytest.raises(ValueError, match="больше нуля"):
        GuestSessionCodec(SECRET, ttl=ttl)


def test_build_codec_with_secret_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    secret = "k" * 40
    with caplog.at_level(logging.WARNING, logger="app.guest.session"):
        codec = build_guest_session_codec(secret, ttl_hours=3)
    assert codec.ttl == timedelta(hours=3)
    assert caplog.records == []
    # Тот же секрет — совместимые подписи (несколько процессов api в scaled).
    other = build_guest_session_codec(secret, ttl_hours=3)
    assert other.decode(codec.encode(_claims(iat=int(datetime.now(UTC).timestamp())))) is not None


def test_build_codec_without_secret_uses_random_key_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.guest.session"):
        first = build_guest_session_codec(None, ttl_hours=12)
        second = build_guest_session_codec(None, ttl_hours=12)
    assert [r.getMessage() for r in caplog.records] == [RANDOM_KEY_WARNING, RANDOM_KEY_WARNING]
    value = first.encode(_claims(iat=int(datetime.now(UTC).timestamp())))
    assert first.decode(value) is not None
    assert second.decode(value) is None  # ключи разные: сессии не переживают перезапуск


# ---------------------------------------------------------------- encode / decode


def test_roundtrip(codec: GuestSessionCodec) -> None:
    claims = _claims()
    value = codec.encode(claims)
    assert value.startswith("v1.")
    assert value.count(".") == 2
    assert codec.decode(value, now=NOW) == claims


def test_payload_is_compact_json_without_extra_fields(codec: GuestSessionCodec) -> None:
    claims = _claims()
    _, payload, _ = codec.encode(claims).split(".")
    raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    assert b" " not in raw
    assert "=" not in payload
    assert json.loads(raw) == {
        "vid": str(claims.vid),
        "tid": str(claims.tid),
        "tbl": str(claims.tbl),
        "tia": claims.tia,
        "lang": "ru",
        "iat": claims.iat,
    }


def test_value_fits_max_length(codec: GuestSessionCodec) -> None:
    assert len(codec.encode(_claims())) < MAX_SESSION_VALUE_LENGTH // 3


@pytest.mark.parametrize("value", [None, "", "v1", "v1..", "v1.a.b.c", "abc"])
def test_decode_malformed_values(codec: GuestSessionCodec, value: str | None) -> None:
    assert codec.decode(value, now=NOW) is None


def test_decode_rejects_unknown_version(codec: GuestSessionCodec) -> None:
    _, payload, sig = codec.encode(_claims()).split(".")
    assert codec.decode(f"v2.{payload}.{sig}", now=NOW) is None


def test_decode_rejects_tampered_payload(codec: GuestSessionCodec) -> None:
    """E-14: подмена ``vid`` при прежней подписи — сессии нет."""
    value = codec.encode(_claims())
    _, _, sig = value.split(".")
    other = codec.encode(_claims(vid=uuid.uuid4()))
    _, other_payload, _ = other.split(".")
    assert codec.decode(f"v1.{other_payload}.{sig}", now=NOW) is None


def test_decode_rejects_tampered_signature(codec: GuestSessionCodec) -> None:
    value = codec.encode(_claims())
    flipped = value[:-1] + ("A" if value[-1] != "A" else "B")
    assert codec.decode(flipped, now=NOW) is None


def test_decode_rejects_other_secret(codec: GuestSessionCodec) -> None:
    other = GuestSessionCodec(b"o" * MIN_SECRET_LENGTH, ttl=TTL)
    assert other.decode(codec.encode(_claims()), now=NOW) is None


def test_decode_rejects_too_long_value(codec: GuestSessionCodec) -> None:
    assert codec.decode("v1." + "a" * MAX_SESSION_VALUE_LENGTH + ".b", now=NOW) is None


def test_decode_rejects_non_ascii(codec: GuestSessionCodec) -> None:
    value = codec.encode(_claims())
    assert codec.decode(value + "ж", now=NOW) is None


def test_decode_rejects_bad_base64_with_valid_signature(codec: GuestSessionCodec) -> None:
    payload = "a*b"
    assert codec.decode(f"v1.{payload}.{_sign(payload)}", now=NOW) is None


def test_decode_rejects_bad_json_with_valid_signature(codec: GuestSessionCodec) -> None:
    payload = _b64(b"{not json")
    assert codec.decode(f"v1.{payload}.{_sign(payload)}", now=NOW) is None


def test_decode_rejects_invalid_utf8_with_valid_signature(codec: GuestSessionCodec) -> None:
    payload = _b64(b"\xff\xfe")
    assert codec.decode(f"v1.{payload}.{_sign(payload)}", now=NOW) is None


def _valid_data() -> dict[str, object]:
    claims = _claims()
    return {
        "vid": str(claims.vid),
        "tid": str(claims.tid),
        "tbl": str(claims.tbl),
        "tia": claims.tia,
        "lang": "ru",
        "iat": claims.iat,
    }


def test_forged_valid_data_is_accepted(codec: GuestSessionCodec) -> None:
    """Контроль ``_forge``: корректный payload с верной подписью разбирается."""
    assert codec.decode(_forge(_valid_data()), now=NOW) == _claims()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("vid"),
        lambda d: d.update(extra=1),
        lambda d: d.update(vid="not-a-uuid"),
        lambda d: d.update(tid=123),
        lambda d: d.update(lang="en"),
        lambda d: d.update(tia="1"),
        lambda d: d.update(tia=True),
        lambda d: d.update(iat=1.5),
        lambda d: d.update(iat=False),
    ],
    ids=["missing", "extra", "bad-uuid", "uuid-int", "lang", "tia-str", "tia-bool", "iat-float", "iat-bool"],
)
def test_decode_rejects_wrong_fields(codec: GuestSessionCodec, mutate: object) -> None:
    data = _valid_data()
    mutate(data)  # type: ignore[operator]
    assert codec.decode(_forge(data), now=NOW) is None


@pytest.mark.parametrize("data", [[], "x", 1, None])
def test_decode_rejects_non_object_payload(codec: GuestSessionCodec, data: object) -> None:
    assert codec.decode(_forge(data), now=NOW) is None


# ---------------------------------------------------------------- срок действия


def test_decode_expired_at_ttl_boundary(codec: GuestSessionCodec) -> None:
    value = codec.encode(_claims())
    assert codec.decode(value, now=NOW + TTL - timedelta(seconds=1)) is not None
    assert codec.decode(value, now=NOW + TTL) is None  # iat + ttl <= now


def test_decode_allows_small_clock_skew(codec: GuestSessionCodec) -> None:
    value = codec.encode(_claims(iat=int(NOW.timestamp()) + 60))
    assert codec.decode(value, now=NOW) is not None


def test_decode_rejects_iat_far_in_future(codec: GuestSessionCodec) -> None:
    value = codec.encode(_claims(iat=int(NOW.timestamp()) + 61))
    assert codec.decode(value, now=NOW) is None


def test_decode_uses_current_time_by_default(codec: GuestSessionCodec) -> None:
    fresh = _claims(iat=int(datetime.now(UTC).timestamp()))
    assert codec.decode(codec.encode(fresh)) == fresh
    assert codec.decode(codec.encode(_claims(iat=0))) is None


def test_remaining_seconds(codec: GuestSessionCodec) -> None:
    claims = _claims()
    assert codec.remaining_seconds(claims, now=NOW) == int(TTL.total_seconds())
    assert codec.remaining_seconds(claims, now=NOW + timedelta(hours=11)) == 3600
    assert codec.remaining_seconds(claims, now=NOW + TTL + timedelta(hours=1)) == 1  # не меньше 1


def test_remaining_seconds_defaults_to_now(codec: GuestSessionCodec) -> None:
    claims = _claims(iat=int(datetime.now(UTC).timestamp()))
    assert int(TTL.total_seconds()) - 5 <= codec.remaining_seconds(claims) <= int(TTL.total_seconds())
