"""XLSX → ``TabularData`` (story #65; ADR-8.2, ADR-8.7). Единственный модуль, импортирующий ``openpyxl``.

Зависимости (добавляет developer в ``backend/pyproject.toml``): ``openpyxl>=3.1`` и ``defusedxml>=0.7``
(openpyxl сам использует defusedxml, если он установлен, — защита от XML-бомб).

Безопасность до разбора (``zipfile``, без openpyxl):

- сигнатура zip, наличие ``xl/workbook.xml``; ``vbaProject.bin`` (макросы) — ``unsupported_format``;
- сумма распакованных размеров ≤ ``MAX_UNCOMPRESSED_BYTES``, степень сжатия каждого члена ≤
  ``MAX_COMPRESSION_RATIO`` — иначе ``unsafe_archive`` (zip-бомба).

Разбор: ``load_workbook(BytesIO(data), read_only=True, data_only=True)`` — формулы не
вычисляются, берётся сохранённое значение; формула без сохранённого значения —
``formula_without_value``. Лист — ``sheet`` из аргумента, иначе лист ``menu`` (без учёта
регистра), иначе первый. Ячейки с ошибками Excel (``#N/A``) и датами — ``invalid_cell_type``.
Номер строки — номер строки листа. Книга закрывается в ``finally``.
"""

from __future__ import annotations

from typing import Final

from app.menu_sync.files.format import TabularData
from app.menu_sync.report import SyncIssue

DEFAULT_SHEET_NAME: Final[str] = "menu"
MAX_UNCOMPRESSED_BYTES: Final[int] = 50 * 1024 * 1024
MAX_COMPRESSION_RATIO: Final[int] = 100


def check_xlsx_archive(data: bytes) -> list[SyncIssue]:
    """Проверки zip-контейнера до openpyxl (сигнатура, макросы, zip-бомба)."""
    raise NotImplementedError


def read_xlsx_table(data: bytes, *, sheet: str | None = None) -> tuple[TabularData | None, list[SyncIssue]]:
    """Прочитать лист XLSX из байтов; ``None`` и проблемы уровня файла/листа/заголовка при неудаче."""
    raise NotImplementedError
