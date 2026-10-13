"""CSV → ``TabularData`` (story #64, ADR-8.2). Только стандартная библиотека (``csv``).

- Кодировка — UTF-8, BOM допускается (``utf-8-sig``, так сохраняет Excel «CSV UTF-8»); иная —
  ``encoding`` с подсказкой пересохранить файл как «CSV UTF-8».
- Разделитель — ``,`` или ``;`` (Excel с русской/азербайджанской локалью сохраняет ``;``):
  определяется по строке заголовка — тот, при котором находятся обязательные колонки; при ``;``
  допускается десятичная запятая.
- Кавычки — RFC 4180 (``"`` удваивается внутри поля), переводы строк внутри кавычек допустимы;
  номер строки для сообщений — номер физической строки начала записи.
- Пустые строки (все поля пустые) пропускаются; лимиты ``MAX_DATA_ROWS``, ``MAX_COLUMNS``,
  ``MAX_CELL_CHARS`` (``csv.field_size_limit``) проверяются при чтении.
"""

from __future__ import annotations

from app.menu_sync.files.format import TabularData
from app.menu_sync.report import SyncIssue


def read_csv_table(data: bytes) -> tuple[TabularData | None, list[SyncIssue]]:
    """Прочитать CSV из байтов; ``None`` и проблемы уровня файла/заголовка при неудаче."""
    raise NotImplementedError
