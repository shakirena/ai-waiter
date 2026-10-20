"""Деньги в Pydantic-схемах ``app.schemas.money`` (story #61, DEC-013): без БД."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.money import MONEY_MAX, MoneyError, MoneyErrorReason, MoneyStr, format_money, parse_money


class _Price(BaseModel):
    price: MoneyStr


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8", "8.00"),
        ("8.5", "8.50"),
        ("8.50", "8.50"),
        ("0", "0.00"),
        ("007.10", "7.10"),
        ("99999999.99", "99999999.99"),
        (Decimal("8.5"), "8.50"),
        (Decimal("8.500"), "8.50"),  # лишние нули — то же значение, округления нет
        (Decimal("1E+2"), "100.00"),
        (Decimal("-0"), "0.00"),
        (12, "12.00"),
        (0, "0.00"),
    ],
)
def test_parse_money_accepts(raw: object, expected: str) -> None:
    result = parse_money(raw)
    assert isinstance(result, Decimal)
    assert str(result) == expected
    assert result.as_tuple().exponent == -2


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (8.5, MoneyErrorReason.FLOAT),
        (8.0, MoneyErrorReason.FLOAT),
        (True, MoneyErrorReason.INVALID),
        (None, MoneyErrorReason.INVALID),
        ([1], MoneyErrorReason.INVALID),
        ("", MoneyErrorReason.INVALID),
        ("abc", MoneyErrorReason.INVALID),
        # Только ASCII-цифры: полноширинные «１２.00», арабско-индийские и деванагари — ошибка.
        (chr(0xFF11) + chr(0xFF12) + ".00", MoneyErrorReason.INVALID),
        (chr(0x0668), MoneyErrorReason.INVALID),
        ("1" + chr(0x0966) + ".50", MoneyErrorReason.INVALID),
        ("8." + chr(0xFF15) + chr(0xFF10), MoneyErrorReason.INVALID),
        ("-" + chr(0xFF11), MoneyErrorReason.INVALID),
        (chr(0xFF11) * 9, MoneyErrorReason.INVALID),
        (" 8.50", MoneyErrorReason.INVALID),
        ("8.50 ", MoneyErrorReason.INVALID),
        ("8,50", MoneyErrorReason.INVALID),
        ("1 000", MoneyErrorReason.INVALID),
        ("+8", MoneyErrorReason.INVALID),
        ("8.", MoneyErrorReason.INVALID),
        (".5", MoneyErrorReason.INVALID),
        ("1e3", MoneyErrorReason.INVALID),
        ("NaN", MoneyErrorReason.INVALID),
        ("Infinity", MoneyErrorReason.INVALID),
        ("8.505", MoneyErrorReason.TOO_MANY_DECIMALS),
        ("-1", MoneyErrorReason.NEGATIVE),
        ("-1.50", MoneyErrorReason.NEGATIVE),
        ("100000000", MoneyErrorReason.TOO_LARGE),
        ("123456789.00", MoneyErrorReason.TOO_LARGE),
        (Decimal("8.505"), MoneyErrorReason.TOO_MANY_DECIMALS),
        (Decimal("-0.01"), MoneyErrorReason.NEGATIVE),
        (Decimal("NaN"), MoneyErrorReason.INVALID),
        (Decimal("Infinity"), MoneyErrorReason.INVALID),
        (Decimal("1E+100"), MoneyErrorReason.TOO_LARGE),
        (MONEY_MAX + Decimal("0.01"), MoneyErrorReason.TOO_LARGE),
        (-5, MoneyErrorReason.NEGATIVE),
        (100_000_000, MoneyErrorReason.TOO_LARGE),
    ],
)
def test_parse_money_rejects(raw: object, reason: MoneyErrorReason) -> None:
    with pytest.raises(MoneyError) as info:
        parse_money(raw)
    assert info.value.reason is reason
    assert isinstance(info.value, ValueError)
    message = str(info.value)
    assert message
    assert any("а" <= ch <= "я" for ch in message.lower()), "текст ошибки — на русском"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("8.5"), "8.50"),
        (Decimal("8"), "8.00"),
        (Decimal("8.500"), "8.50"),
        (Decimal("-0.00"), "0.00"),
        (Decimal("1E+2"), "100.00"),
        (MONEY_MAX, "99999999.99"),
    ],
)
def test_format_money(value: Decimal, expected: str) -> None:
    assert format_money(value) == expected


@pytest.mark.parametrize("value", [Decimal("8.505"), Decimal("NaN"), Decimal("Infinity"), 8.5, "8.50"])
def test_format_money_rejects(value: object) -> None:
    with pytest.raises(ValueError, match=r"Decimal|знаков"):
        format_money(value)  # type: ignore[arg-type]


def test_money_str_field_python_and_json() -> None:
    model = _Price.model_validate({"price": "8.5"})
    assert model.price == Decimal("8.50")
    assert isinstance(model.price, Decimal)
    # В Python — Decimal, в JSON — строка с двумя знаками.
    assert model.model_dump() == {"price": Decimal("8.50")}
    assert model.model_dump(mode="json") == {"price": "8.50"}
    assert model.model_dump_json() == '{"price":"8.50"}'


def test_money_str_field_rejects_json_number() -> None:
    """JSON-число (float) — ошибка: деньги в JSON передаются строкой (ТЗ 4.4)."""
    with pytest.raises(ValidationError) as info:
        _Price.model_validate_json('{"price": 8.5}')
    (error,) = info.value.errors()
    assert error["type"] == "value_error"
    assert isinstance(error["ctx"]["error"], MoneyError)
    assert error["ctx"]["error"].reason is MoneyErrorReason.FLOAT


def test_money_str_field_accepts_json_string() -> None:
    assert _Price.model_validate_json('{"price": "12.5"}').price == Decimal("12.50")
