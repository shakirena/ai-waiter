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
