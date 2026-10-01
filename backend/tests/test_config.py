from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import AppEnv, AppMode
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
