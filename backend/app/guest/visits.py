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

from sqlalchemy import ColumnElement, Update, func, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.ids import new_id
from app.guest.errors import VisitOpenConflictError
from app.models.enums import Lang, VisitClosedBy, VisitStatus
from app.models.visit import OPEN_VISIT_PREDICATE, Visit

OPEN_VISIT_ATTEMPTS: Final = 3


def _open_visit_update(tenant_id: uuid.UUID, *criteria: ColumnElement[bool]) -> Update:
    """``UPDATE visits … WHERE tenant_id = :t AND status = 'open' AND <criteria>``."""
    return update(Visit).where(Visit.tenant_id == tenant_id, Visit.status == VisitStatus.OPEN.value, *criteria)


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
       циклов, затем ``VisitOpenConflictError``.

    Шаг 1 — один ``UPDATE … SET last_activity_at = now() … RETURNING *`` вместо SELECT + UPDATE."""
    touch_open = (
        _open_visit_update(tenant_id, Visit.table_id == table_id)
        .values(last_activity_at=func.now())
        .returning(Visit)
        .execution_options(populate_existing=True)
    )
    for _ in range(OPEN_VISIT_ATTEMPTS):
        visit = (await session.execute(touch_open)).scalar_one_or_none()
        if visit is not None:
            return visit, False
        open_new = (
            insert(Visit)
            .values(id=new_id(), tenant_id=tenant_id, table_id=table_id, lang=lang.value)
            .on_conflict_do_nothing(index_elements=["table_id"], index_where=text(OPEN_VISIT_PREDICATE))
            .returning(Visit)
            .execution_options(populate_existing=True)
        )
        visit = (await session.execute(open_new)).scalar_one_or_none()
        if visit is not None:
            return visit, True
    raise VisitOpenConflictError


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
    или он уже закрыт. Эндпоинта в #9 нет: потребители — тесты #9, #21, #17, #23.

    ``staff_id`` допустим только при ``closed_by = staff`` (иначе ``ValueError``)."""
    if staff_id is not None and closed_by is not VisitClosedBy.STAFF:
        raise ValueError("closed_by_staff_id задаётся только при закрытии официантом (closed_by=staff)")
    statement = (
        _open_visit_update(tenant_id, Visit.id == visit_id)
        .values(
            status=VisitStatus.CLOSED.value,
            closed_at=func.now(),
            closed_by=closed_by.value,
            closed_by_staff_id=staff_id,
        )
        .returning(Visit.id)
    )
    return (await session.execute(statement)).scalar_one_or_none() is not None


async def touch_visit(session: AsyncSession, *, tenant_id: uuid.UUID, visit_id: uuid.UUID) -> None:
    """``UPDATE visits SET last_activity_at = now() WHERE tenant_id, id, status='open'`` (для #23)."""
    await session.execute(_open_visit_update(tenant_id, Visit.id == visit_id).values(last_activity_at=func.now()))


async def set_visit_lang(session: AsyncSession, *, tenant_id: uuid.UUID, visit_id: uuid.UUID, lang: Lang) -> None:
    """``UPDATE visits SET lang, last_activity_at = now() WHERE tenant_id, id, status='open'`` —
    последний явно выбранный язык за столом (ADR-9.4)."""
    await session.execute(
        _open_visit_update(tenant_id, Visit.id == visit_id).values(lang=lang.value, last_activity_at=func.now())
    )
