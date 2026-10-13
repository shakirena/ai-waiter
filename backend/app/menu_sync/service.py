"""Применение снимка меню в ядре (ADR-8.1, ADR-8.4, ADR-8.5, DEC-011). Единый путь для файла и ``PUT /menu``.

``apply_menu_snapshot`` выполняется внутри транзакции вызывающего и сам её не фиксирует (как
``apply_seed``): CLI оборачивает вызов в ``session.begin()``, ``PUT /menu`` (#16) — так же,
db-тесты — в откатываемую транзакцию. Порядок шагов (в скобках — story, которая добавляет шаг):

1. (#62) ``pg_try_advisory_xact_lock(MENU_SYNC_LOCK_NAMESPACE, hashtext(tenant_id::text))`` — не
   получилось → ``MenuSyncBusyError`` (параллельная синхронизация того же заведения; тот же
   lock берёт ``PUT /stoplist`` в #16, потому что пишет ``menu_items.is_available``);
2. (#62) заведение по ``tenant_id`` (нет → ``TenantNotFoundError``), ``check_snapshot``,
   ``resolve_currency``; ошибки → итог ``rejected``, ничего не пишется;
3. (#63) ``snapshot_hash``; хеш равен ``last_applied_hash`` и нет ``force`` → итог ``unchanged``,
   данные меню не трогаются (INT-1);
4. (#62) ``load_current_menu`` → ``plan_menu_sync``; ошибки плана → ``rejected``;
5. (#62) не ``dry_run`` → пакетная запись плана (``INSERT … ON CONFLICT (tenant_id, external_id) DO UPDATE``
   для категорий и позиций, ``(menu_item_id, price_tier)`` для цен; ``updated_at`` — явно);
6. (#63) не ``dry_run`` → строка ``menu_sync_runs`` (``applied``/``unchanged``) в той же транзакции.

До #63 сервис работает без журнала: ``snapshot_hash`` и ``run_id`` в отчёте — ``None``, статусы —
только ``applied``/``rejected``, параметр ``force`` принимается и ни на что не влияет. #63 вставляет
шаги 3 и 6, не меняя сигнатуру.

Отклонённый снимок журналируется отдельно (``record_rejected_run``) после отката основной
транзакции: иначе запись об ошибке откатилась бы вместе с ней (FR-20 — «ошибки коннектора»).

События EventBus не публикуются: CLI — отдельный процесс, в ``single`` шина в памяти не
пересекает процессы. Потребители меню (#10, #11) читают БД и не кешируют меню в памяти процесса
(ADR-8.6).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Final

from app.menu_sync.plan import CurrentMenu
from app.menu_sync.report import MenuSyncReport, SyncIssue
from app.menu_sync.snapshot import MenuSnapshot
from app.models.enums import MenuSyncSource

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Первый ключ двухаргументного advisory lock — «пространство» синхронизации меню (номер issue).
MENU_SYNC_LOCK_NAMESPACE: Final[int] = 8
# source_ref хранится без пути: только имя файла или «тип/версия» коннектора.
SOURCE_REF_MAX: Final[int] = 255


class MenuSyncError(RuntimeError):
    """Базовая ошибка синхронизации, не связанная с данными снимка."""


class MenuSyncBusyError(MenuSyncError):
    """Синхронизация меню этого заведения уже идёт (advisory lock занят)."""


class TenantNotFoundError(MenuSyncError):
    """Заведения с таким ``tenant_id`` нет."""


async def load_current_menu(session: AsyncSession, tenant_id: uuid.UUID) -> CurrentMenu:
    """Категории, позиции (включая скрытые) и цены заведения; фильтр ``tenant_id`` в каждом запросе."""
    raise NotImplementedError


async def last_applied_hash(session: AsyncSession, tenant_id: uuid.UUID) -> str | None:
    """(#63) Хеш последнего снимка со статусом ``applied``/``unchanged`` (любой источник) или ``None``."""
    raise NotImplementedError


async def apply_menu_snapshot(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    snapshot: MenuSnapshot,
    source: MenuSyncSource,
    source_ref: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    allow_mass_hide: bool = False,
) -> MenuSyncReport:
    """Применить полный снимок меню заведения (шаги — в docstring модуля).

    Не коммитит. ``dry_run`` — всё, кроме записи (lock тоже берётся: счётчики считаются по
    согласованному состоянию). Ошибки данных возвращаются в отчёте (``rejected``), а не исключением;
    исключения — только ``MenuSyncBusyError``, ``TenantNotFoundError`` и ошибки БД.
    """
    raise NotImplementedError


async def record_rejected_run(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source: MenuSyncSource,
    source_ref: str | None,
    issues: list[SyncIssue],
    snapshot_hash: str | None = None,
) -> uuid.UUID:
    """(#63) Записать ``menu_sync_runs`` со статусом ``rejected`` (проблемы — ``limit_issues``). Не коммитит.

    Вызывается в новой транзакции после отката: и для ошибок разбора файла (снимка нет, хеша нет),
    и для ``rejected`` из ``apply_menu_snapshot``. Пробный прогон не журналируется.
    """
    raise NotImplementedError
