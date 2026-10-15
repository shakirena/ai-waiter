"""CLI ``python -m app.menu_sync`` (#66, ADR-8.6) без PostgreSQL.

``check`` работает без БД и ``.env``; у ``import`` сервис (``apply_menu_snapshot``,
``record_rejected_run``) подменяется: проверяются аргументы, коды выхода 0/1/2/3, текст и ``--json``.
Применение к настоящей БД — ``tests/db/test_menu_sync_cli.py``.
"""

from __future__ import annotations

import io
import json
import os
import runpy
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

import app.menu_sync.__main__ as cli
from app.menu_sync.report import EntityCounts, IssueCode, MenuSyncReport, PriceCounts, Severity, SyncIssue
from app.menu_sync.service import MenuSyncBusyError, TenantNotFoundError
from app.models.enums import MenuSyncSource, MenuSyncStatus

BACKEND_DIR = Path(__file__).resolve().parents[1]
VALID_CSV = BACKEND_DIR / "tests" / "fixtures" / "menu" / "menu_valid.csv"
TENANT = "0190aaaa-0000-7000-8000-000000000001"
PASSWORD = "Cli-Pa55word-xyz"
FAKE_URL = f"postgresql+asyncpg://dev:{PASSWORD}@db.invalid/menu_dev"
HASH = "a" * 64

HEADER = "category_external_id,category_name,external_id,name,price_default"


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


@pytest.fixture
def bad_csv(tmp_path: Path) -> Path:
    """Две ошибки цены и повтор ``external_id``."""
    return write(tmp_path, "bad.csv", f"{HEADER}\n1,Cat,a1,X,abc\n1,Cat,a1,Y,-1\n")


@pytest.fixture
def plain_csv(tmp_path: Path) -> Path:
    """Корректный файл без колонки ``is_available`` и с нулевой ценой у ``a2`` (строка 3)."""
    return write(tmp_path, "plain.csv", f"{HEADER}\n1,Cat,a1,X,1.50\n1,Cat,a2,Y,0\n")


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Окружение для ``import``: строка подключения к несуществующему хосту (в сеть не ходим)."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("APP_MODE", "single")
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)


