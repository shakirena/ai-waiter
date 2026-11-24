"""QR-токен стола (#79, ADR-9.5, spec NFR-1, E-4): генерация и проверка формата без БД."""

from __future__ import annotations

import base64

import pytest

from app.guest import tokens
from app.guest.tokens import QR_TOKEN_BYTES, QR_TOKEN_RE, generate_qr_token, is_valid_token_format
from app.seed.data import dev_token


def test_generated_token_is_32_base64url_chars_with_192_bits() -> None:
    token = generate_qr_token()
    assert len(token) == 32
    assert QR_TOKEN_RE.fullmatch(token)
    assert is_valid_token_format(token)
    assert len(base64.urlsafe_b64decode(token)) == QR_TOKEN_BYTES == 24  # 192 бита ≥ 128


def test_generated_tokens_are_unique() -> None:
    assert len({generate_qr_token() for _ in range(1000)}) == 1000


def test_generator_uses_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """NFR-1: токен — из ``secrets.token_urlsafe``, а не ``random``/UUID."""
    calls: list[int] = []

    def fake_token_urlsafe(nbytes: int) -> str:
        calls.append(nbytes)
        return "A" * 32

    monkeypatch.setattr(tokens.secrets, "token_urlsafe", fake_token_urlsafe)
    assert generate_qr_token() == "A" * 32
    assert calls == [QR_TOKEN_BYTES]


@pytest.mark.parametrize(
    "token",
    ["a" * 22, "Z" * 64, "abc-DEF_123" * 3, dev_token(1)],
)
def test_valid_formats(token: str) -> None:
    assert is_valid_token_format(token)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "a" * 21,
        "a" * 65,
        "a" * 30 + "\n",  # $ в re.match пропустил бы завершающий перевод строки
        " " + "a" * 30,
        "a" * 15 + " " + "a" * 15,
        "a" * 30 + "=",
        "a" * 30 + "+/",
        "а" * 30,  # кириллица
        "a" * 30 + "%",
    ],
    ids=["empty", "short", "long", "newline", "lead-space", "inner-space", "padding", "std-b64", "cyrillic", "pct"],
)
def test_invalid_formats(token: str) -> None:
    assert not is_valid_token_format(token)


def test_non_string_is_invalid() -> None:
    assert not is_valid_token_format(None)  # type: ignore[arg-type]
