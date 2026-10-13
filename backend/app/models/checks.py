"""Построители текста CHECK-ограничений (ADR-7.2) из перечислений и шаблонов ``app.models.enums``.

Значения подставляются в SQL литералами, поэтому принимаются только «безопасные» строки:
перечисления и шаблоны задаются в коде, а не пользователем; апостроф или NUL — ошибка
программиста, которую лучше поймать при импорте моделей, чем в миграции.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _literal(value: str) -> str:
    if "'" in value or "\x00" in value:
        raise ValueError(f"недопустимый символ в значении CHECK: {value!r}")
    return f"'{value}'"


def _column(name: str) -> str:
    if not _IDENTIFIER.match(name):
        raise ValueError(f"недопустимое имя колонки в CHECK: {name!r}")
    return name


def sql_in(column: str, values: Iterable[str]) -> str:
    """``column IN ('a', 'b')`` — значения перечисления в порядке объявления."""
    items = [_literal(str(value)) for value in values]
    if not items:
        raise ValueError("CHECK IN без значений")
    return f"{_column(column)} IN ({', '.join(items)})"


def sql_not_in(column: str, values: Iterable[str]) -> str:
    """``column NOT IN ('a', 'b')`` — для условий вида «статус не X или поле заполнено»."""
    return sql_in(column, values).replace(" IN (", " NOT IN (", 1)


def sql_text_array(values: Iterable[str]) -> str:
    """``ARRAY['a', 'b']::text[]``."""
    return f"ARRAY[{', '.join(_literal(str(value)) for value in values)}]::text[]"


def sql_match(column: str, pattern: str) -> str:
    """``column ~ 'pattern'`` (регулярное выражение POSIX PostgreSQL)."""
    return f"{_column(column)} ~ {_literal(pattern)}"


def sql_not_match(column: str, pattern: str) -> str:
    """``column !~ 'pattern'``."""
    return f"{_column(column)} !~ {_literal(pattern)}"


def sql_length(column: str, max_length: int, min_length: int | None = None) -> str:
    """``char_length(column) BETWEEN min AND max`` или ``char_length(column) <= max``.

    NULL проходит CHECK, поэтому для nullable-колонок ограничение действует только на заданное значение.
    """
    if min_length is None:
        return f"char_length({_column(column)}) <= {max_length:d}"
    return f"char_length({_column(column)}) BETWEEN {min_length:d} AND {max_length:d}"


def sql_between(column: str, low: int, high: int) -> str:
    """``column BETWEEN low AND high`` для целых."""
    return f"{_column(column)} BETWEEN {low:d} AND {high:d}"
