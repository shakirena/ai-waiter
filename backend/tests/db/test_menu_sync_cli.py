"""CLI ``python -m app.menu_sync import`` на настоящем PostgreSQL (story #66, AC-6, ADR-8.6).

AC #66: ``--dry-run`` → план без изменений БД (код 0), затем ``applied`` (код 0), затем ``unchanged``
(код 0); файл с ошибками — код 2, меню не меняется, в журнале ``rejected``; нет заведения — 1;
lock занят — 3; массовое скрытие — 2, с ``--allow-mass-hide`` — применяется.

``main`` сам открывает соединение и фиксирует транзакции, поэтому данные коммитятся: каждый тест
работает со своим заведением, а после модуля схема пересоздаётся миграциями (другим тестам эти
данные не нужны). Строка подключения — только тестовая БД (``--database-url`` и ``DATABASE_URL``).
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import make_url, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

import app.menu_sync.__main__ as cli
from app.db.ids import new_id
from app.menu_sync.service import MENU_SYNC_LOCK_NAMESPACE
from app.models.menu import Category, MenuItem, MenuItemPrice
from app.models.menu_sync import MenuSyncRun
from app.models.tenant import Tenant
from tests.db.conftest import alembic_command, reset_schema, run_in_thread

pytestmark = pytest.mark.db

BACKEND_DIR = Path(__file__).resolve().parents[2]
VALID_CSV = BACKEND_DIR / "tests" / "fixtures" / "menu" / "menu_valid.csv"
HEADER = "category_external_id,category_name,external_id,name,price_default"


@pytest.fixture(scope="module")
def cli_database(migrated_database: str) -> Iterator[str]:
    """Тестовая БД с миграциями; после модуля схема пересоздаётся (CLI фиксирует данные)."""
    yield migrated_database
    reset_schema(migrated_database)
    alembic_command(migrated_database, "upgrade", "head")


@pytest.fixture
def url(cli_database: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("APP_MODE", "single")
    monkeypatch.setenv("DATABASE_URL", cli_database)  # никогда не рабочая БД из .env
    return cli_database


def db_call[T](database_url: str, func: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Выполнить ``func(session)`` с фиксацией в отдельном потоке (вне цикла событий pytest)."""

    async def run() -> T:
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
                return await func(session)
        finally:
            await engine.dispose()

    return run_in_thread(lambda: asyncio.run(run()))


@pytest.fixture
def tenant(url: str) -> uuid.UUID:
    tenant_id = new_id()

    async def create(session: AsyncSession) -> None:
        session.add(Tenant(id=tenant_id, name="Заведение CLI"))

    db_call(url, create)
    return tenant_id


@dataclass
class MenuState:
    items: dict[str, tuple[bool, bool]]  # external_id → (is_hidden, is_available)
    categories: int
    prices: int
    runs: list[MenuSyncRun]


def menu_state(database_url: str, tenant_id: uuid.UUID) -> MenuState:
    async def load(session: AsyncSession) -> MenuState:
        items = (
            await session.execute(
                select(MenuItem.external_id, MenuItem.is_hidden, MenuItem.is_available).where(
                    MenuItem.tenant_id == tenant_id
                )
            )
        ).all()
        categories = (await session.scalars(select(Category.id).where(Category.tenant_id == tenant_id))).all()
        prices = (await session.scalars(select(MenuItemPrice.price).where(MenuItemPrice.tenant_id == tenant_id))).all()
        runs = (
            await session.scalars(
                select(MenuSyncRun).where(MenuSyncRun.tenant_id == tenant_id).order_by(MenuSyncRun.id)
            )
        ).all()
        return MenuState(
            items={row.external_id: (row.is_hidden, row.is_available) for row in items},
            categories=len(categories),
            prices=len(prices),
            runs=list(runs),
        )

    return db_call(database_url, load)