def run(capsys: pytest.CaptureFixture[str], *argv: str | Path) -> tuple[int, str, str]:
    code = cli.main([str(arg) for arg in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def applied_report(**values: Any) -> MenuSyncReport:
    report = MenuSyncReport(
        status=MenuSyncStatus.APPLIED,
        dry_run=False,
        snapshot_hash=HASH,
        categories=EntityCounts(created=1),
        items=EntityCounts(created=1, updated=2, hidden=3, restored=4, unchanged=5),
        prices=PriceCounts(created=6, updated=7, deleted=8),
        availability_changed=9,
        run_id=uuid.UUID("0190aaaa-0000-7000-8000-0000000000ff"),
    )
    for key, value in values.items():
        setattr(report, key, value)
    return report


class FakeService:
    """Подмена ``apply_menu_snapshot``/``record_rejected_run``/``_ensure_tenant`` с записью вызовов."""

    def __init__(self, result: MenuSyncReport | BaseException) -> None:
        self.result = result
        self.apply_calls: list[dict[str, Any]] = []
        self.rejected_calls: list[dict[str, Any]] = []
        self.ensured: list[uuid.UUID] = []
        self.ensure_error: BaseException | None = None

    async def apply(self, session: Any, **kwargs: Any) -> MenuSyncReport:
        self.apply_calls.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        self.result.dry_run = kwargs["dry_run"]
        return self.result

    async def record_rejected(self, session: Any, **kwargs: Any) -> uuid.UUID:
        self.rejected_calls.append(kwargs)
        return uuid.UUID("0190aaaa-0000-7000-8000-0000000000ee")

    async def ensure(self, session: Any, tenant_id: uuid.UUID) -> None:
        self.ensured.append(tenant_id)
        if self.ensure_error is not None:
            raise self.ensure_error


@pytest.fixture
def fake_service(monkeypatch: pytest.MonkeyPatch, env: None) -> Callable[[MenuSyncReport | BaseException], FakeService]:
    def install(result: MenuSyncReport | BaseException) -> FakeService:
        fake = FakeService(result)
        monkeypatch.setattr(cli, "apply_menu_snapshot", fake.apply)
        monkeypatch.setattr(cli, "record_rejected_run", fake.record_rejected)
        monkeypatch.setattr(cli, "_ensure_tenant", fake.ensure)
        return fake

    return install


# ---------------------------------------------------------------- аргументы


def test_help_is_exit_0(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "--help")
    assert code == cli.EXIT_OK
    assert "check" in out
    assert "import" in out
    assert "Коды выхода" in out


@pytest.mark.parametrize(
    ("argv", "fragment"),
    [
        ([], "ошибка в аргументах"),
        (["unknown"], "ошибка в аргументах"),
        (["check"], "FILE"),
        (["import", "menu.csv"], "--tenant"),
        (["import", "menu.csv", "--tenant", "not-a-uuid"], "ожидается UUID заведения"),
        (["import", "menu.csv", "--tenant", "12345"], "ожидается UUID заведения"),
        (["check", "menu.csv", "--tenant", TENANT], "ошибка в аргументах"),
    ],
)
def test_argument_errors_are_exit_1(capsys: pytest.CaptureFixture[str], argv: list[str], fragment: str) -> None:
    """Ошибка в аргументах — 1 (окружение/запуск), а не 2 argparse: 2 значит «ошибки в данных файла»."""
    code, out, err = run(capsys, *argv)
    assert code == cli.EXIT_ERROR
    assert out == ""
    assert fragment in err


def test_tenant_uuid_accepts_spaces_and_upper_case() -> None:
    args = cli.build_parser().parse_args(["import", "m.csv", "--tenant", f" {TENANT.upper()} "])
    assert args.tenant == uuid.UUID(TENANT)
    assert (args.dry_run, args.force, args.allow_mass_hide, args.json) == (False, False, False, False)
    assert (args.sheet, args.database_url) == (None, None)


def test_all_import_options_are_parsed() -> None:
    args = cli.build_parser().parse_args(
        [
            "import",
            "m.xlsx",
            "--tenant",
            TENANT,
            "--dry-run",
            "--force",
            "--allow-mass-hide",
            "--sheet",
            "Menu",
            "--database-url",
            FAKE_URL,
            "--json",
        ]
    )
    assert (args.command, args.file, args.sheet, args.database_url) == ("import", "m.xlsx", "Menu", FAKE_URL)
    assert args.dry_run and args.force and args.allow_mass_hide and args.json
    assert args.handler is cli.run_import


def test_exit_codes_are_stable() -> None:
    assert (cli.EXIT_OK, cli.EXIT_ERROR, cli.EXIT_INVALID_DATA, cli.EXIT_BUSY) == (0, 1, 2, 3)


# ---------------------------------------------------------------- check


def test_check_valid_csv_without_database(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``check`` не читает конфигурацию: работает без DATABASE_URL."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "_load_settings", lambda url: pytest.fail("check не должен читать настройки"))
    code, out, err = run(capsys, "check", VALID_CSV)
    assert code == cli.EXIT_OK
    assert err == ""
    assert "Файл: menu_valid.csv (CSV, строк данных: 9)" in out
    assert "Категорий: 3, позиций: 9" in out
    assert "Проверка пройдена" in out
    assert "is_available нет" not in out


def test_check_without_availability_column_says_it_is_kept(plain_csv: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "check", plain_csv)
    assert code == cli.EXIT_OK
    assert "Колонки is_available нет: наличие позиций не меняется." in out


def test_check_errors_are_exit_2_with_rows(bad_csv: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "check", bad_csv)
    assert code == cli.EXIT_INVALID_DATA
    assert err == ""
    assert "Проблемы: ошибок 3, предупреждений 0" in out
    assert "ошибка (строка 2, колонка price_default)" in out
    assert "[значение: «abc»]" in out
    assert "ошибка (строка 3, колонка external_id): повтор external_id позиции (строка 2)" in out
    assert "Проверка не пройдена" in out
    assert "Категорий" not in out


def test_check_json(bad_csv: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "check", bad_csv, "--json")
    assert code == cli.EXIT_INVALID_DATA
    assert out.isascii()
    data = json.loads(out)
    assert data["command"] == "check"
    assert (data["file"], data["format"], data["rows"], data["ok"]) == ("bad.csv", "csv", 2, False)
    assert (data["categories"], data["items"], data["issues_truncated"]) == (None, None, 0)
    assert [issue["code"] for issue in data["issues"]] == ["invalid_money", "negative_price", "duplicate_external_id"]
    assert data["issues"][0]["row"] == 2


def test_check_json_valid(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "check", VALID_CSV, "--json")
    assert code == cli.EXIT_OK
    data = json.loads(out)
    assert (data["ok"], data["categories"], data["items"], data["has_availability"]) == (True, 3, 9, True)
    assert data["issues"] == []


def test_check_xlsx_with_sheet(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    book = Workbook()
    book.active.title = "Notes"
    sheet = book.create_sheet("Prices")
    sheet.append(HEADER.split(","))
    sheet.append(["1", "Cat", "a1", "X", 4.5])
    path = tmp_path / "menu.xlsx"
    book.save(path)

    code, out, _ = run(capsys, "check", path, "--sheet", "prices")
    assert code == cli.EXIT_OK, out
    assert "Файл: menu.xlsx (XLSX, строк данных: 1)" in out

    code, out, _ = run(capsys, "check", path, "--sheet", "missing")
    assert code == cli.EXIT_INVALID_DATA
    assert "missing" in out


def test_check_unsupported_format_is_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, "menu.txt", f"{HEADER}\n")
    code, out, _ = run(capsys, "check", path)
    assert code == cli.EXIT_INVALID_DATA
    assert "(формат не распознан, строк данных: 0)" in out
    assert ".csv (UTF-8) и .xlsx" in out


def test_check_too_many_issues_reports_truncated(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = "".join(f"1,Cat,id{n},X,bad\n" for n in range(150))
    path = write(tmp_path, "many.csv", f"{HEADER}\n{rows}")
    code, out, _ = run(capsys, "check", path)
    assert code == cli.EXIT_INVALID_DATA
    assert "Проблемы: ошибок 100, предупреждений 0, не показано ещё 50" in out


def test_check_missing_file_is_exit_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "check", tmp_path / "absent.csv")
    assert code == cli.EXIT_ERROR
    assert out == ""
    assert "Файл не найден:" in err
    assert "absent.csv" in err


def test_check_directory_is_exit_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "check", tmp_path)
    assert code == cli.EXIT_ERROR
    assert out == ""
    assert "Указан каталог, а не файл" in err


@pytest.mark.parametrize(
    ("error", "expected"),
    [(PermissionError(13, "Отказано в доступе"), "Отказано в доступе"), (OSError(), "OSError")],
)
def test_check_unreadable_file_is_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error: OSError, expected: str
) -> None:
    def fail(path: Path, *, sheet: str | None = None) -> None:
        raise error

    monkeypatch.setattr(cli, "read_menu_file", fail)
    code, _, err = run(capsys, "check", VALID_CSV)
    assert code == cli.EXIT_ERROR
    assert f"Не удалось прочитать файл {VALID_CSV}: {expected}" in err


def test_control_characters_in_path_are_escaped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(capsys, "check", str(tmp_path / "evil\x1b[31m.csv"))
    assert code == cli.EXIT_ERROR
    assert "\x1b" not in err
    assert "\\x1b[31m" in err


# ---------------------------------------------------------------- import: без БД


def test_import_dry_run_with_parse_errors_does_not_need_database(
    monkeypatch: pytest.MonkeyPatch, bad_csv: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "_load_settings", lambda url: pytest.fail("база не нужна"))
    code, out, err = run(capsys, "import", bad_csv, "--tenant", TENANT, "--dry-run")
    assert code == cli.EXIT_INVALID_DATA
    assert err == ""
    assert f"Заведение: {TENANT}" in out
    assert "Режим: пробный прогон (--dry-run), в базу ничего не записано" in out
    assert "Статус: rejected — отклонено: ошибки в данных" in out
    assert "Хеш снимка" not in out
    assert "Запись журнала" not in out


def test_import_missing_file_is_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    fake = fake_service(applied_report())
    code, out, err = run(capsys, "import", tmp_path / "absent.csv", "--tenant", TENANT)
    assert code == cli.EXIT_ERROR
    assert out == ""
    assert "Файл не найден" in err
    assert fake.apply_calls == []


def test_import_config_error_is_exit_1_without_value(capsys: pytest.CaptureFixture[str]) -> None:
    url = f"mysql://dev:{PASSWORD}@db.invalid/menu"
    code, out, err = run(capsys, "import", VALID_CSV, "--tenant", TENANT, "--database-url", url)
    assert code == cli.EXIT_ERROR
    assert out == ""
    assert "Ошибка конфигурации" in err
    assert PASSWORD not in err


def test_import_without_database_url_is_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_settings(url: str | None) -> Any:
        return cli.Settings(_env_file=None)  # type: ignore[call-arg]

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "_load_settings", no_settings)
    code, _, err = run(capsys, "import", VALID_CSV, "--tenant", TENANT)
    assert code == cli.EXIT_ERROR
    assert "DATABASE_URL" in err


