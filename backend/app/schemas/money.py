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

from decimal import Decimal
from typing import Annotated, Final

from pydantic import BeforeValidator, PlainSerializer

# Максимум NUMERIC(10,2): 8 знаков до точки, 2 после.
MONEY_MAX: Final[Decimal] = Decimal("99999999.99")
# Строковая форма в JSON API: 1–8 цифр, затем необязательные «.» и 1–2 цифры.
MONEY_PATTERN: Final[str] = r"^\d{1,8}(\.\d{1,2})?$"


def parse_money(value: object) -> Decimal:
    """Привести значение к ``Decimal`` с ровно двумя знаками (``quantize``) или ``ValueError``.

    Текст ошибки — на русском, без самого значения (значение показывает вызывающий, если нужно).
    """
    raise NotImplementedError


def format_money(value: Decimal) -> str:
    """``Decimal`` → строка с двумя знаками после точки (``"8.50"``); ``ValueError`` при > 2 знаках."""
    raise NotImplementedError


# Тип поля Pydantic-схем: на входе — правила ``parse_money``, в JSON — строка ``format_money``.
MoneyStr = Annotated[
    Decimal,
    BeforeValidator(parse_money),
    PlainSerializer(format_money, return_type=str, when_used="json"),
]
