"""Защиты фикстур db (ADR-7.11) без PostgreSQL: только TEST_DATABASE_URL, имя *_test,
skip локально и ошибка в CI. Значение строки подключения в сообщения не попадает."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.db import conftest as db_conftest

GOOD = "postgresql+asyncpg://u:pw-secret@localhost:5432/ai_waiter_test"


@pytest.fixture
def no_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """Нет TEST_DATABASE_URL ни в окружении, ни в корневом .env; DATABASE_URL задан (и не должен читаться)."""
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/ai_waiter_test")
    monkeypatch.setattr(db_conftest, "REPO_ROOT", tmp_path)
    return monkeypatch


def test_url_from_environment(no_env: pytest.MonkeyPatch) -> None:
    no_env.setenv("TEST_DATABASE_URL", GOOD)
    assert db_conftest.read_test_database_url() == GOOD


def test_url_from_root_dotenv(no_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"DATABASE_URL=x\nTEST_DATABASE_URL={GOOD}\n", encoding="utf-8")
    assert db_conftest.read_test_database_url() == GOOD


def test_database_url_is_never_used(no_env: pytest.MonkeyPatch) -> None:
    assert db_conftest.read_test_database_url() is None


def test_missing_url_skips_locally(no_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(pytest.skip.Exception, match="TEST_DATABASE_URL не задан"):
        db_conftest.require_test_database_url()


def test_missing_url_fails_in_ci(no_env: pytest.MonkeyPatch) -> None:
    no_env.setenv("CI", "true")
    with pytest.raises(pytest.fail.Exception, match="в CI тесты с PostgreSQL"):
        db_conftest.require_test_database_url()


def test_non_test_database_exits(no_env: pytest.MonkeyPatch) -> None:
    no_env.setenv("TEST_DATABASE_URL", "postgresql+asyncpg://u:pw-secret@localhost/ai_waiter")
    with pytest.raises(pytest.exit.Exception, match="_test") as exc_info:
        db_conftest.require_test_database_url()
    assert "pw-secret" not in str(exc_info.value)


def test_good_url_is_returned(no_env: pytest.MonkeyPatch) -> None:
    no_env.setenv("TEST_DATABASE_URL", GOOD)
    assert db_conftest.require_test_database_url() == GOOD


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (GOOD, None),
        ("postgresql+asyncpg://u:pw-secret@localhost/ai_waiter", "оканчиваться на _test"),
        ("postgresql+asyncpg://u:pw-secret@localhost/", "оканчиваться на _test"),
        ("postgresql://u:pw-secret@localhost/ai_waiter_test", "postgresql+asyncpg"),
        ("not a url", "некорректная строка подключения"),
    ],
)
def test_check_test_database_url(url: str, expected: str | None) -> None:
    problem = db_conftest.check_test_database_url(url)
    if expected is None:
        assert problem is None
    else:
        assert problem is not None
        assert expected in problem
        assert "pw-secret" not in problem


def test_run_in_thread_returns_value_and_reraises() -> None:
    assert db_conftest.run_in_thread(lambda: 42) == 42

    def boom() -> None:
        raise ValueError("ошибка в потоке")

    with pytest.raises(ValueError, match="ошибка в потоке"):
        db_conftest.run_in_thread(boom)


def test_alembic_config_has_url_and_no_logging() -> None:
    cfg = db_conftest.alembic_config(GOOD)
    assert cfg.attributes == {"database_url": GOOD, "configure_logger": False}
    assert cfg.get_main_option("sqlalchemy.url") is None
