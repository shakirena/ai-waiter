"""Отчёт синхронизации меню (story #61, счётчики — #62; ADR-8.4).

Проблемы с местом (строка, колонка) и счётчики изменений.

Один формат для CLI (текст и ``--json``), журнала ``menu_sync_runs`` (``counts``/``issues`` jsonb),
будущего ответа админки и ``PUT /menu`` (#16). Сообщения — на русском, коды — стабильные
идентификаторы для тестов и фронтенда.
"""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

from app.models.enums import MenuSyncStatus

# Сколько проблем хранить в журнале и показывать; остальные — числом «и ещё N».
MAX_REPORTED_ISSUES: Final[int] = 100
# Значение ячейки в сообщении обрезается до этой длины.
MAX_ISSUE_VALUE_CHARS: Final[int] = 60
# external_id в проблеме: = snapshot.EXTERNAL_ID_MAX (= CHECK в БД), чтобы допустимый id не обрезался.
MAX_ISSUE_EXTERNAL_ID_CHARS: Final[int] = 64
# Поле (колонка, путь в снимке: в нём бывают ключи из входных данных) и текст сообщения.
MAX_ISSUE_COLUMN_CHARS: Final[int] = 100
MAX_ISSUE_MESSAGE_CHARS: Final[int] = 500
# Невидимые и управляющие символы (Unicode Cc, Cf, Zl, Zp): C0/C1, DEL, U+0085, U+2028/U+2029,
# bidi-переключатели, zero-width, BOM. В тексте проблемы они показываются экранированными
# (escape-последовательности x1b, u202e с обратной косой), чтобы не управлять терминалом CLI
# и не переставлять текст в админке.
# и не переставлять текст в админке.
INVISIBLE_CATEGORIES: Final[frozenset[str]] = frozenset({"Cc", "Cf", "Zl", "Zp"})


def escape_invisible(text: str) -> str:
    """Заменить символы категорий ``INVISIBLE_CATEGORIES`` на ``\\xNN``/``\\uNNNN``/``\\UNNNNNNNN``."""
    parts: list[str] = []
    for char in text:
        if unicodedata.category(char) not in INVISIBLE_CATEGORIES:
            parts.append(char)
            continue
        code = ord(char)
        if code <= 0xFF:
            parts.append(f"\\x{code:02x}")
        elif code <= 0xFFFF:
            parts.append(f"\\u{code:04x}")
        else:
            parts.append(f"\\U{code:08x}")
    return "".join(parts)


def safe_text(text: str, max_chars: int) -> str:
    """Экранировать невидимые символы и обрезать до ``max_chars`` (с «…» на конце)."""
    # Сначала обрезка по исходной длине: экранирование гигантской строки не нужно.
    escaped = escape_invisible(text[: max_chars + 1])
    if len(escaped) > max_chars:
        escaped = escaped[: max_chars - 1] + "…"
    return escaped


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


def issue_value(value: object) -> str | None:
    """Значение для ``SyncIssue.value``: только скаляры; невидимые символы экранируются, длина ≤ 60.

    Составные значения (словарь, список) не показываются — ``None``.
    """
    if value is None or isinstance(value, dict | list | tuple | set):
        return None
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, str | int | float | Decimal):
        text = str(value)
    else:
        return None
    return safe_text(text, MAX_ISSUE_VALUE_CHARS)


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

    def __post_init__(self) -> None:
        # Все текстовые поля могут нести входные данные: длина ограничена, невидимые символы
        # экранированы, кто бы ни создал проблему (снимок, разбор файла, план).
        object.__setattr__(self, "message", safe_text(self.message, MAX_ISSUE_MESSAGE_CHARS))
        if self.column is not None:
            object.__setattr__(self, "column", safe_text(self.column, MAX_ISSUE_COLUMN_CHARS))
        if self.external_id is not None:
            object.__setattr__(self, "external_id", safe_text(self.external_id, MAX_ISSUE_EXTERNAL_ID_CHARS))
        if self.value is not None:
            object.__setattr__(self, "value", issue_value(self.value))

    def to_dict(self) -> dict[str, Any]:
        """Форма для ``--json``, ``menu_sync_runs.issues`` и ответа API (без ``None``-полей)."""
        result: dict[str, Any] = {
            "code": self.code.value,
            "severity": self.severity.value,
            "message": self.message,
        }
        for key in ("row", "column", "external_id", "value"):
            item = getattr(self, key)
            if item is not None:
                result[key] = item
        return result


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
        return has_errors(self.issues)

    def counts_dict(self) -> dict[str, Any]:
        """Счётчики для ``menu_sync_runs.counts`` и ``--json``."""
        return {
            "categories": asdict(self.categories),
            "items": asdict(self.items),
            "prices": asdict(self.prices),
            "availability_changed": self.availability_changed,
        }

    def to_dict(self) -> dict[str, Any]:
        """Полный отчёт для ``--json`` и будущего ответа API."""
        return {
            "status": self.status.value,
            "dry_run": self.dry_run,
            "snapshot_hash": self.snapshot_hash,
            "run_id": str(self.run_id) if self.run_id is not None else None,
            "counts": self.counts_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
            "issues_truncated": self.issues_truncated,
        }


def has_errors(issues: list[SyncIssue]) -> bool:
    """Есть ли среди проблем ошибки (``severity=error``): тогда снимок не применяется."""
    return any(issue.severity is Severity.ERROR for issue in issues)


def limit_issues(issues: list[SyncIssue]) -> tuple[list[SyncIssue], int]:
    """Ошибки раньше предупреждений, затем по строке; первые ``MAX_REPORTED_ISSUES`` и число отброшенных.

    Проблемы без строки (уровень файла, API) идут первыми; при равенстве порядок сохраняется.
    """
    ordered = sorted(
        issues,
        key=lambda issue: (issue.severity is not Severity.ERROR, issue.row if issue.row is not None else 0),
    )
    return ordered[:MAX_REPORTED_ISSUES], max(0, len(ordered) - MAX_REPORTED_ISSUES)
