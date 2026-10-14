"""AC-2 / NFR-7: redis, arq, apscheduler импортируются только в пакетах реализаций.

Дублирует ruff TID251 на уровне тестов, чтобы нарушение было видно и в pytest.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"

RESTRICTED: dict[str, tuple[str, ...]] = {
    "redis": ("core/scaled/",),
    "arq": ("core/scaled/",),
    "apscheduler": ("core/single/",),
    "openpyxl": ("menu_sync/files/xlsx_reader.py",),  # ADR-8.7 (#65)
}


def _imported_top_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_scanner_sees_application_code() -> None:
    """Защита от «пустого» прохода: обход действительно находит модули app/."""
    files = {path.relative_to(APP_DIR).as_posix() for path in APP_DIR.rglob("*.py")}
    assert {"core/container.py", "core/events.py", "main.py"} <= files


def test_scanner_detects_all_import_forms(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import redis.asyncio as r\n"
        "from arq.connections import RedisSettings\n"
        "def f():\n"
        "    import apscheduler\n"
        "from . import local\n",
        encoding="utf-8",
    )
    assert _imported_top_modules(sample) == {"redis", "arq", "apscheduler"}


@pytest.mark.parametrize("module", sorted(RESTRICTED))
def test_restricted_imports_only_in_implementation_packages(module: str) -> None:
    allowed = RESTRICTED[module]
    offenders = [
        rel
        for path in APP_DIR.rglob("*.py")
        if module in _imported_top_modules(path)
        and not (rel := path.relative_to(APP_DIR).as_posix()).startswith(allowed)
    ]
    assert offenders == [], f"{module} imported outside {allowed}: {offenders}"


# ---------------------------------------------------------------- app.menu_sync (#61, ADR-8.1)


def _imported_modules(path: Path) -> set[str]:
    """Полные имена импортируемых модулей; ``from app import api`` даёт и ``app``, и ``app.api``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _imports_any(path: Path, prefixes: tuple[str, ...]) -> bool:
    return any(name == p or name.startswith(f"{p}.") for name in _imported_modules(path) for p in prefixes)


def test_full_name_scanner(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("import fastapi.routing\nfrom app import api\nfrom app.apis import x\n", encoding="utf-8")
    assert _imports_any(sample, ("fastapi",))
    assert _imports_any(sample, ("app.api",))
    other = tmp_path / "other.py"
    other.write_text("from app.apis import x\nimport fastapix\n", encoding="utf-8")
    assert not _imports_any(other, ("fastapi", "app.api"))


def test_menu_sync_does_not_import_fastapi_or_api() -> None:
    """Роутеры (#16, админка) вызывают ``app.menu_sync``, а не наоборот; деньги API — ``app.schemas``."""
    files = [*(APP_DIR / "menu_sync").rglob("*.py"), *(APP_DIR / "schemas").rglob("*.py")]
    assert any(path.name == "snapshot.py" for path in files)
    offenders = [path.relative_to(APP_DIR).as_posix() for path in files if _imports_any(path, ("fastapi", "app.api"))]
    assert offenders == []


def test_core_does_not_import_menu_sync() -> None:
    offenders = [
        path.relative_to(APP_DIR).as_posix()
        for path in (APP_DIR / "core").rglob("*.py")
        if _imports_any(path, ("app.menu_sync",))
    ]
    assert offenders == []


def test_menu_sync_files_do_not_import_database() -> None:
    """Файловый коннектор работает без БД (DEC-011, ADR-8.2): прямых импортов SQLAlchemy, ``app.db`` и
    моделей нет; из ``app.models`` допустим только ``app.models.enums`` (перечисления и шаблоны).

    Транзитивно ``app.models.enums`` загружает пакет ``app.models`` (его ``__init__``), это не нарушение
    границы: разбор файла не обращается к ORM и сессии.
    """
    files = list((APP_DIR / "menu_sync" / "files").rglob("*.py"))
    assert {path.name for path in files} >= {"__init__.py", "format.py", "csv_reader.py"}
    offenders = {}
    for path in files:
        forbidden = sorted(
            name
            for name in _imported_modules(path)
            if _imports_any_name(name, ("sqlalchemy", "app.db", "app.models"))
            and not _imports_any_name(name, ("app.models.enums",))
        )
        if forbidden:
            offenders[path.relative_to(APP_DIR).as_posix()] = forbidden
    assert offenders == {}


def _imports_any_name(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == p or name.startswith(f"{p}.") for p in prefixes)


def test_files_boundary_scanner_detects_database_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from sqlalchemy import select\nfrom app.models.menu import MenuItem\nfrom app.models.enums import X\n",
        encoding="utf-8",
    )
    names = _imported_modules(sample)
    assert any(_imports_any_name(n, ("sqlalchemy",)) for n in names)
    models = [n for n in names if _imports_any_name(n, ("app.models",))]
    assert sorted(n for n in models if not _imports_any_name(n, ("app.models.enums",))) == [
        "app.models.menu",
        "app.models.menu.MenuItem",
    ]
