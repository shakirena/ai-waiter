"""Визит стола: get-or-open, закрытие, активность, язык (#9, ADR-9.3, ADR-9.4; ТЗ FR-14a, ADR-7.5).

Открытый визит у стола один — гарантирует частичный уникальный индекс ``uq_visits_open_table``
(``table_id`` WHERE ``status = 'open'``). Гонка двух сканирований решается
``INSERT … ON CONFLICT (table_id) WHERE status = 'open' DO NOTHING RETURNING *``: транзакция не
прерывается, SAVEPOINT и перехват ``IntegrityError`` не нужны. Код одинаков в ``single``/``scaled``.

Все запросы фильтруют по ``tenant_id``. Commit делает вызывающий (``entry`` или будущие #17, #21, #23).
EventBus-событий нет (раздел «События и фоновые задачи» arch).
"""

from __future__ import annotations

import uuid
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Lang, VisitClosedBy
from app.models.visit import Visit

OPEN_VISIT_ATTEMPTS: Final = 3


async def get_or_open_visit(
    session: AsyncSession, *, tenant_id: uuid.UUID, table_id: uuid.UUID, lang: Lang
) -> tuple[Visit, bool]:
    """Открытый визит стола или новый; второй элемент — ``created``.

    1. ``SELECT … WHERE tenant_id, table_id, status='open'``; найден — ``last_activity_at = now()``,
       ``created=False`` (``lang`` найденного визита не меняется);
    2. иначе ``postgresql.insert(Visit).values(id=new_id(), tenant_id, table_id, lang)
       .on_conflict_do_nothing(index_elements=["table_id"], index_where=text(OPEN_VISIT_PREDICATE))
       .returning(Visit)``; строка вернулась — ``created=True``;
    3. пусто — визит открыл параллельный запрос: снова шаг 1. Не больше ``OPEN_VISIT_ATTEMPTS``
       циклов, затем ``VisitOpenConflictError``."""
    raise NotImplementedError


async def close_visit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    visit_id: uuid.UUID,
    closed_by: VisitClosedBy,
    staff_id: uuid.UUID | None = None,
) -> bool:
    """``UPDATE visits SET status='closed', closed_at=now(), closed_by, closed_by_staff_id
    WHERE tenant_id, id, status='open'``. ``True`` — визит закрыт этим вызовом; ``False`` — его нет
    или он уже закрыт. Эндпоинта в #9 нет: потребители — тесты #9, #21, #17, #23."""
    raise NotImplementedError


async def touch_visit(session: AsyncSession, *, tenant_id: uuid.UUID, visit_id: uuid.UUID) -> None:
    """``UPDATE visits SET last_activity_at = now() WHERE tenant_id, id, status='open'`` (для #23)."""
    raise NotImplementedError


async def set_visit_lang(session: AsyncSession, *, tenant_id: uuid.UUID, visit_id: uuid.UUID, lang: Lang) -> None:
    """``UPDATE visits SET lang, last_activity_at = now() WHERE tenant_id, id, status='open'`` —
    последний явно выбранный язык за столом (ADR-9.4)."""
    raise NotImplementedError
