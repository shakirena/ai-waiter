"""Язык гостя при входе: явный выбор → cookie → ``Accept-Language`` → язык заведения (#9, ADR-9.4, ТЗ FR-2).

Чистые функции без БД и HTTP. В лог ``Accept-Language`` целиком не пишется (Security arch).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from app.models.enums import Lang

# Длиннее — заголовок обрезается до этой длины перед разбором (защита от тяжёлого разбора).
ACCEPT_LANGUAGE_MAX_LENGTH: Final = 512

# Языковой диапазон RFC 4647 (без «*»): подтеги из букв и цифр до 8 символов, первый — только буквы.
_LANGUAGE_RANGE_RE: Final = re.compile(r"[a-z]{1,8}(?:-[a-z0-9]{1,8})*")
# Вес RFC 9110 12.4.2: 0…1, не больше трёх знаков после точки.
_QVALUE_RE: Final = re.compile(r"0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?")
_SUPPORTED: Final = frozenset(Lang)


def _parse_item(item: str) -> tuple[float, str] | None:
    """Элемент ``ru-RU;q=0.8`` → ``(0.8, "ru")``; неверный, ``*`` или ``q=0`` → ``None``."""
    tag, *params = item.split(";")
    tag = tag.strip().lower()
    if not _LANGUAGE_RANGE_RE.fullmatch(tag):
        return None
    weight = 1.0
    for param in params:
        name, sep, value = param.strip().partition("=")
        if name.strip().lower() != "q":
            continue  # параметры кроме q стандарт не определяет — пропускаются
        value = value.strip()
        if not sep or not _QVALUE_RE.fullmatch(value):
            return None
        weight = float(value)
    if weight <= 0:
        return None
    return weight, tag.split("-", 1)[0]


def parse_accept_language(header: str | None) -> list[str]:
    """Основные подтеги в порядке убывания ``q`` (при равном ``q`` — порядок заголовка), без повторов.

    ``"ru-RU,ru;q=0.9,az-Latn-AZ;q=0.8"`` → ``["ru", "az"]``. Подтег — в нижнем регистре; ``q=0``
    пропускается; ``*``, пустые и синтаксически неверные элементы (в том числе ``q`` вне 0…1 или не
    число) пропускаются без исключения. ``None``/пустая строка → ``[]``. Обрабатываются только первые
    ``ACCEPT_LANGUAGE_MAX_LENGTH`` символов."""
    if not header:
        return []
    parsed: list[tuple[float, int, str]] = []
    for index, item in enumerate(header[:ACCEPT_LANGUAGE_MAX_LENGTH].split(",")):
        entry = _parse_item(item)
        if entry is not None:
            parsed.append((-entry[0], index, entry[1]))
    result: list[str] = []
    for _, _, primary in sorted(parsed):
        if primary not in result:
            result.append(primary)
    return result


def resolve_entry_lang(
    *,
    requested: Lang | None,
    session_lang: Lang | None,
    accept_language: str | None,
    languages: Sequence[str],
) -> Lang:
    """Язык устройства при входе (ADR-9.4), ``languages`` — ``tenants.languages`` (непустой):

    1. ``requested`` (тело запроса, выбор из ``localStorage``), если входит в ``languages``;
    2. ``session_lang`` — язык действующей cookie того же стола (``entry.enter_table``), если входит в ``languages``;
    3. первый подтег ``parse_accept_language(accept_language)``, входящий в ``languages`` и в ``Lang``;
    4. ``Lang(languages[0])`` — язык заведения по умолчанию."""
    allowed = {value for value in languages if value in _SUPPORTED}
    for candidate in (requested, session_lang):
        if candidate is not None and candidate.value in allowed:
            return Lang(candidate)
    for primary in parse_accept_language(accept_language):
        if primary in allowed:
            return Lang(primary)
    return Lang(languages[0])
