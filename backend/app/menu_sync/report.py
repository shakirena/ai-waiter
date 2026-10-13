"""Отчёт синхронизации меню (story #61, счётчики — #62; ADR-8.4).

Проблемы с местом (строка, колонка) и счётчики изменений.

Один формат для CLI (текст и ``--json``), журнала ``menu_sync_runs`` (``counts``/``issues`` jsonb),
будущего ответа админки и ``PUT /menu`` (#16). Сообщения — на русском, коды — стабильные
идентификаторы для тестов и фронтенда.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from app.models.enums import MenuSyncStatus

# Сколько проблем хранить в журнале и показывать; остальные — числом «и ещё N».
MAX_REPORTED_ISSUES: Final[int] = 100
# Значение ячейки в сообщении обрезается до этой длины.
MAX_ISSUE_VALUE_CHARS: Final[int] = 60


class Severity(StrEnum):
    ERROR = "error"  # снимок не применяется
    WARNING = "warning"  # применяется, но стоит проверить


class IssueCode(StrEnum):
    """Коды проблем. Файл: строка/колонка; снимок: ``external_id``."""

    # уровень файла
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_FORMAT = "unsupported_format"  # не .csv/.xlsx, .xls, .xlsm, повреждённый zip
    ENCODING = "encoding"  # CSV не в UTF-8
    UNSAFE_ARCHIVE = "unsafe_archive"  # XLSX: распакованный размер/степень сжатия сверх лимита
    SHEET_NOT_FOUND = "sheet_not_found"
    TOO_MANY_ROWS = "too_many_rows"
    TOO_MANY_COLUMNS = "too_many_columns"
    # заголовок
    MISSING_COLUMN = "missing_column"
    UNKNOWN_COLUMN = "unknown_column"
    DUPLICATE_COLUMN = "duplicate_column"
    INVALID_TIER = "invalid_tier"  # price_<tier> с недопустимым именем тарифа
    # ячейка
    REQUIRED = "required"
    TOO_LONG = "too_long"
    CONTROL_CHARS = "control_chars"
    INVALID_ID = "invalid_id"  # external_id: дробное число, дата и т. п.
    INVALID_MONEY = "invalid_money"
    TOO_MANY_DECIMALS = "too_many_decimals"
    NEGATIVE_PRICE = "negative_price"
    PRICE_TOO_LARGE = "price_too_large"
    INVALID_BOOL = "invalid_bool"
    INVALID_CURRENCY = "invalid_currency"
    INVALID_CELL_TYPE = "invalid_cell_type"  # дата/время/ошибка Excel (#N/A)
    FORMULA_WITHOUT_VALUE = "formula_without_value"
    # снимок
    DUPLICATE_EXTERNAL_ID = "duplicate_external_id"
    CATEGORY_CONFLICT = "category_conflict"  # одна категория с разными name/sort_key в строках
    UNKNOWN_CATEGORY = "unknown_category"  # PUT /menu: позиция ссылается на категорию вне снимка
    EMPTY_SNAPSHOT = "empty_snapshot"
    CURRENCY_MISMATCH = "currency_mismatch"  # валюта позиции ≠ валюте заведения (ADR-7.4)
    MASS_HIDE = "mass_hide"  # снимок скрыл бы слишком много позиций (ADR-8.4)
    # предупреждения
    ZERO_PRICE = "zero_price"


@dataclass(frozen=True, slots=True)
class SyncIssue:
    """Проблема в данных. ``row`` — номер строки файла (1 — заголовок) или ``None`` для API."""

    code: IssueCode
    message: str
    severity: Severity = Severity.ERROR
    row: int | None = None
    column: str | None = None
    external_id: str | None = None
    value: str | None = None  # обрезано до MAX_ISSUE_VALUE_CHARS

    def to_dict(self) -> dict[str, Any]:
        """Форма для ``--json``, ``menu_sync_runs.issues`` и ответа API (без ``None``-полей)."""
        raise NotImplementedError


@dataclass(slots=True)
class EntityCounts:
    """Счётчики по категориям или позициям. Позиция считается ровно в одном поле:
    ``restored`` важнее ``updated`` (вернулась и изменилась — «возвращена»)."""

    created: int = 0
    updated: int = 0
    hidden: int = 0
    restored: int = 0
    unchanged: int = 0


@dataclass(slots=True)
class PriceCounts:
    created: int = 0
    updated: int = 0
    deleted: int = 0  # тариф пропал из снимка (например, vip с price_vip = 0, ТЗ A.2)


@dataclass(slots=True)
class MenuSyncReport:
    """Итог одной синхронизации (или пробного прогона)."""

    status: MenuSyncStatus
    dry_run: bool
    snapshot_hash: str | None = None
    categories: EntityCounts = field(default_factory=EntityCounts)
    items: EntityCounts = field(default_factory=EntityCounts)
    prices: PriceCounts = field(default_factory=PriceCounts)
    availability_changed: int = 0
    issues: list[SyncIssue] = field(default_factory=list)
    issues_truncated: int = 0  # сколько проблем не попало в список (> MAX_REPORTED_ISSUES)
    run_id: uuid.UUID | None = None  # запись menu_sync_runs; None — пробный прогон

    @property
    def has_errors(self) -> bool:
        raise NotImplementedError

    def counts_dict(self) -> dict[str, Any]:
        """Счётчики для ``menu_sync_runs.counts`` и ``--json``."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """Полный отчёт для ``--json`` и будущего ответа API."""
        raise NotImplementedError


def limit_issues(issues: list[SyncIssue]) -> tuple[list[SyncIssue], int]:
    """Ошибки раньше предупреждений, затем по строке; первые ``MAX_REPORTED_ISSUES`` и число отброшенных."""
    raise NotImplementedError
