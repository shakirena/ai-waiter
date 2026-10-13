"""Справочные данные по умолчанию, которые получает каждое новое заведение (не только сид).

FR-16a: справочник аллергенов по умолчанию — 14 аллергенов ЕС (Регламент ЕС 1169/2011,
приложение II). Справочник хранится в ``allergens`` отдельно у каждого заведения (ADR-7.3):
при создании заведения (админка, сид) строки строит ``default_allergen_rows`` — миграция
справочник не заполняет. Названия AZ/RU — значения по умолчанию, админ может их менять.
"""

from __future__ import annotations

import uuid
from typing import Final, NamedTuple, TypedDict


class AllergenDefaults(NamedTuple):
    code: str
    name_az: str
    name_ru: str


EU14_ALLERGENS: Final[tuple[AllergenDefaults, ...]] = (
    AllergenDefaults("gluten", "Qlüten", "Глютен"),
    AllergenDefaults("crustaceans", "Xərçəngkimilər", "Ракообразные"),
    AllergenDefaults("eggs", "Yumurta", "Яйца"),
    AllergenDefaults("fish", "Balıq", "Рыба"),
    AllergenDefaults("peanuts", "Yerfındığı", "Арахис"),
    AllergenDefaults("soybeans", "Soya", "Соя"),
    AllergenDefaults("milk", "Süd və laktoza", "Молоко и лактоза"),
    AllergenDefaults("nuts", "Qoz-fındıq", "Орехи"),
    AllergenDefaults("celery", "Kərəviz", "Сельдерей"),
    AllergenDefaults("mustard", "Xardal", "Горчица"),
    AllergenDefaults("sesame", "Küncüt", "Кунжут"),
    AllergenDefaults("sulphites", "Sulfitlər", "Сульфиты"),
    AllergenDefaults("lupin", "Lüpin", "Люпин"),
    AllergenDefaults("molluscs", "Molyusklar", "Моллюски"),
)

EU14_ALLERGEN_CODES: Final[tuple[str, ...]] = tuple(allergen.code for allergen in EU14_ALLERGENS)

# Шаг sort_order: между позициями справочника остаётся место для аллергенов заведения.
ALLERGEN_SORT_STEP: Final[int] = 10


class AllergenRow(TypedDict):
    """Строка ``allergens`` без ``id`` (его задаёт default модели или сервер)."""

    tenant_id: uuid.UUID
    code: str
    name_az: str
    name_ru: str
    sort_order: int


def default_allergen_rows(tenant_id: uuid.UUID) -> list[AllergenRow]:
    """Справочник 14 аллергенов ЕС для заведения: ``Allergen(**row)`` или ``insert(Allergen).values(rows)``.

    Чистая функция: каждый вызов возвращает новый список, к БД не обращается.
    """
    return [
        AllergenRow(
            tenant_id=tenant_id,
            code=allergen.code,
            name_az=allergen.name_az,
            name_ru=allergen.name_ru,
            sort_order=(position + 1) * ALLERGEN_SORT_STEP,
        )
        for position, allergen in enumerate(EU14_ALLERGENS)
    ]
