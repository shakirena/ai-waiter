"""Чистое сравнение текущего меню заведения со снимком (ADR-8.3, ADR-8.4). Без БД и ввода-вывода.

``service`` загружает ``CurrentMenu`` одним-двумя SELECT, вызывает ``plan_menu_sync`` и
выполняет план пакетными INSERT … ON CONFLICT / UPDATE / DELETE. Пробный прогон
(``--dry-run``) — тот же план без записи, поэтому его счётчики совпадают с реальным применением.

Правила (ADR-8.3):

- категории и позиции сопоставляются по ``external_id`` в границах заведения;
- нет в БД → создать; есть → обновить изменившиеся поля (``pos_name``, ``sort_key``,
  ``category_id``, ``station``, ``currency``); была скрыта → ``is_hidden = false`` («возвращена»);
- есть в БД, нет в снимке, не скрыта → ``is_hidden = true``; уже скрытая не считается;
- цены: тарифы снимка — upsert, тарифы позиции, которых нет в снимке, — удалить; у скрываемых
  позиций цены не трогаются;
- ``is_available``: ``None`` в снимке — не менять (новая позиция — ``true``);
- ``menu_item_meta`` и ``menu_item_allergens`` не трогаются никогда (FR-16);
- ``synced_at`` ставится всем строкам, которые есть в применённом снимке.

Story #62. Ошибка уровня плана (→ снимок отклоняется целиком, ADR-8.4) одна: массовое скрытие
(``MASS_HIDE_MIN_ITEMS`` и ``MASS_HIDE_RATIO`` от видимых позиций) без ``allow_mass_hide``.
Валюта, дубли и ссылки проверены раньше — ``snapshot.check_snapshot`` (#61).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from app.menu_sync.report import EntityCounts, PriceCounts, SyncIssue
from app.menu_sync.snapshot import MenuSnapshot

# Отказ, если снимок скрывает не меньше MASS_HIDE_MIN_ITEMS позиций и не меньше MASS_HIDE_RATIO
# от видимых сейчас: защита от «не того файла» или пустого листа. Обход — allow_mass_hide.
MASS_HIDE_MIN_ITEMS: Final[int] = 10
MASS_HIDE_RATIO: Final[Decimal] = Decimal("0.30")


@dataclass(frozen=True, slots=True)
class CurrentCategory:
    id: uuid.UUID
    external_id: str
    pos_name: str
    sort_key: str
    is_hidden: bool


@dataclass(frozen=True, slots=True)
class CurrentItem:
    id: uuid.UUID
    external_id: str
    category_id: uuid.UUID
    pos_name: str
    currency: str
    station: str | None
    sort_key: str
    is_available: bool
    is_hidden: bool
    prices: dict[str, Decimal]  # тариф → цена


@dataclass(frozen=True, slots=True)
class CurrentMenu:
    """Синхронизируемая часть меню заведения (без ``menu_item_meta``)."""

    tenant_id: uuid.UUID
    tenant_currency: str
    categories: dict[str, CurrentCategory]  # по external_id
    items: dict[str, CurrentItem]  # по external_id


@dataclass(frozen=True, slots=True)
class CategoryWrite:
    """Категория для upsert по ``(tenant_id, external_id)``; ``id`` новой — из ``new_id()``."""

    id: uuid.UUID
    external_id: str
    pos_name: str
    sort_key: str


@dataclass(frozen=True, slots=True)
class ItemWrite:
    """Позиция для upsert; ``is_available=None`` — колонку не менять (у новой — ``true``)."""

    id: uuid.UUID
    external_id: str
    category_id: uuid.UUID
    pos_name: str
    currency: str
    station: str | None
    sort_key: str
    is_available: bool | None
    prices: dict[str, Decimal]


@dataclass(slots=True)
class MenuSyncPlan:
    """Что записать. Пустые списки при ошибках: план с ``issues``-ошибками не применяется."""

    category_writes: list[CategoryWrite] = field(default_factory=list)  # новые, изменённые, возвращённые
    item_writes: list[ItemWrite] = field(default_factory=list)
    hide_category_ids: list[uuid.UUID] = field(default_factory=list)
    hide_item_ids: list[uuid.UUID] = field(default_factory=list)
    delete_prices: list[tuple[uuid.UUID, str]] = field(default_factory=list)  # (menu_item_id, price_tier)
    present_category_ids: list[uuid.UUID] = field(default_factory=list)  # для synced_at
    present_item_ids: list[uuid.UUID] = field(default_factory=list)
    categories: EntityCounts = field(default_factory=EntityCounts)
    items: EntityCounts = field(default_factory=EntityCounts)
    prices: PriceCounts = field(default_factory=PriceCounts)
    availability_changed: int = 0
    issues: list[SyncIssue] = field(default_factory=list)


def plan_menu_sync(current: CurrentMenu, snapshot: MenuSnapshot, *, allow_mass_hide: bool = False) -> MenuSyncPlan:
    """Построить план применения снимка к текущему меню (правила — в docstring модуля).

    Снимок уже прошёл ``resolve_currency``. Детерминирован при фиксированном ``new_id``
    (тесты подменяют генератор).
    """
    raise NotImplementedError