def test_load_settings_prefers_argument(env: None) -> None:
    other = "postgresql+asyncpg://other:x@db.invalid/other"
    assert cli._load_settings(other).database_url.get_secret_value() == other
    assert cli._load_settings(None).database_url.get_secret_value() == FAKE_URL


# ---------------------------------------------------------------- import: подменённый сервис


def test_import_applied_prints_counts(
    capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    fake = fake_service(applied_report())
    code, out, err = run(capsys, "import", VALID_CSV, "--tenant", TENANT)
    assert code == cli.EXIT_OK
    assert err == ""
    call = fake.apply_calls[0]
    assert call["tenant_id"] == uuid.UUID(TENANT)
    assert call["source"] is MenuSyncSource.FILE
    assert call["source_ref"] == "menu_valid.csv"
    assert (call["dry_run"], call["force"], call["allow_mass_hide"]) == (False, False, False)
    assert len(call["snapshot"].items) == 9
    assert "Статус: applied — меню применено" in out
    assert "Категории: создано 1, изменено 0, скрыто 0, возвращено 0, без изменений 0" in out
    assert "Позиции: создано 1, изменено 2, скрыто 3, возвращено 4, без изменений 5" in out
    assert "Цены: добавлено 6, изменено 7, удалено 8" in out
    assert "Наличие изменено у позиций: 9" in out
    assert f"Хеш снимка: {HASH}" in out
    assert "Запись журнала: 0190aaaa-0000-7000-8000-0000000000ff" in out
    assert "пробный прогон" not in out
    assert fake.rejected_calls == []


def test_import_passes_flags_and_dry_run_label(
    capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    fake = fake_service(applied_report(run_id=None))
    code, out, _ = run(capsys, "import", VALID_CSV, "--tenant", TENANT, "--dry-run", "--force", "--allow-mass-hide")
    assert code == cli.EXIT_OK
    call = fake.apply_calls[0]
    assert (call["dry_run"], call["force"], call["allow_mass_hide"]) == (True, True, True)
    assert "Режим: пробный прогон (--dry-run)" in out
    assert "Статус: applied — меню будет применено" in out
    assert "Запись журнала" not in out


def test_import_unchanged_is_exit_0_without_counts(
    capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    fake_service(applied_report(status=MenuSyncStatus.UNCHANGED, items=EntityCounts()))
    code, out, _ = run(capsys, "import", VALID_CSV, "--tenant", TENANT)
    assert code == cli.EXIT_OK
    assert "Статус: unchanged — без изменений" in out
    assert "Позиции:" not in out
    assert f"Хеш снимка: {HASH}" in out


def test_import_warnings_get_file_rows(
    plain_csv: Path, capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    """``zero_price`` из ``check_snapshot`` приходит без строки — CLI добавляет строку и колонку файла."""
    warning = SyncIssue(
        IssueCode.ZERO_PRICE, "цена 0", severity=Severity.WARNING, external_id="a2", column="prices.default"
    )
    unknown = SyncIssue(IssueCode.ZERO_PRICE, "цена 0", severity=Severity.WARNING, external_id="zz")
    fake_service(applied_report(issues=[unknown, warning]))
    code, out, _ = run(capsys, "import", plain_csv, "--tenant", TENANT)
    assert code == cli.EXIT_OK
    assert "Проблемы: ошибок 0, предупреждений 2" in out
    assert "  предупреждение (строка 3, колонка price_default): цена 0" in out
    assert "  предупреждение (позиция zz): цена 0" in out
    assert "Колонки is_available нет" in out


def test_import_rejected_is_journaled_with_rows_and_exit_2(
    plain_csv: Path, capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    error = SyncIssue(IssueCode.CURRENCY_MISMATCH, "валюта USD", external_id="a1", column="currency")
    rejected = MenuSyncReport(
        status=MenuSyncStatus.REJECTED, dry_run=False, snapshot_hash=HASH, issues=[error], issues_truncated=4
    )
    fake = fake_service(rejected)
    code, out, _ = run(capsys, "import", plain_csv, "--tenant", TENANT)
    assert code == cli.EXIT_INVALID_DATA
    assert fake.ensured == [uuid.UUID(TENANT)]
    call = fake.rejected_calls[0]
    assert call["tenant_id"] == uuid.UUID(TENANT)
    assert (call["source"], call["source_ref"], call["snapshot_hash"]) == (MenuSyncSource.FILE, "plain.csv", HASH)
    assert call["issues_truncated"] == 4
    assert call["started_at"].tzinfo is not None
    assert [(issue.row, issue.column) for issue in call["issues"]] == [(2, "currency")]
    assert "Статус: rejected — отклонено: ошибки в данных, ничего не записано" in out
    assert "Запись журнала: 0190aaaa-0000-7000-8000-0000000000ee" in out
    assert "  ошибка (строка 2, колонка currency): валюта USD" in out
    assert "не показано ещё 4" in out


def test_import_rejected_dry_run_is_not_journaled(
    plain_csv: Path, capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    rejected = MenuSyncReport(status=MenuSyncStatus.REJECTED, dry_run=True, snapshot_hash=HASH)
    fake = fake_service(rejected)
    code, out, _ = run(capsys, "import", plain_csv, "--tenant", TENANT, "--dry-run")
    assert code == cli.EXIT_INVALID_DATA
    assert fake.rejected_calls == []
    assert "Статус: rejected — отклонено: ошибки в данных" in out


def test_import_parse_errors_are_journaled_without_apply(
    bad_csv: Path, capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    fake = fake_service(applied_report())
    code, out, _ = run(capsys, "import", bad_csv, "--tenant", TENANT)
    assert code == cli.EXIT_INVALID_DATA
    assert fake.apply_calls == []
    call = fake.rejected_calls[0]
    assert call["source_ref"] == "bad.csv"
    assert call["snapshot_hash"] is None
    assert [issue.code for issue in call["issues"]] == [
        IssueCode.INVALID_MONEY,
        IssueCode.NEGATIVE_PRICE,
        IssueCode.DUPLICATE_EXTERNAL_ID,
    ]
    assert "Запись журнала: 0190aaaa-0000-7000-8000-0000000000ee" in out


def test_import_json(capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]) -> None:
    fake_service(applied_report())
    code, out, _ = run(capsys, "import", VALID_CSV, "--tenant", TENANT, "--json")
    assert code == cli.EXIT_OK
    data = json.loads(out)
    assert data["command"] == "import"
    assert (data["file"], data["format"], data["rows"], data["has_availability"]) == ("menu_valid.csv", "csv", 9, True)
    assert data["tenant_id"] == TENANT
    assert (data["status"], data["dry_run"], data["snapshot_hash"]) == ("applied", False, HASH)
    assert data["counts"]["items"] == {"created": 1, "updated": 2, "hidden": 3, "restored": 4, "unchanged": 5}
    assert data["run_id"] == "0190aaaa-0000-7000-8000-0000000000ff"


def test_import_json_parse_errors_dry_run(bad_csv: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "import", bad_csv, "--tenant", TENANT, "--dry-run", "--json")
    assert code == cli.EXIT_INVALID_DATA
    data = json.loads(out)
    assert (data["status"], data["dry_run"], data["run_id"], data["snapshot_hash"]) == ("rejected", True, None, None)
    assert len(data["issues"]) == 3


def test_import_busy_is_exit_3(capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]) -> None:
    fake_service(MenuSyncBusyError("занято"))
    code, out, err = run(capsys, "import", VALID_CSV, "--tenant", TENANT)
    assert code == cli.EXIT_BUSY
    assert out == ""
    assert "Синхронизация меню этого заведения уже идёт" in err


def test_import_unknown_tenant_is_exit_1(
    capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    fake_service(TenantNotFoundError("нет"))
    code, out, err = run(capsys, "import", VALID_CSV, "--tenant", TENANT)
    assert code == cli.EXIT_ERROR
    assert out == ""
    assert f"Заведение {TENANT} не найдено" in err


def test_import_parse_errors_for_unknown_tenant_is_exit_1(
    bad_csv: Path, capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    fake = fake_service(applied_report())
    fake.ensure_error = TenantNotFoundError("нет")
    code, out, err = run(capsys, "import", bad_csv, "--tenant", TENANT)
    assert code == cli.EXIT_ERROR
    assert out == ""
    assert fake.rejected_calls == []
    assert "не найдено" in err


def test_import_database_error_hides_password(
    capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    fake_service(ConnectionRefusedError(f"connect to dev:{PASSWORD}@db.invalid failed"))
    code, out, err = run(capsys, "import", VALID_CSV, "--tenant", TENANT)
    assert code == cli.EXIT_ERROR
    assert out == ""
    assert PASSWORD not in err
    assert "Не удалось выполнить импорт меню: ConnectionRefusedError" in err
    assert "***" in err
    assert "alembic upgrade head" in err


def test_import_is_allowed_in_prod(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://menu.example.com")
    fake_service(applied_report())
    code, _, _ = run(capsys, "import", VALID_CSV, "--tenant", TENANT)
    assert code == cli.EXIT_OK


def test_output_never_contains_database_url(
    capsys: pytest.CaptureFixture[str], fake_service: Callable[..., FakeService]
) -> None:
    fake_service(applied_report())
    for extra in ([], ["--json"]):
        _, out, err = run(capsys, "import", VALID_CSV, "--tenant", TENANT, "--database-url", FAKE_URL, *extra)
        assert PASSWORD not in out + err
        assert "db.invalid" not in out + err


# ---------------------------------------------------------------- вывод и точка входа


def test_tolerant_output_reconfigures_text_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="cp1251")
    stderr = io.StringIO()  # без reconfigure — пропускается
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    cli._tolerant_output()
    stdout.write("Салат ı ə")
    stdout.flush()
    assert raw.getvalue().decode("cp1251") == "Салат \\u0131 \\u0259"


def test_module_entry_point_in_subprocess() -> None:
    """Настоящий ``python -m app.menu_sync check``: код выхода процесса и русский текст."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(  # noqa: S603 — фиксированные аргументы, без оболочки
        [sys.executable, "-m", "app.menu_sync", "check", str(VALID_CSV)],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Проверка пройдена" in result.stdout


@pytest.mark.filterwarnings("ignore:.*found in sys.modules.*:RuntimeWarning")
def test_module_guard_raises_system_exit_with_main_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bad_csv: Path
) -> None:
    monkeypatch.setattr(sys, "argv", ["python -m app.menu_sync", "check", str(bad_csv)])
    with pytest.raises(SystemExit) as info:
        runpy.run_module("app.menu_sync", run_name="__main__", alter_sys=True)
    assert info.value.code == cli.EXIT_INVALID_DATA
    assert "Проверка не пройдена" in capsys.readouterr().out
