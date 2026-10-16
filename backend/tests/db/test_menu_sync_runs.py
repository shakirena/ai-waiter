"""Журнал ``menu_sync_runs`` и пропуск неизменённого снимка на PostgreSQL (story #63, AC-3, ADR-8.5).

AC #63: снимок применён (``applied`` с хешем) → тот же снимок в другом порядке без ``force`` →
таблицы меню не меняются (``updated_at``, ``synced_at`` прежние), в журнале ``unchanged`` с тем же
хешем, источником и временем запуска.

Внутри одной транзакции ``now()`` постоянен: после первого применения тест возвращает строкам меню
старые ``updated_at``/``synced_at`` (``OLD``) — так видно, тронул ли их повторный вызов.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.menu_sync.report import (
    MAX_ISSUE_VALUE_CHARS,
    MAX_REPORTED_ISSUES,
    IssueCode,
    MenuSyncReport,
    SyncIssue,
)
from app.menu_sync.service import apply_menu_snapshot, last_applied_hash, record_rejected_run
from app.menu_sync.snapshot import MenuSnapshot
from app.models.enums import MenuSyncSource, MenuSyncStatus
from app.models.menu import Category, MenuItem, MenuItemPrice
from app.models.menu_sync import MenuSyncRun
from tests.db.factories import create_tenant, expect_insert_violation

pytestmark = pytest.mark.db

OLD = datetime(2026, 1, 1, tzinfo=UTC)
HASH_A = "a" * 64


def _snap_item(external_id: str, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "external_id": external_id,
        "category_external_id": "19",
        "name": f"Блюдо {external_id}",
        "prices": {"default": "8.00", "vip": "10.00"},
    }
    item.update(overrides)
    return item


CATEGORIES = [
    {"external_id": "19", "name": "Isti yemekler", "sort_key": "19"},
    {"external_id": "20", "name": "Salatlar", "sort_key": "20"},
]
ITEMS = [_snap_item("1001"), _snap_item("1002", category_external_id="20"), _snap_item("1003", is_available=False)]


def _snapshot(
    items: list[dict[str, Any]] | None = None, categories: list[dict[str, Any]] | None = None
) -> MenuSnapshot:
    return MenuSnapshot.model_validate(
        {"categories": CATEGORIES if categories is None else categories, "items": ITEMS if items is None else items}
    )


def _reordered() -> MenuSnapshot:
    """Те же данные: позиции, категории и тарифы в другом порядке."""
    items = [{**item, "prices": dict(reversed(item["prices"].items()))} for item in reversed(ITEMS)]
    return _snapshot(items, list(reversed(CATEGORIES)))


async def _apply(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    snapshot: MenuSnapshot,
    *,
    source: MenuSyncSource = MenuSyncSource.FILE,
    source_ref: str | None = "menu.csv",
    **kwargs: Any,
) -> MenuSyncReport:
    return await apply_menu_snapshot(
        session, tenant_id=tenant_id, snapshot=snapshot, source=source, source_ref=source_ref, **kwargs
    )


async def _runs(session: AsyncSession, tenant_id: uuid.UUID) -> list[Any]:
    """Строки журнала заведения в порядке записи (свежие значения из БД)."""
    rows = await session.execute(
        select(
            MenuSyncRun.id,
            MenuSyncRun.source,
            MenuSyncRun.source_ref,
            MenuSyncRun.status,
            MenuSyncRun.snapshot_hash,
            MenuSyncRun.started_at,
            MenuSyncRun.finished_at,
            MenuSyncRun.counts,
            MenuSyncRun.issues,
        )
        .where(MenuSyncRun.tenant_id == tenant_id)
        .order_by(MenuSyncRun.finished_at, MenuSyncRun.id)
    )
    return list(rows)


async def _age_menu(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Вернуть строкам меню заведения старые ``updated_at``/``synced_at``."""
    for model in (Category, MenuItem):
        await session.execute(
            update(model).where(model.tenant_id == tenant_id).values(updated_at=OLD, synced_at=OLD)  # type: ignore[attr-defined]
        )
    await session.execute(update(MenuItemPrice).where(MenuItemPrice.tenant_id == tenant_id).values(updated_at=OLD))


async def _menu_times(session: AsyncSession, tenant_id: uuid.UUID) -> set[datetime]:
    """Все ``updated_at``/``synced_at`` меню заведения."""
    values: set[datetime] = set()
    for model in (Category, MenuItem):
        rows = await session.execute(
            select(model.updated_at, model.synced_at).where(model.tenant_id == tenant_id)  # type: ignore[attr-defined]
        )
        for row in rows:
            values.update(row)
    values.update(await session.scalars(select(MenuItemPrice.updated_at).where(MenuItemPrice.tenant_id == tenant_id)))
    return values


