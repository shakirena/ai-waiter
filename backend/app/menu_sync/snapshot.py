"""Снимок меню — тело ``PUT /integration/v1/menu`` (ТЗ 4.4) и результат разбора файла (ADR-8.1, ADR-8.2).

Пример (JSON)::

    {
      "categories": [{"external_id": "19", "name": "Isti yemekler", "sort_key": "19"}],
      "items": [{
        "external_id": "157", "category_external_id": "19", "name": "Dolma",
        "prices": {"default": "8.00", "vip": "10.00"}, "currency": "AZN",
        "station": "Metbex", "sort_key": "17003", "is_available": true
      }]
    }

Story #61. Модель проверяет форму элементов: длины строк, деньги (``MoneyStr``), тарифы,
обязательный ``default``, лимиты размера. ``check_snapshot`` — дубли ``external_id``, ссылки позиций
на категории снимка, валюту заведения. Сравнение с текущим меню — ``plan`` (#62); хеш — #63.

Строки обрезаются по краям (``str_strip_whitespace``); управляющие символы запрещены.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.menu_sync.report import SyncIssue
from app.models.enums import CURRENCY_PATTERN
from app.schemas.money import MoneyStr

# Длины (в БД у pos_name/station/sort_key CHECK нет — ограничивает синхронизация).
EXTERNAL_ID_MAX: Final[int] = 64  # = CHECK categories/menu_items.external_id
NAME_MAX: Final[int] = 200
STATION_MAX: Final[int] = 100
SORT_KEY_MAX: Final[int] = 64
# Лимиты снимка: защита памяти и транзакции; меню пилота — сотни позиций.
MAX_CATEGORIES: Final[int] = 500
MAX_ITEMS: Final[int] = 5000
MAX_TIERS_PER_ITEM: Final[int] = 10
# Строка без управляющих символов (U+0000–U+001F, U+007F).
NO_CONTROL_CHARS_PATTERN: Final[str] = r"^[^\x00-\x1f\x7f]*$"


class _SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SnapshotCategory(_SnapshotModel):
    """Категория кассы. ``name`` → ``categories.pos_name`` (админом не редактируется, FR-16)."""

    external_id: str = Field(min_length=1, max_length=EXTERNAL_ID_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    name: str = Field(min_length=1, max_length=NAME_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    sort_key: str = Field(default="", max_length=SORT_KEY_MAX, pattern=NO_CONTROL_CHARS_PATTERN)


class SnapshotItem(_SnapshotModel):
    """Позиция кассы.

    - ``prices`` — тариф → цена; ``default`` обязателен; ключи — ``PRICE_TIER_PATTERN``;
      тарифа нет в снимке — его строка в ``menu_item_prices`` удаляется (ADR-8.3);
    - ``currency`` — ``None``: валюта заведения; иначе обязана совпасть с ней (ADR-7.4, ADR-8.3);
    - ``is_available`` — ``None``: наличие не меняется (у новой позиции — ``true``), ADR-8.3.
    """

    external_id: str = Field(min_length=1, max_length=EXTERNAL_ID_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    category_external_id: str = Field(min_length=1, max_length=EXTERNAL_ID_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    name: str = Field(min_length=1, max_length=NAME_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    prices: dict[str, MoneyStr] = Field(min_length=1, max_length=MAX_TIERS_PER_ITEM)
    currency: str | None = Field(default=None, pattern=CURRENCY_PATTERN)
    station: str | None = Field(default=None, max_length=STATION_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    sort_key: str = Field(default="", max_length=SORT_KEY_MAX, pattern=NO_CONTROL_CHARS_PATTERN)
    is_available: bool | None = None

    @model_validator(mode="after")
    def _check_tiers(self) -> Self:
        """Ключи ``prices`` соответствуют ``PRICE_TIER_PATTERN``, ``default`` присутствует.

        Пустая ``station`` (``""``) приводится к ``None``.
        """
        raise NotImplementedError


class MenuSnapshot(_SnapshotModel):
    """Полный снимок меню: всё, чего в нём нет, скрывается (INT-2).

    Модель проверяет только форму каждого элемента. Межэлементные проверки (дубли, ссылки на
    категории, валюта заведения) — в ``check_snapshot``: так ошибки разных позиций собираются все
    сразу, а не обрываются на первой (AC #61).
    """

    categories: list[SnapshotCategory] = Field(max_length=MAX_CATEGORIES)
    items: list[SnapshotItem] = Field(max_length=MAX_ITEMS)


def issues_from_validation_error(exc: ValidationError, data: Mapping[str, Any]) -> list[SyncIssue]:
    """Ошибки Pydantic → ``SyncIssue``: ``external_id`` элемента берётся из ``data`` по индексу в
    ``loc`` (``("items", 2, "prices", "default")``), поле — остаток ``loc``, сообщение — на русском."""
    raise NotImplementedError


def check_snapshot(snapshot: MenuSnapshot, tenant_currency: str) -> list[SyncIssue]:
    """Межэлементные проверки снимка (#61), все ошибки сразу:

    - пустой список позиций — ``empty_snapshot``;
    - повтор ``external_id`` среди категорий и (отдельно) среди позиций — ``duplicate_external_id``;
    - ``category_external_id`` вне категорий снимка — ``unknown_category``;
    - ``currency`` задана и ≠ ``tenant_currency`` — ``currency_mismatch`` (ADR-7.4, ADR-8.3);
    - цена 0 — предупреждение ``zero_price``.
    """
    raise NotImplementedError


def parse_snapshot(data: Mapping[str, Any], tenant_currency: str) -> tuple[MenuSnapshot | None, list[SyncIssue]]:
    """Сырые данные (тело ``PUT /menu`` в #16) → снимок или ``None`` и проблемы.

    ``model_validate`` → при ``ValidationError`` — ``issues_from_validation_error``; иначе
    ``check_snapshot``. Снимок возвращается только без ошибок (предупреждения допустимы).
    """
    raise NotImplementedError


def resolve_currency(snapshot: MenuSnapshot, tenant_currency: str) -> MenuSnapshot:
    """Копия снимка, где ``currency is None`` заменено валютой заведения (до расчёта хеша и плана)."""
    raise NotImplementedError


def snapshot_hash(snapshot: MenuSnapshot) -> str:
    """SHA-256 (hex, 64 символа) канонической формы снимка (INT-1, ADR-8.5). Реализуется в #63.

    Каноническая форма: категории и позиции отсортированы по ``external_id``, тарифы — по имени,
    деньги — строкой с двумя знаками, ``None`` — явным ``null``; ``json.dumps(sort_keys=True,
    separators=(",", ":"), ensure_ascii=False)`` в UTF-8. Порядок строк в файле и формат файла
    (CSV/XLSX) на хеш не влияют. Вызывается после ``resolve_currency``.
    """
    raise NotImplementedError
