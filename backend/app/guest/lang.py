"""Язык гостя при входе: явный выбор → cookie → ``Accept-Language`` → язык заведения (#9, ADR-9.4, ТЗ FR-2).

Чистые функции без БД и HTTP. В лог ``Accept-Language`` целиком не пишется (Security arch).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from app.models.enums import Lang

# Длиннее — заголовок обрезается до этой длины перед разбором (защита от тяжёлого разбора).
ACCEPT_LANGUAGE_MAX_LENGTH: Final = 512


def parse_accept_language(header: str | None) -> list[str]:
    """Основные подтеги в порядке убывания ``q`` (при равном ``q`` — порядок заголовка), без повторов.

    ``"ru-RU,ru;q=0.9,az-Latn-AZ;q=0.8"`` → ``["ru", "az"]``. Подтег — в нижнем регистре; ``q=0``
    пропускается; ``*``, пустые и синтаксически неверные элементы (в том числе ``q`` вне 0…1 или не
    число) пропускаются без исключения. ``None``/пустая строка → ``[]``. Обрабатываются только первые
    ``ACCEPT_LANGUAGE_MAX_LENGTH`` символов."""
    raise NotImplementedError


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
    raise NotImplementedError
