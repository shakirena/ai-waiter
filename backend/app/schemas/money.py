"""Деньги в JSON API (story #61; CLAUDE.md, ADR-7.4, DEC-013): ``Decimal`` в коде, строка ``"12.50"`` в JSON.

Правила разбора (``parse_money``):

- принимается ``str`` (``"8"``, ``"8.5"``, ``"8.50"``), ``Decimal`` и ``int``;
- ``float`` отвергается: двоичная дробь не годится для денег; JSON-число ``8.5`` — ошибка,
  деньги в JSON передаются строкой (ТЗ 4.4);
- не больше двух знаков после точки — ядро не округляет, округление из ``float`` кассы — забота
  коннектора (ТЗ A.2, C-07);
- без знака, экспоненты, пробелов, разделителей тысяч; ``0 <= x <= MONEY_MAX`` (``NUMERIC(10,2)``).

Сериализация (``format_money``) — всегда два знака: ``Decimal("8.5")`` → ``"8.50"``.
"""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Final

from pydantic import BeforeValidator, PlainSerializer

# Максимум NUMERIC(10,2): 8 знаков до точки, 2 после.
MONEY_MAX: Final[Decimal] = Decimal("99999999.99")
# Строковая форма в JSON API: 1–8 цифр, затем необязательные «.» и 1–2 цифры.
MONEY_PATTERN: Final[str] = r"^\d{1,8}(\.\d{1,2})?$"

_MONEY_RE: Final[re.Pattern[str]] = re.compile(MONEY_PATTERN)
# Похоже на число, но с лишними знаками после точки или лишними цифрами до неё.
_TOO_MANY_DECIMALS_RE: Final[re.Pattern[str]] = re.compile(r"^\d+\.\d{3,}$")
_TOO_LARGE_RE: Final[re.Pattern[str]] = re.compile(r"^\d{9,}(\.\d{1,2})?$")
_NEGATIVE_RE: Final[re.Pattern[str]] = re.compile(r"^-\d+(\.\d+)?$")
_CENT: Final[Decimal] = Decimal("0.01")


class MoneyErrorReason(StrEnum):
    """Причина отказа ``parse_money`` — для сопоставления с кодами проблем (``IssueCode``)."""

    INVALID = "invalid"  # не число, экспонента, пробелы, NaN, неподходящий тип
    FLOAT = "float"  # двоичная дробь (JSON-число)
    TOO_MANY_DECIMALS = "too_many_decimals"
    NEGATIVE = "negative"
    TOO_LARGE = "too_large"


class MoneyError(ValueError):
    """Значение не является суммой денег. ``reason`` — машинная причина, текст — на русском."""

    def __init__(self, reason: MoneyErrorReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _invalid() -> MoneyError:
    return MoneyError(MoneyErrorReason.INVALID, 'ожидается сумма строкой, например "8.50"')


def _check_range(value: Decimal) -> Decimal:
    """Конечное ``Decimal`` в пределах ``0…MONEY_MAX`` с ≤ 2 знаками → ровно два знака."""
    if not value.is_finite():
        raise _invalid()
    if value < 0:
        raise MoneyError(MoneyErrorReason.NEGATIVE, "сумма не может быть отрицательной")
    if value > MONEY_MAX:
        raise MoneyError(MoneyErrorReason.TOO_LARGE, f"сумма больше максимальной {MONEY_MAX}")
    result = value.quantize(_CENT)
    if result != value:
        raise MoneyError(MoneyErrorReason.TOO_MANY_DECIMALS, "больше двух знаков после точки")
    # -0 → 0: в JSON не должно появляться "-0.00".
    return result.copy_abs() if result == 0 else result


def _parse_text(value: str) -> Decimal:
    if _MONEY_RE.fullmatch(value):
        return _check_range(Decimal(value))
    if _TOO_MANY_DECIMALS_RE.fullmatch(value):
        raise MoneyError(MoneyErrorReason.TOO_MANY_DECIMALS, "больше двух знаков после точки")
    if _TOO_LARGE_RE.fullmatch(value):
        raise MoneyError(MoneyErrorReason.TOO_LARGE, f"сумма больше максимальной {MONEY_MAX}")
    if _NEGATIVE_RE.fullmatch(value):
        raise MoneyError(MoneyErrorReason.NEGATIVE, "сумма не может быть отрицательной")
    raise _invalid()


def parse_money(value: object) -> Decimal:
    """Привести значение к ``Decimal`` с ровно двумя знаками (``quantize``) или ``ValueError``.

    Текст ошибки — на русском, без самого значения (значение показывает вызывающий, если нужно).
    Ошибка — ``MoneyError`` (подкласс ``ValueError``) с машинной причиной ``reason``.
    """
    # bool — подкласс int: True не должен становиться ценой 1.00.
    if isinstance(value, bool):
        raise _invalid()
    if isinstance(value, float):
        raise MoneyError(
            MoneyErrorReason.FLOAT, 'дробное число не допускается, сумма передаётся строкой, например "8.50"'
        )
    if isinstance(value, str):
        return _parse_text(value)
    if isinstance(value, Decimal):
        return _check_range(value)
    if isinstance(value, int):
        return _check_range(Decimal(value))
    raise _invalid()


def format_money(value: Decimal) -> str:
    """``Decimal`` → строка с двумя знаками после точки (``"8.50"``); ``ValueError`` при > 2 знаках."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("ожидается конечное Decimal")
    result = value.quantize(_CENT)
    if result != value:
        raise ValueError("больше двух знаков после точки")
    if result == 0:
        result = result.copy_abs()
    return f"{result:f}"


# Тип поля Pydantic-схем: на входе — правила ``parse_money``, в JSON — строка ``format_money``.
MoneyStr = Annotated[
    Decimal,
    BeforeValidator(parse_money),
    PlainSerializer(format_money, return_type=str, when_used="json"),
]
