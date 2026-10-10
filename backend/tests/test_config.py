from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import AppEnv, AppMode, ConfigError, Settings, get_settings
from tests.conftest import make_settings


def test_defaults_single_mode_on_loopback() -> None:
    s = make_settings()
    assert s.app_mode is AppMode.SINGLE
    assert s.host == "127.0.0.1"
    assert s.api_workers == 1


def test_scaled_requires_redis_url() -> None:
    with pytest.raises(ValidationError, match="REDIS_URL"):
        make_settings(app_mode="scaled")


def test_single_rejects_multiple_workers() -> None:
    with pytest.raises(ValidationError, match="single"):
        make_settings(api_workers=2)


def test_database_url_must_be_asyncpg() -> None:
    with pytest.raises(ValidationError, match="asyncpg"):
        make_settings(database_url="postgresql://u:p@db.invalid/x")


def test_prod_requires_public_base_url() -> None:
    with pytest.raises(ValidationError, match="PUBLIC_BASE_URL"):
        make_settings(app_env=AppEnv.PROD)


def test_app_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        make_settings(app_mode="cluster")


def test_secrets_not_in_repr() -> None:
    s = make_settings(
        anthropic_api_key="sk-test-secret",
        database_url="postgresql+asyncpg://u:pw-secret@db.invalid/x",
    )
    assert "sk-test-secret" not in repr(s)
    assert "pw-secret" not in repr(s)


def test_docs_disabled_in_prod_by_default() -> None:
    s = make_settings(app_env=AppEnv.PROD, public_base_url="https://menu.example.com")
    assert s.is_docs_enabled is False


def test_frontend_dist_default_is_relative_to_repo() -> None:
    s = make_settings()
    assert s.frontend_dist_path.parts[-2:] == ("frontend", "dist")


# --- #37: доработки Settings и понятные ошибки конфигурации


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[pytest.MonkeyPatch]:
    """Окружение без переменных Settings и без .env рядом: get_settings() видит только то, что задал тест."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_docs_explicit_flag_overrides_env() -> None:
    assert make_settings(docs_enabled=False).is_docs_enabled is False
    s = make_settings(app_env=AppEnv.PROD, public_base_url="https://menu.example.com", docs_enabled=True)
    assert s.is_docs_enabled is True


def test_frontend_dist_explicit_dir(tmp_path: Path) -> None:
    assert make_settings(frontend_dist_dir=tmp_path).frontend_dist_path == tmp_path


def test_single_rejects_non_loopback_host() -> None:
    with pytest.raises(ValidationError, match="loopback"):
        make_settings(host="0.0.0.0")  # noqa: S104


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_single_accepts_loopback_hosts(host: str) -> None:
    assert make_settings(host=host).host == host


def test_scaled_allows_any_host_and_workers() -> None:
    s = make_settings(
        app_mode="scaled",
        redis_url="redis://redis:6379/0",
        host="0.0.0.0",  # noqa: S104
        api_workers=4,
    )
    assert s.app_mode is AppMode.SCALED
    assert s.api_workers == 4


@pytest.mark.parametrize("url", ["https://203.0.113.10", "https://[2001:db8::1]"])
def test_public_base_url_rejects_ip_address(url: str) -> None:
    with pytest.raises(ValidationError, match="доменное имя"):
        make_settings(public_base_url=url)


def test_public_base_url_accepts_domain() -> None:
    s = make_settings(public_base_url="https://menu.example.com")
    assert s.public_base_url is not None
    assert s.public_base_url.host == "menu.example.com"


def test_get_settings_reads_environment(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_MODE", "scaled")
    clean_env.setenv("REDIS_URL", "redis://redis:6379/0")
    clean_env.setenv("DOCS_ENABLED", "")  # пустое значение — как не заданное
    s = get_settings()
    assert s.app_mode is AppMode.SCALED
    assert s.docs_enabled is None
    assert get_settings() is s  # кэш процесса


def test_get_settings_reads_dotenv_file(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("APP_ENV=test\nLOG_LEVEL=DEBUG\n", encoding="utf-8")
    s = get_settings()
    assert s.app_env is AppEnv.TEST
    assert s.log_level == "DEBUG"


def test_get_settings_unknown_mode_is_clear_error(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_MODE", "bogus")
    with pytest.raises(ConfigError) as exc_info:
        get_settings()
    text = str(exc_info.value)
    assert "Ошибка конфигурации" in text
    assert "APP_MODE: недопустимое значение; допустимо: single, scaled" in text
    assert "bogus" not in text  # введённое значение не выводится


def test_get_settings_scaled_without_redis_is_clear_error(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_MODE", "scaled")
    with pytest.raises(ConfigError, match="REDIS_URL обязателен при APP_MODE=scaled"):
        get_settings()


def test_config_error_does_not_leak_secret_values(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", "postgresql://u:pw-secret@db.invalid/x")
    with pytest.raises(ConfigError) as exc_info:
        get_settings()
    text = str(exc_info.value)
    assert "DATABASE_URL" in text
    assert "asyncpg" in text
    assert "pw-secret" not in text
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


@pytest.mark.parametrize(
    ("variable", "value", "expected"),
    [
        ("PORT", "abc", "PORT: ожидается целое число"),
        ("PORT", "0", "PORT: значение должно быть не меньше 1"),
        ("PORT", "70000", "PORT: значение должно быть не больше 65535"),
        ("SERVE_FRONTEND", "maybe", "SERVE_FRONTEND: ожидается true или false"),
        ("LOG_FORMAT", "xml", "LOG_FORMAT: недопустимое значение"),
        ("PUBLIC_BASE_URL", "not a url", "PUBLIC_BASE_URL: некорректный URL"),
    ],
)
def test_config_error_texts(clean_env: pytest.MonkeyPatch, variable: str, value: str, expected: str) -> None:
    clean_env.setenv(variable, value)
    with pytest.raises(ConfigError, match=re.escape(expected)):
        get_settings()


def test_env_example_lists_every_setting() -> None:
    """ADR-2: каждая переменная Settings есть в .env.example (в том числе закомментированная)."""
    env_example = Path(__file__).resolve().parents[2] / ".env.example"
    text = env_example.read_text(encoding="utf-8")
    names = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))
    missing = {name.upper() for name in Settings.model_fields} - names
    assert not missing, f"нет в .env.example: {sorted(missing)}"
