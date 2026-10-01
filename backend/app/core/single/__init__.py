"""Реализации для режима single (в памяти процесса, APScheduler).

Импортируется лениво из ``app.core.container`` только при ``APP_MODE=single``.
Импорт apscheduler разрешён только здесь (ruff TID251, ADR-1).
"""