def run_cli(capsys: pytest.CaptureFixture[str], *argv: str | Path) -> tuple[int, str, str]:
    code = cli.main([str(arg) for arg in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def import_args(path: Path, tenant_id: uuid.UUID, database_url: str, *extra: str) -> list[str | Path]:
    return ["import", path, "--tenant", str(tenant_id), "--database-url", database_url, *extra]


def write_csv(directory: Path, name: str, rows: list[str], header: str = HEADER) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(("\n".join([header, *rows]) + "\n").encode("utf-8"))
    return path


def items_csv(directory: Path, name: str, ids: list[str]) -> Path:
    return write_csv(directory, name, [f"1,Cat,{item_id},Блюдо {item_id},5.00" for item_id in ids])


# ---------------------------------------------------------------- AC #66


def test_ac66_dry_run_then_applied_then_unchanged(
    url: str, tenant: uuid.UUID, capsys: pytest.CaptureFixture[str]
) -> None:
    args = import_args(VALID_CSV, tenant, url)

    code, out, err = run_cli(capsys, *args, "--dry-run")
    assert code == cli.EXIT_OK, err
    assert "Статус: applied — меню будет применено" in out
    assert "Позиции: создано 9, изменено 0, скрыто 0, возвращено 0, без изменений 0" in out
    assert "Категории: создано 3" in out
    assert "Запись журнала" not in out
    state = menu_state(url, tenant)
    assert (state.items, state.categories, state.prices, state.runs) == ({}, 0, 0, [])

    code, out, err = run_cli(capsys, *args)
    assert code == cli.EXIT_OK, err
    assert "Статус: applied — меню применено" in out
    state = menu_state(url, tenant)
    assert len(state.items) == 9
    assert state.categories == 3
    assert state.prices == 15
    assert state.items["009"] == (False, False)  # is_available = 0
    [applied] = state.runs
    assert (applied.status, applied.source, applied.source_ref) == ("applied", "file", "menu_valid.csv")
    assert f"Хеш снимка: {applied.snapshot_hash}" in out
    assert f"Запись журнала: {applied.id}" in out

    code, out, err = run_cli(capsys, *args)
    assert code == cli.EXIT_OK, err
    assert "Статус: unchanged" in out
    state = menu_state(url, tenant)
    assert [run.status for run in state.runs] == ["applied", "unchanged"]
    assert state.runs[1].snapshot_hash == applied.snapshot_hash

    code, out, _ = run_cli(capsys, *args, "--force", "--json")
    assert code == cli.EXIT_OK
    assert '"status": "applied"' in out
    assert [run.status for run in menu_state(url, tenant).runs] == ["applied", "unchanged", "applied"]


def test_parse_errors_are_rejected_and_journaled(
    url: str, tenant: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_cli(capsys, *import_args(VALID_CSV, tenant, url))[0] == cli.EXIT_OK
    before = menu_state(url, tenant)
    bad = write_csv(tmp_path / "Users" / "operator", "bad.csv", ["1,Cat,a1,X,abc", "1,Cat,a1,Y,-1"])

    code, out, _ = run_cli(capsys, *import_args(bad, tenant, url))
    assert code == cli.EXIT_INVALID_DATA
    assert "Статус: rejected" in out
    after = menu_state(url, tenant)
    assert after.items == before.items
    assert after.prices == before.prices
    rejected = after.runs[-1]
    assert (rejected.status, rejected.source_ref, rejected.snapshot_hash) == ("rejected", "bad.csv", None)
    assert [(issue["code"], issue["row"]) for issue in rejected.issues] == [
        ("invalid_money", 2),
        ("negative_price", 3),
        ("duplicate_external_id", 3),
    ]
    assert rejected.started_at <= rejected.finished_at
    assert f"Запись журнала: {rejected.id}" in out

    # --dry-run с ошибками не журналируется.
    assert run_cli(capsys, *import_args(bad, tenant, url, "--dry-run"))[0] == cli.EXIT_INVALID_DATA
    assert len(menu_state(url, tenant).runs) == len(after.runs)


def test_snapshot_errors_get_file_rows_in_journal(
    url: str, tenant: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Чужая валюта — ошибка ``check_snapshot`` при применении; в журнале — строка и колонка файла."""
    path = write_csv(tmp_path, "usd.csv", ["1,Cat,a1,X,5.00,AZN", "1,Cat,a2,Y,6.00,USD"], header=f"{HEADER},currency")

    code, out, _ = run_cli(capsys, *import_args(path, tenant, url, "--dry-run"))
    assert code == cli.EXIT_INVALID_DATA
    assert "(строка 3, колонка currency)" in out
    assert menu_state(url, tenant).runs == []

    code, out, _ = run_cli(capsys, *import_args(path, tenant, url))
    assert code == cli.EXIT_INVALID_DATA
    state = menu_state(url, tenant)
    assert state.items == {}
    [rejected] = state.runs
    assert rejected.status == "rejected"
    assert [(issue["code"], issue["row"], issue["column"]) for issue in rejected.issues] == [
        ("currency_mismatch", 3, "currency")
    ]


def test_truncated_issues_are_counted_in_journal(
    url: str, tenant: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(tmp_path, "many.csv", [f"1,Cat,id{n},X,bad" for n in range(150)])
    code, out, _ = run_cli(capsys, *import_args(path, tenant, url))
    assert code == cli.EXIT_INVALID_DATA
    assert "не показано ещё 50" in out
    [rejected] = menu_state(url, tenant).runs
    assert len(rejected.issues) == 100
    assert rejected.counts == {"issues_truncated": 50}


def test_missing_availability_column_keeps_availability(
    url: str, tenant: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Решение пользователя: нет колонки ``is_available`` — наличие позиций не трогается."""
    first = write_csv(
        tmp_path, "first.csv", ["1,Cat,a1,X,5.00,0", "1,Cat,a2,Y,6.00,1"], header=f"{HEADER},is_available"
    )
    assert run_cli(capsys, *import_args(first, tenant, url))[0] == cli.EXIT_OK
    second = write_csv(tmp_path, "second.csv", ["1,Cat,a1,X,5.50", "1,Cat,a2,Y,6.00"])
    code, out, _ = run_cli(capsys, *import_args(second, tenant, url))
    assert code == cli.EXIT_OK
    assert "Колонки is_available нет: наличие позиций не меняется." in out
    assert "Наличие изменено у позиций: 0" in out
    assert menu_state(url, tenant).items == {"a1": (False, False), "a2": (False, True)}


def test_mass_hide_needs_explicit_permission(
    url: str, tenant: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    full = items_csv(tmp_path, "full.csv", [f"i{n}" for n in range(10)])
    assert run_cli(capsys, *import_args(full, tenant, url))[0] == cli.EXIT_OK
    small = items_csv(tmp_path, "small.csv", ["other"])

    code, out, _ = run_cli(capsys, *import_args(small, tenant, url))
    assert code == cli.EXIT_INVALID_DATA
    assert "--allow-mass-hide" in out
    state = menu_state(url, tenant)
    assert all(not hidden for hidden, _ in state.items.values())
    assert state.runs[-1].status == "rejected"
    assert state.runs[-1].issues[0]["code"] == "mass_hide"

    code, out, _ = run_cli(capsys, *import_args(small, tenant, url, "--allow-mass-hide"))
    assert code == cli.EXIT_OK
    assert "скрыто 10" in out
    items = menu_state(url, tenant).items
    assert sum(hidden for hidden, _ in items.values()) == 10
    assert items["other"] == (False, True)


def test_empty_file_is_always_rejected(
    url: str, tenant: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_cli(capsys, *import_args(VALID_CSV, tenant, url))[0] == cli.EXIT_OK
    empty = write_csv(tmp_path, "empty.csv", [])
    code, _, _ = run_cli(capsys, *import_args(empty, tenant, url, "--allow-mass-hide"))
    assert code == cli.EXIT_INVALID_DATA
    state = menu_state(url, tenant)
    assert not any(hidden for hidden, _ in state.items.values())
    assert state.runs[-1].status == "rejected"


# ---------------------------------------------------------------- окружение и lock


def test_unknown_tenant_is_exit_1(url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = new_id()
    code, out, err = run_cli(capsys, *import_args(VALID_CSV, missing, url))
    assert code == cli.EXIT_ERROR
    assert out == ""
    assert f"Заведение {missing} не найдено" in err

    bad = write_csv(tmp_path, "bad.csv", ["1,Cat,a1,X,abc"])
    code, _, err = run_cli(capsys, *import_args(bad, missing, url))
    assert code == cli.EXIT_ERROR
    assert "не найдено" in err

    async def runs(session: AsyncSession) -> list[Any]:
        return list((await session.scalars(select(MenuSyncRun.id).where(MenuSyncRun.tenant_id == missing))).all())

    assert db_call(url, runs) == []


@contextmanager
def held_menu_lock(database_url: str, tenant_id: uuid.UUID) -> Iterator[None]:
    """Держать advisory lock синхронизации меню заведения в другом соединении (как параллельный импорт)."""
    ready = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    async def hold() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(:namespace, hashtext(CAST(:tenant_id AS text)))"),
                    {"namespace": MENU_SYNC_LOCK_NAMESPACE, "tenant_id": str(tenant_id)},
                )
                ready.set()
                await asyncio.to_thread(release.wait, 60)
        finally:
            await engine.dispose()

    def target() -> None:
        try:
            asyncio.run(hold())
        except BaseException as exc:  # передаётся в тест
            errors.append(exc)
            ready.set()

    thread = threading.Thread(target=target, name="menu-lock")
    thread.start()
    try:
        assert ready.wait(30)
        if errors:
            raise errors[0]
        yield
    finally:
        release.set()
        thread.join(30)


def test_busy_lock_is_exit_3(url: str, tenant: uuid.UUID, capsys: pytest.CaptureFixture[str]) -> None:
    with held_menu_lock(url, tenant):
        code, out, err = run_cli(capsys, *import_args(VALID_CSV, tenant, url))
        assert code == cli.EXIT_BUSY
        code_dry, _, _ = run_cli(capsys, *import_args(VALID_CSV, tenant, url, "--dry-run"))
        assert code_dry == cli.EXIT_BUSY
    assert out == ""
    assert "уже идёт" in err
    state = menu_state(url, tenant)
    assert (state.items, state.runs) == ({}, [])
    # Lock освобождён — импорт проходит.
    assert run_cli(capsys, *import_args(VALID_CSV, tenant, url))[0] == cli.EXIT_OK


def test_wrong_password_is_not_shown(url: str, tenant: uuid.UUID, capsys: pytest.CaptureFixture[str]) -> None:
    wrong = "Wrong-Menu-Pa55-q7"
    bad_url = make_url(url).set(password=wrong).render_as_string(hide_password=False)
    code, out, err = run_cli(capsys, *import_args(VALID_CSV, tenant, bad_url))
    assert code == cli.EXIT_ERROR
    assert out == ""
    assert wrong not in err
    assert "Не удалось выполнить импорт меню" in err
