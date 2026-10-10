"""Alembic без БД (ADR-7.10): alembic.ini без строки подключения, офлайн-режим env.py,
шаблон ревизии с форматированием ruff, корень цепочки — будущая ревизия 0001."""

from __future__ import annotations

import configparser
import io
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import get_settings
from tests.conftest import FAKE_DATABASE_URL

BACKEND_DIR = Path(__file__).resolve().parents[1]
INI = BACKEND_DIR / "alembic.ini"


def _config(**attributes: object) -> tuple[Config, io.StringIO]:
    buffer = io.StringIO()
    cfg = Config(INI, output_buffer=buffer)
    cfg.attributes.update({"configure_logger": False, **attributes})
    return cfg, buffer


def test_ini_has_no_connection_string_and_no_timezone() -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(INI, encoding="utf-8")
    assert not parser.has_option("alembic", "sqlalchemy.url")
    assert not parser.has_option("alembic", "timezone")
    assert parser.get("alembic", "file_template") == "%%(rev)s_%%(slug)s"
    assert parser.get("post_write_hooks", "ruff_format.type") == "module"
    assert parser.get("post_write_hooks", "ruff_format.module") == "ruff"


def test_versions_chain_has_at_most_one_root_starting_at_0001() -> None:
    """Цепочка линейна; если ревизии есть, корень — 0001 (#49)."""
    script = ScriptDirectory.from_config(Config(INI))
    assert len(script.get_heads()) <= 1
    bases = script.get_bases()
    assert bases in ([], ["0001"])


def test_offline_upgrade_uses_explicit_url() -> None:
    cfg, buffer = _config(database_url=FAKE_DATABASE_URL)
    command.upgrade(cfg, "head", sql=True)
    assert "test:test" not in buffer.getvalue()


def test_offline_upgrade_falls_back_to_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Без явного URL env.py берёт DATABASE_URL из Settings (окружение или .env)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", FAKE_DATABASE_URL)
    monkeypatch.setenv("APP_MODE", "single")
    get_settings.cache_clear()
    try:
        cfg, _ = _config()
        command.upgrade(cfg, "head", sql=True)
        assert get_settings().database_url.get_secret_value() == FAKE_DATABASE_URL
    finally:
        get_settings.cache_clear()


def test_revision_template_renders_formatted_code(tmp_path: Path) -> None:
    """script.py.mako + post-write hook ruff: новая ревизия — валидный и отформатированный Python."""
    cfg, _ = _config(database_url=FAKE_DATABASE_URL)
    cfg.set_main_option("version_locations", str(tmp_path))
    command.revision(cfg, message="probe revision", rev_id="9999", version_path=str(tmp_path))
    [path] = list(tmp_path.glob("9999_*.py"))
    assert path.name == "9999_probe_revision.py"
    source = path.read_text(encoding="utf-8")
    assert 'revision: str = "9999"' in source
    compile(source, str(path), "exec")
    result = subprocess.run(  # noqa: S603 — фиксированная команда текущего интерпретатора
        [sys.executable, "-m", "ruff", "format", "--check", str(path)],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_alembic_ini_is_ascii() -> None:
    """Alembic читает ini в кодировке локали (cp1252 на Windows CI): кириллица ломает чтение."""
    INI.read_bytes().decode("ascii")
