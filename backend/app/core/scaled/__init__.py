"""Реализации для режима scaled (Redis, arq).

Единственный пакет, где разрешён импорт ``redis`` и ``arq`` (ruff TID251, ADR-1).
Импортируется лениво из ``app.core.container`` только при ``APP_MODE=scaled``.
"""
