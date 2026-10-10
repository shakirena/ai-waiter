"""Справочные данные по умолчанию, которые получает каждое новое заведение (не только сид).

FR-16a: справочник аллергенов по умолчанию — 14 аллергенов ЕС (Регламент ЕС 1169/2011,
приложение II). Справочник хранится в ``allergens`` отдельно у каждого заведения (ADR-7.3):
при создании заведения сервис копирует эти коды; названия AZ/RU задаёт сид или админ.
"""

from __future__ import annotations

from typing import Final

EU14_ALLERGEN_CODES: Final[tuple[str, ...]] = (
    "gluten",
    "crustaceans",
    "eggs",
    "fish",
    "peanuts",
    "soybeans",
    "milk",
    "nuts",
    "celery",
    "mustard",
    "sesame",
    "sulphites",
    "lupin",
    "molluscs",
)
