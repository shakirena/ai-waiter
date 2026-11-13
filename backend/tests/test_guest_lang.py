"""Язык гостя (#82, ADR-9.4, spec FR-7, E-2, E-11): разбор Accept-Language и порядок выбора."""

from __future__ import annotations

import pytest

from app.guest.lang import ACCEPT_LANGUAGE_MAX_LENGTH, parse_accept_language, resolve_entry_lang
from app.models.enums import Lang


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, []),
        ("", []),
        ("ru-RU,ru;q=0.9,en;q=0.8", ["ru", "en"]),
        ("ru-RU,ru;q=0.9,az-Latn-AZ;q=0.8", ["ru", "az"]),
        ("az-AZ", ["az"]),
        ("AZ-latn-az", ["az"]),
        ("en;q=0.5, az;q=0.9, ru;q=0.7", ["az", "ru", "en"]),
        ("en, ru", ["en", "ru"]),  # равный q — порядок заголовка
        ("ru;q=0.1, ru-RU", ["ru"]),  # без повторов, по наибольшему q
        ("ru;q=0, az", ["az"]),  # q=0 — «неприемлемо»
        ("ru;q=0.000", []),
        ("*", []),
        ("*, ru;q=0.5", ["ru"]),
        ("ru;q=1.0", ["ru"]),
        ("ru;q=1.001, az", ["az"]),  # q > 1
        ("ru;q=abc, az", ["az"]),
        ("ru;q=, az", ["az"]),
        ("ru;q, az", ["az"]),
        ("ru;q=0.12345, az", ["az"]),  # больше трёх знаков
        ("ru;q=-1, az", ["az"]),
        ("ru;level=1, az;q=0.5", ["ru", "az"]),  # прочие параметры пропускаются
        ("ru ; Q=0.4 , az;q=0.5", ["az", "ru"]),
        (",,, ;q=1, ru", ["ru"]),
        ("1ru, ru_RU, r!u, az", ["az"]),
        ("toolongtag-RU, ru", ["ru"]),
        ("\x00\xff;;;,ru", ["ru"]),
    ],
)
def test_parse_accept_language(header: str | None, expected: list[str]) -> None:
    assert parse_accept_language(header) == expected


def test_parse_truncates_long_header() -> None:
    padding = "en;q=0.1," * (ACCEPT_LANGUAGE_MAX_LENGTH // 9 + 1)
    assert len(padding) > ACCEPT_LANGUAGE_MAX_LENGTH
    assert parse_accept_language(padding + "ru") == ["en"]  # ru за пределом 512 символов
    assert parse_accept_language("ru," + "x" * 10_000) == ["ru"]


BOTH = ["az", "ru"]


@pytest.mark.parametrize(
    ("requested", "session_lang", "header", "languages", "expected"),
    [
        # AC-8: язык из браузера
        (None, None, "ru-RU,ru;q=0.9,en;q=0.8", BOTH, Lang.RU),
        (None, None, "az-Latn-AZ", ["ru", "az"], Lang.AZ),
        # E-11: язык заведения по умолчанию
        (None, None, None, BOTH, Lang.AZ),
        (None, None, "en-US,tr;q=0.8", ["ru", "az"], Lang.RU),
        (None, None, "*", BOTH, Lang.AZ),
        (None, None, "\x00garbage", BOTH, Lang.AZ),
        (None, None, "az", ["ru"], Lang.RU),  # az не поддерживается заведением
        # шаг 1: явный выбор устройства важнее cookie и браузера
        (Lang.RU, Lang.AZ, "az", BOTH, Lang.RU),
        (Lang.AZ, None, None, ["ru"], Lang.RU),  # выбор вне языков заведения пропускается
        # шаг 2 (E-2): язык прежней cookie того же стола важнее браузера
        (None, Lang.RU, "az", BOTH, Lang.RU),
        (None, Lang.AZ, "ru", ["ru"], Lang.RU),  # язык cookie больше не поддерживается
        # язык браузера, которого нет в Lang, при необычном списке не выбирается
        (None, None, "en", ["ru", "en"], Lang.RU),
    ],
)
def test_resolve_entry_lang(
    requested: Lang | None, session_lang: Lang | None, header: str | None, languages: list[str], expected: Lang
) -> None:
    result = resolve_entry_lang(
        requested=requested, session_lang=session_lang, accept_language=header, languages=languages
    )
    assert result is expected
