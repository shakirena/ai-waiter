"""Файловый коннектор: CSV/XLSX → ``MenuSnapshot`` (story #64, XLSX — #65; ADR-8.2).

Без БД — идёт в unit-тестах на Windows.

Формат описан в ``format`` и в docs/arch/feature-8-menu-import.md («Формат файла»); пример —
``backend/tests/fixtures/menu/menu_valid.csv`` (данные вымышленные).

``read_menu_file`` читает байты (лимит ``MAX_FILE_BYTES`` проверяется до чтения содержимого),
определяет формат по расширению и сигнатуре, вызывает ``csv_reader``/``xlsx_reader`` →
``TabularData`` → ``format.rows_to_snapshot``. Пути к файлу приходят только из аргументов
CLI или из загрузки в админке — в коде путей нет.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

from app.menu_sync.report import SyncIssue
from app.menu_sync.snapshot import MenuSnapshot

MAX_FILE_BYTES: Final[int] = 5 * 1024 * 1024
# Сигнатура zip (XLSX — zip-архив Office Open XML).
ZIP_SIGNATURE: Final[bytes] = b"PK\x03\x04"


class FileFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"


@dataclass(frozen=True, slots=True)
class ParsedMenuFile:
    """Результат разбора. ``snapshot is None`` ⇔ есть ошибки (``issues`` с ``severity=error``)."""

    file_format: FileFormat
    snapshot: MenuSnapshot | None
    issues: list[SyncIssue] = field(default_factory=list)
    rows_total: int = 0  # строк данных без заголовка и пустых
    item_rows: dict[str, int] = field(default_factory=dict)  # external_id позиции → номер строки
    has_availability: bool = False  # есть ли колонка is_available (иначе наличие не меняется)


def detect_format(filename: str, head: bytes) -> FileFormat | None:
    """Формат по расширению (``.csv``/``.xlsx``, без учёта регистра) с проверкой сигнатуры:
    ``.xlsx`` без ``ZIP_SIGNATURE`` или ``.csv`` с ней — ``None`` (``unsupported_format``)."""
    raise NotImplementedError


def parse_menu_bytes(data: bytes, filename: str, *, sheet: str | None = None) -> ParsedMenuFile:
    """Разобрать содержимое файла (общая точка для CLI и будущей загрузки в админке).

    ``filename`` — только для определения формата и сообщений; ``sheet`` — имя листа XLSX.
    """
    raise NotImplementedError


def read_menu_file(path: Path, *, sheet: str | None = None) -> ParsedMenuFile:
    """Прочитать файл с диска (размер — ``stat`` до чтения) и вызвать ``parse_menu_bytes``."""
    raise NotImplementedError