# ---------------------------------------------------------------- AC #63


async def test_ac63_same_snapshot_in_other_order_is_unchanged(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    applied = await _apply(db_session, tenant.id, _snapshot())
    assert applied.status is MenuSyncStatus.APPLIED
    assert applied.snapshot_hash is not None
    assert applied.run_id is not None
    await _age_menu(db_session, tenant.id)

    report = await _apply(db_session, tenant.id, _reordered())

    assert report.status is MenuSyncStatus.UNCHANGED
    assert report.dry_run is False
    assert report.snapshot_hash == applied.snapshot_hash
    assert report.run_id is not None
    assert report.counts_dict() == MenuSyncReport(status=MenuSyncStatus.UNCHANGED, dry_run=False).counts_dict()
    assert await _menu_times(db_session, tenant.id) == {OLD}  # таблицы меню не тронуты

    first, second = await _runs(db_session, tenant.id)
    assert (first.id, first.status, first.snapshot_hash) == (applied.run_id, "applied", applied.snapshot_hash)
    assert first.counts == applied.counts_dict()
    assert first.counts["items"]["created"] == 3
    assert second.id == report.run_id
    assert (second.status, second.snapshot_hash) == ("unchanged", applied.snapshot_hash)
    assert (second.source, second.source_ref) == (first.source, first.source_ref) == ("file", "menu.csv")
    assert second.issues == []
    # Время запуска записано и не раньше предыдущей синхронизации.
    assert first.started_at <= first.finished_at <= second.started_at <= second.finished_at
    assert second.finished_at - second.started_at < timedelta(minutes=1)


async def test_force_applies_same_snapshot_again(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    applied = await _apply(db_session, tenant.id, _snapshot())
    await _age_menu(db_session, tenant.id)

    report = await _apply(db_session, tenant.id, _reordered(), force=True)

    assert report.status is MenuSyncStatus.APPLIED
    assert report.snapshot_hash == applied.snapshot_hash
    assert report.items.unchanged == 3
    now = await db_session.scalar(select(func.now()))
    synced = set(await db_session.scalars(select(MenuItem.synced_at).where(MenuItem.tenant_id == tenant.id)))
    assert synced == {now}  # пересчитано: synced_at обновлён
    assert [run.status for run in await _runs(db_session, tenant.id)] == ["applied", "applied"]


async def test_changed_snapshot_is_applied_and_hash_moves(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    first = await _apply(db_session, tenant.id, _snapshot())
    changed = await _apply(db_session, tenant.id, _snapshot([*ITEMS[:2], _snap_item("1003", is_available=True)]))

    assert changed.status is MenuSyncStatus.APPLIED
    assert changed.snapshot_hash != first.snapshot_hash
    assert changed.availability_changed == 1
    assert await last_applied_hash(db_session, tenant.id) == changed.snapshot_hash
    # Возврат к первому снимку — снова применение, а не unchanged: сравнивается последний хеш.
    back = await _apply(db_session, tenant.id, _snapshot())
    assert back.status is MenuSyncStatus.APPLIED


async def test_other_source_with_same_hash_is_unchanged(db_session: AsyncSession) -> None:
    """Состояние меню одно на заведение: хеш файла совпал — снимок коннектора не пересчитывается."""
    tenant = await create_tenant(db_session)
    applied = await _apply(db_session, tenant.id, _snapshot())

    report = await _apply(db_session, tenant.id, _snapshot(), source=MenuSyncSource.CONNECTOR, source_ref="yii2/1.0")

    assert report.status is MenuSyncStatus.UNCHANGED
    last = (await _runs(db_session, tenant.id))[-1]
    assert (last.source, last.source_ref, last.snapshot_hash) == ("connector", "yii2/1.0", applied.snapshot_hash)
    # unchanged тоже служит «последним применённым» — третий раз снова unchanged.
    again = await _apply(db_session, tenant.id, _snapshot())
    assert again.status is MenuSyncStatus.UNCHANGED


async def test_dry_run_is_not_journaled(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    preview = await _apply(db_session, tenant.id, _snapshot(), dry_run=True)
    assert (preview.status, preview.dry_run, preview.run_id) == (MenuSyncStatus.APPLIED, True, None)
    assert preview.snapshot_hash is not None
    assert await _runs(db_session, tenant.id) == []
    assert await last_applied_hash(db_session, tenant.id) is None

    await _apply(db_session, tenant.id, _snapshot())
    repeat_preview = await _apply(db_session, tenant.id, _reordered(), dry_run=True)
    assert (repeat_preview.status, repeat_preview.run_id) == (MenuSyncStatus.UNCHANGED, None)
    assert len(await _runs(db_session, tenant.id)) == 1


async def test_source_ref_is_file_name_without_directory(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    await _apply(db_session, tenant.id, _snapshot(), source_ref="C:\\Users\\admin\\Desktop\\export\\menu.xlsx")
    await _apply(db_session, tenant.id, _snapshot(), source_ref=None)
    refs = [run.source_ref for run in await _runs(db_session, tenant.id)]
    assert refs == ["menu.xlsx", None]


# ---------------------------------------------------------------- rejected


async def test_rejected_is_journaled_after_rollback(db_session: AsyncSession) -> None:
    """Сервис не пишет ``rejected`` сам: вызывающий откатывает транзакцию и вызывает ``record_rejected_run``."""
    tenant = await create_tenant(db_session)
    applied = await _apply(db_session, tenant.id, _snapshot())
    bad = _snapshot([_snap_item("1001", currency="USD")])

    async with db_session.begin_nested() as attempt:
        report = await _apply(db_session, tenant.id, bad, source_ref="/srv/import/bad.csv")
        await attempt.rollback()
    assert report.status is MenuSyncStatus.REJECTED
    assert report.snapshot_hash is None  # отвергнут check_snapshot до расчёта хеша
    assert report.run_id is None
    assert len(await _runs(db_session, tenant.id)) == 1

    run_id = await record_rejected_run(
        db_session,
        tenant_id=tenant.id,
        source=MenuSyncSource.FILE,
        source_ref="/srv/import/bad.csv",
        issues=report.issues,
    )
    last = (await _runs(db_session, tenant.id))[-1]
    assert (last.id, last.status, last.snapshot_hash, last.source_ref) == (run_id, "rejected", None, "bad.csv")
    assert [issue["code"] for issue in last.issues] == [IssueCode.CURRENCY_MISMATCH.value]
    assert last.counts == {}
    assert last.started_at <= last.finished_at
    # Отклонённый снимок не меняет «последний применённый» хеш.
    assert await last_applied_hash(db_session, tenant.id) == applied.snapshot_hash


async def test_rejected_by_plan_has_hash_and_does_not_count_as_applied(db_session: AsyncSession) -> None:
    """Ошибка плана (массовое скрытие) — хеш снимка уже посчитан и передаётся в журнал."""
    tenant = await create_tenant(db_session)
    many = [_snap_item(str(2000 + n)) for n in range(12)]
    applied = await _apply(db_session, tenant.id, _snapshot(many))
    hiding = _snapshot(many[:1])

    report = await _apply(db_session, tenant.id, hiding)
    assert report.status is MenuSyncStatus.REJECTED
    assert report.snapshot_hash is not None
    assert report.snapshot_hash != applied.snapshot_hash
    started = datetime.now(UTC) - timedelta(seconds=5)
    await record_rejected_run(
        db_session,
        tenant_id=tenant.id,
        source=MenuSyncSource.CONNECTOR,
        source_ref="yii2/1.0",
        issues=report.issues,
        snapshot_hash=report.snapshot_hash,
        started_at=started,
    )
    last = (await _runs(db_session, tenant.id))[-1]
    assert (last.status, last.snapshot_hash, last.started_at) == ("rejected", report.snapshot_hash, started)
    assert await last_applied_hash(db_session, tenant.id) == applied.snapshot_hash
    # Тот же снимок с разрешением массового скрытия применяется: rejected не делает его «неизменным».
    allowed = await _apply(db_session, tenant.id, hiding, allow_mass_hide=True)
    assert allowed.status is MenuSyncStatus.APPLIED


async def test_rejected_issues_are_limited_and_values_truncated(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    issues = [
        SyncIssue(IssueCode.INVALID_MONEY, "не число", row=n + 2, column="price_default", value="x" * 500)
        for n in range(MAX_REPORTED_ISSUES + 25)
    ]
    await record_rejected_run(
        db_session, tenant_id=tenant.id, source=MenuSyncSource.FILE, source_ref="menu.csv", issues=issues
    )
    [run] = await _runs(db_session, tenant.id)
    assert len(run.issues) == MAX_REPORTED_ISSUES
    assert run.counts == {"issues_truncated": 25}
    assert {len(issue["value"]) for issue in run.issues} == {MAX_ISSUE_VALUE_CHARS}
    assert run.issues[0] == {
        "code": "invalid_money",
        "severity": "error",
        "message": "не число",
        "row": 2,
        "column": "price_default",
        "value": "x" * (MAX_ISSUE_VALUE_CHARS - 1) + "…",
    }


async def test_applied_with_warnings_keeps_them_in_journal(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    report = await _apply(db_session, tenant.id, _snapshot([*ITEMS, _snap_item("1004", prices={"default": "0"})]))
    assert report.status is MenuSyncStatus.APPLIED
    [run] = await _runs(db_session, tenant.id)
    assert [issue["code"] for issue in run.issues] == ["zero_price"]
    assert "issues_truncated" not in run.counts


# ---------------------------------------------------------------- изоляция заведений


async def test_journal_and_hash_are_tenant_scoped(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    other = await create_tenant(db_session, name="Другое заведение")
    applied = await _apply(db_session, other.id, _snapshot())

    assert await last_applied_hash(db_session, tenant.id) is None
    report = await _apply(db_session, tenant.id, _snapshot())
    assert report.status is MenuSyncStatus.APPLIED  # хеш другого заведения не учитывается
    assert report.snapshot_hash == applied.snapshot_hash
    await record_rejected_run(
        db_session, tenant_id=other.id, source=MenuSyncSource.FILE, source_ref="other.csv", issues=[]
    )

    assert [run.status for run in await _runs(db_session, tenant.id)] == ["applied"]
    assert [run.status for run in await _runs(db_session, other.id)] == ["applied", "rejected"]


async def test_last_applied_hash_takes_latest_applied_or_unchanged(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    base = datetime(2026, 5, 1, tzinfo=UTC)
    rows = [
        ("applied", "1" * 64, base),
        ("unchanged", "2" * 64, base + timedelta(minutes=5)),
        ("rejected", "3" * 64, base + timedelta(minutes=10)),
    ]
    for status, digest, finished in rows:
        db_session.add(
            MenuSyncRun(
                tenant_id=tenant.id,
                source="connector",
                status=status,
                snapshot_hash=digest,
                started_at=finished,
                finished_at=finished,
            )
        )
    await db_session.flush()
    assert await last_applied_hash(db_session, tenant.id) == "2" * 64


# ---------------------------------------------------------------- CHECK


def _run(tenant_id: uuid.UUID, **values: Any) -> MenuSyncRun:
    data: dict[str, Any] = {
        "tenant_id": tenant_id,
        "source": "file",
        "status": "applied",
        "snapshot_hash": HASH_A,
        "started_at": OLD,
        "finished_at": OLD,
    }
    data.update(values)
    return MenuSyncRun(**data)


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"snapshot_hash": None}, "ck_menu_sync_runs_hash_state"),
        ({"status": "unchanged", "snapshot_hash": None}, "ck_menu_sync_runs_hash_state"),
        ({"finished_at": OLD - timedelta(seconds=1)}, "ck_menu_sync_runs_finished_at"),
        ({"source": "manual"}, "ck_menu_sync_runs_source"),
        ({"status": "skipped"}, "ck_menu_sync_runs_status"),
        ({"snapshot_hash": "A" * 64}, "ck_menu_sync_runs_snapshot_hash"),
        ({"snapshot_hash": "a" * 63}, "ck_menu_sync_runs_snapshot_hash"),
        ({"source_ref": ""}, "ck_menu_sync_runs_source_ref"),
        ({"source_ref": "m" * 256}, "ck_menu_sync_runs_source_ref"),
        ({"counts": []}, "ck_menu_sync_runs_counts"),
        ({"issues": {}}, "ck_menu_sync_runs_issues"),
    ],
)
async def test_checks_reject_invalid_rows(db_session: AsyncSession, values: dict[str, Any], constraint: str) -> None:
    tenant = await create_tenant(db_session)
    await expect_insert_violation(db_session, constraint, _run(tenant.id, **values))


async def test_valid_rows_accepted_with_defaults(db_session: AsyncSession) -> None:
    tenant = await create_tenant(db_session)
    rejected_without_hash = _run(tenant.id, status="rejected", snapshot_hash=None, source_ref="m" * 255)
    db_session.add_all([_run(tenant.id), rejected_without_hash])
    await db_session.flush()
    [row] = await db_session.execute(
        select(MenuSyncRun.counts, MenuSyncRun.issues, MenuSyncRun.created_at).where(
            MenuSyncRun.tenant_id == tenant.id, MenuSyncRun.id == rejected_without_hash.id
        )
    )
    assert (row.counts, row.issues) == ({}, [])
    assert row.created_at is not None
