"""Синхронизация меню заведения: единый путь для файлового импорта (#8) и ``PUT /menu`` (#16).

docs/arch/feature-8-menu-import.md, ADR-8.1, DEC-011.

Поток данных::

    CSV/XLSX ──files.read_menu_file──┐
                                     ├─► MenuSnapshot ──apply_menu_snapshot──► categories,
    PUT /integration/v1/menu (#16) ──┘                                        menu_items, menu_item_prices,
                                                                              menu_sync_runs

Модули:

- ``snapshot`` — Pydantic-модель снимка (форма тела ``PUT /menu``, ТЗ 4.4) и его хеш (INT-1);
- ``report`` — коды проблем, счётчики, отчёт синхронизации;
- ``plan`` — чистое сравнение «что в БД» ↔ «что в снимке», без БД (тестируется на Windows);
- ``service`` — применение снимка в одной транзакции под advisory lock заведения;
- ``files`` — разбор CSV/XLSX в снимок; без SQLAlchemy;
- ``__main__`` — CLI ``python -m app.menu_sync check|import``.

Границы импортов (``tests/test_import_boundaries.py``):

- ``app.menu_sync.files`` не импортирует ``sqlalchemy``, ``app.db``, ``app.models`` (кроме ``enums``);
- ``openpyxl`` — только в ``app/menu_sync/files/xlsx_reader.py``;
- пакет не импортирует ``fastapi`` и ``app.api``: роутеры (#16, админка) вызывают его, а не наоборот;
- ``app.core`` не импортирует ``app.menu_sync``.

В ядре нет кода под конкретную кассу: касса превращает свои данные в снимок сама (коннектор)
или в файл формата ``files`` (утилита на стороне кассы, ADR-8.8).
"""
