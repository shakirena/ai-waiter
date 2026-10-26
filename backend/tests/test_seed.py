"""Сид-данные (#53, ADR-7.12) без PostgreSQL: корректность ``app.seed.data`` и CLI ``python -m app.seed``.

Загрузка в настоящую БД и идемпотентность — ``tests/db/test_seed.py``.
"""

from __future__ import annotations

import dataclasses
import os
import re
import runpy
import subprocess
import sys
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.seed.__main__ as seed_cli
from app.models.enums import (
    CURRENCY_PATTERN,
    DEFAULT_PRICE_TIER,
    PRICE_TIER_PATTERN,
    QR_TOKEN_PATTERN,
    TableType,
)
from app.models.menu import DESCRIPTION_MAX, EXTERNAL_ID_MAX, NAME_MAX, PREP_MINUTES_MAX, SPICE_LEVEL_MAX
from app.models.reference import EU14_ALLERGEN_CODES
from app.models.visit import COMMENT_MAX, QTY_MAX, QTY_MIN
from app.seed import data
from app.seed.guard import FOREIGN_TENANTS_REFUSAL, ForeignTenantsError
from app.seed.loader import SeededTable, SeedSummary

SEED_DATA_FILE = Path(data.__file__)
BACKEND_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "Seed-Pa55word-xyz"
FAKE_URL = f"postgresql+asyncpg://dev:{PASSWORD}@db.invalid/demo_dev"

IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{0,4}){2,7}\b")
SECRET_PATTERN = re.compile(
    r"sk-ant-|-----BEGIN|password\s*[=:]|passwd|api[_-]?key|secret|AKIA[0-9A-Z]{16}|://[^/\s]*:[^/\s]*@",
    re.IGNORECASE,
)


def _strings(value: Any) -> Iterator[str]:
    """Все строки в данных сида (рекурсивно по dataclass, кортежам, словарям)."""
    if isinstance(value, str):
        yield value
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for item in dataclasses.fields(value):
            yield from _strings(getattr(value, item.name))
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, tuple | list):
        for item in value:
            yield from _strings(item)


ALL_SEED_DATA = (data.TENANT, data.HALLS, data.TABLES, data.CATEGORIES, data.DISHES, data.VISIT, data.ORDER)


# ---------------------------------------------------------------- data.py


def test_tenant_is_fictional_demo_with_azn_and_baku() -> None:
    assert data.TENANT.name == "Demo Restoran"
    assert data.TENANT.currency == "AZN"
    assert re.match(CURRENCY_PATTERN, data.TENANT.currency)
    assert data.TENANT.timezone == "Asia/Baku"
    assert data.TENANT.languages == ("az", "ru")
    assert data.TENANT.id == data.DEMO_TENANT_ID


def test_halls_and_tables_shape() -> None:
    assert len(data.HALLS) == 2
    assert len(data.TABLES) == 6
    hall_keys = {hall.key for hall in data.HALLS}
    assert {table.hall for table in data.TABLES} <= hall_keys
    cabins = [table for table in data.TABLES if table.type is TableType.CABIN]
    assert len(cabins) == 1
    assert cabins[0].price_tier == data.VIP_PRICE_TIER
    assert [table.is_active for table in data.TABLES].count(False) == 1
    for table in data.TABLES:
        assert re.match(PRICE_TIER_PATTERN, table.price_tier)


def test_qr_tokens_match_pattern_and_are_unique() -> None:
    tokens = [table.qr_token for table in data.TABLES]
    assert len(set(tokens)) == len(tokens)
    for token in tokens:
        assert re.match(QR_TOKEN_PATTERN, token), token
        assert len(token) >= 22
        assert token.startswith("demo-table-")


def test_categories_and_dishes_reference_each_other() -> None:
    assert len(data.CATEGORIES) == 4
    category_ids = {category.external_id for category in data.CATEGORIES}
    assert len(category_ids) == 4
    assert 12 <= len(data.DISHES) <= 20
    external_ids = [dish.external_id for dish in data.DISHES]
    assert len(set(external_ids)) == len(external_ids)
    for dish in data.DISHES:
        assert dish.category in category_ids
        assert 1 <= len(dish.external_id) <= EXTERNAL_ID_MAX
    for category in data.CATEGORIES:
        assert category.name_az
        assert category.name_ru
        assert len(category.external_id) <= EXTERNAL_ID_MAX


def test_every_dish_has_default_and_vip_prices_as_two_place_decimals() -> None:
    for dish in data.DISHES:
        assert DEFAULT_PRICE_TIER in dish.prices, dish.external_id
        assert data.VIP_PRICE_TIER in dish.prices, dish.external_id
        for tier, price in dish.prices.items():
            assert re.match(PRICE_TIER_PATTERN, tier)
            assert isinstance(price, Decimal)
            assert price >= 0
            assert price.as_tuple().exponent == -2, (dish.external_id, price)
            assert price < Decimal("100000000")  # NUMERIC(10,2)


def test_dish_texts_in_az_and_ru_within_limits() -> None:
    for dish in data.DISHES:
        for text in (dish.name_az, dish.name_ru):
            assert 1 <= len(text) <= NAME_MAX
        for text in (dish.description_az, dish.description_ru):
            assert 1 <= len(text) <= DESCRIPTION_MAX
        assert dish.spice_level is None or 0 <= dish.spice_level <= SPICE_LEVEL_MAX
        assert dish.prep_minutes is None or 1 <= dish.prep_minutes <= PREP_MINUTES_MAX
        assert (dish.weight_amount is None) == (dish.weight_unit is None)
        if dish.weight_amount is not None:
            assert isinstance(dish.weight_amount, Decimal)
            assert dish.weight_amount > 0


def test_allergen_examples_cover_verified_and_unknown() -> None:
    """AI-2: есть подтверждённые списки (в том числе пустой) и позиции без подтверждения."""
    verified = [dish for dish in data.DISHES if dish.allergens_verified]
    unverified = [dish for dish in data.DISHES if not dish.allergens_verified]
    assert any(dish.allergens for dish in verified)
    assert any(not dish.allergens for dish in verified)
    assert unverified
    assert any(dish.allergens for dish in unverified)  # список без флага — всё равно «неизвестно»
    for dish in data.DISHES:
        assert set(dish.allergens) <= set(EU14_ALLERGEN_CODES)
        assert len(set(dish.allergens)) == len(dish.allergens)


def test_exactly_one_hidden_and_one_unavailable_dish() -> None:
    assert [dish.is_hidden for dish in data.DISHES].count(True) == 1
    assert [dish.is_available for dish in data.DISHES].count(False) == 1


def test_visit_cart_and_order_use_orderable_dishes() -> None:
    table = data.table_by_token(data.VISIT.table_token)
    assert table.is_active
    lines = [*data.VISIT.cart, *data.ORDER.lines]
    assert data.VISIT.cart
    assert data.ORDER.lines
    for line in lines:
        dish = data.dish_by_external_id(line.dish)
        assert dish.is_available
        assert not dish.is_hidden
        assert QTY_MIN <= line.qty <= QTY_MAX
        assert len(line.comment) <= COMMENT_MAX
    assert {message.role.value for message in data.VISIT.messages} == {"user", "assistant"}


def test_order_total_uses_table_tier_prices() -> None:
    expected = Decimal("6.50") * 1 + Decimal("12.00") * 2
    assert data.order_total(data.ORDER, DEFAULT_PRICE_TIER) == expected
    vip = Decimal("8.00") * 1 + Decimal("14.50") * 2
    assert data.order_total(data.ORDER, data.VIP_PRICE_TIER) == vip


def test_price_for_falls_back_to_default_tier() -> None:
    dish = data.dish_by_external_id("demo-d01")
    assert data.price_for(dish, "terrace") == dish.prices[DEFAULT_PRICE_TIER]


def test_lookup_helpers_raise_for_unknown_keys() -> None:
    with pytest.raises(KeyError):
        data.dish_by_external_id("missing")
    with pytest.raises(KeyError):
        data.table_by_token("missing")


def test_fixed_ids_are_deterministic_and_distinct() -> None:
    assert data.demo_id("tenant") == data.DEMO_TENANT_ID == uuid.uuid5(data.DEMO_NAMESPACE, "tenant")
    ids = [
        data.DEMO_TENANT_ID,
        data.VISIT.id,
        *(message.id for message in data.VISIT.messages),
        data.ORDER.id,
        data.ORDER.idempotency_key,
        data.ORDER.created_event_id,
        *(line.id for line in data.ORDER.lines),
    ]
    assert len(set(ids)) == len(ids)


def test_no_ip_addresses_or_secrets_in_seed_data() -> None:
    """Репозиторий публичный: ни в значениях, ни в исходнике данных нет адресов и секретов."""
    values = list(_strings(ALL_SEED_DATA))
    assert values
    sources = [SEED_DATA_FILE.read_text(encoding="utf-8"), *values]
    for text in sources:
        assert not IP_PATTERN.search(text), text[:80]
        assert not SECRET_PATTERN.search(text), text[:80]


def test_secret_and_ip_patterns_detect_violations() -> None:
    """Проверка самих шаблонов: иначе тест выше мог бы ничего не ловить."""
    assert IP_PATTERN.search("host 10.1.2.3")
    assert SECRET_PATTERN.search("postgresql://user:pw@host/db")
    assert SECRET_PATTERN.search("sk-ant-xxxx")
    assert not SECRET_PATTERN.search("demo-table-01-dev-only")


# ---------------------------------------------------------------- python -m app.seed


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Окружение разработки с фиктивной БД (.invalid не резолвится, соединения нет)."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("APP_MODE", "single")
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)


async def _target_ok(session: AsyncSession) -> None:
    """Проверка целевой базы (#60) прошла: в базе нет заведений, кроме демо."""


@pytest.fixture
def seed_target_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подмена ``ensure_seed_target`` на no-op: иначе её запрос уйдёт в ``db.invalid`` и даст код 1."""
    monkeypatch.setattr(seed_cli, "ensure_seed_target", _target_ok)


SUMMARY = SeedSummary(
    tenant_id=data.DEMO_TENANT_ID,
    tables=(
        SeededTable("Стол 1", "demo-table-01-dev-only", True),
        SeededTable("Терраса 2", "demo-table-06-dev-only", False),
    ),
)


async def _fake_apply_seed(session: AsyncSession) -> SeedSummary:
    return SUMMARY


async def _failing_apply_seed(session: AsyncSession) -> SeedSummary:
    raise RuntimeError(f"connection to dev:{PASSWORD}@db failed")


@pytest.mark.usefixtures("dev_env")
def test_prod_is_refused_with_exit_code_2(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    called: list[object] = []
    monkeypatch.setattr(seed_cli, "apply_seed", lambda session: called.append(session))

    assert seed_cli.main([]) == seed_cli.EXIT_PROD_FORBIDDEN
    assert seed_cli.main(["--database-url", FAKE_URL]) == 2
    err = capsys.readouterr().err
    assert "APP_ENV=prod" in err
    assert called == []


def test_prod_refusal_does_not_need_other_settings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """В prod отказ раньше проверки остальной конфигурации (PUBLIC_BASE_URL и т.п. не нужны)."""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    assert seed_cli.main([]) == 2


@pytest.mark.usefixtures("dev_env")
def test_invalid_app_env_is_config_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    assert seed_cli.main([]) == seed_cli.EXIT_ERROR
    assert "APP_ENV" in capsys.readouterr().err


@pytest.mark.usefixtures("dev_env")
def test_invalid_database_url_is_config_error_without_value(capsys: pytest.CaptureFixture[str]) -> None:
    url = f"mysql://dev:{PASSWORD}@db.invalid/demo"
    assert seed_cli.main(["--database-url", url]) == 1
    err = capsys.readouterr().err
    assert "DATABASE_URL" in err
    assert PASSWORD not in err


@pytest.mark.usefixtures("dev_env", "seed_target_ok")
def test_success_prints_relative_guest_links(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(seed_cli, "apply_seed", _fake_apply_seed)
    assert seed_cli.main([]) == seed_cli.EXIT_OK
    out = capsys.readouterr().out
    assert "/t/demo-table-01-dev-only" in out
    assert "/t/demo-table-06-dev-only (стол неактивен)" in out
    assert "http" not in out


@pytest.mark.usefixtures("dev_env", "seed_target_ok")
def test_database_url_argument_overrides_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str] = []
    original = seed_cli._load_settings

    def spy(database_url: str | None) -> Any:
        settings = original(database_url)
        seen.append(settings.database_url.get_secret_value())
        return settings

    monkeypatch.setattr(seed_cli, "_load_settings", spy)
    monkeypatch.setattr(seed_cli, "apply_seed", _fake_apply_seed)
    other = "postgresql+asyncpg://other:pw@db.invalid/other_dev"
    assert seed_cli.main(["--database-url", other]) == 0
    assert seen == [other]


@pytest.mark.usefixtures("dev_env", "seed_target_ok")
def test_database_error_is_exit_1_without_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(seed_cli, "apply_seed", _failing_apply_seed)
    assert seed_cli.main([]) == seed_cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert PASSWORD not in captured.err + captured.out
    assert "***" in captured.err
    assert "alembic upgrade head" in captured.err


async def _foreign_target(session: AsyncSession) -> None:
    raise ForeignTenantsError


@pytest.mark.usefixtures("dev_env")
def test_foreign_tenants_are_refused_with_exit_code_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-1 (#60): в базе есть заведение, кроме демо, → код 2, текст в stderr, загрузчик не вызван."""
    called: list[object] = []

    async def spy_apply_seed(session: AsyncSession) -> SeedSummary:
        called.append(session)
        return SUMMARY

    monkeypatch.setattr(seed_cli, "ensure_seed_target", _foreign_target)
    monkeypatch.setattr(seed_cli, "apply_seed", spy_apply_seed)

    assert seed_cli.main([]) == seed_cli.EXIT_FORBIDDEN == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert FOREIGN_TENANTS_REFUSAL in captured.err
    assert "Не удалось загрузить демо-данные" not in captured.err
    assert PASSWORD not in captured.err
    assert "db.invalid" not in captured.err
    assert called == []


def test_exit_prod_forbidden_is_alias_of_exit_forbidden() -> None:
    assert seed_cli.EXIT_PROD_FORBIDDEN == seed_cli.EXIT_FORBIDDEN == 2


@pytest.mark.usefixtures("dev_env")
def test_prod_refusal_happens_before_target_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """E-5: при ``APP_ENV=prod`` отказ раньше подключения — проверка целевой базы не вызывается."""
    monkeypatch.setenv("APP_ENV", "prod")
    called: list[object] = []

    async def spy(session: AsyncSession) -> None:
        called.append(session)

    monkeypatch.setattr(seed_cli, "ensure_seed_target", spy)
    assert seed_cli.main(["--database-url", FAKE_URL]) == 2
    assert "APP_ENV=prod" in capsys.readouterr().err
    assert called == []


@pytest.mark.usefixtures("dev_env")
def test_target_check_runs_before_apply_seed_in_same_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-60.1: проверка — первый запрос транзакции сида, загрузчик получает ту же сессию."""
    calls: list[tuple[str, object]] = []

    async def spy_target(session: AsyncSession) -> None:
        calls.append(("guard", session))

    async def spy_apply_seed(session: AsyncSession) -> SeedSummary:
        calls.append(("seed", session))
        return SUMMARY

    monkeypatch.setattr(seed_cli, "ensure_seed_target", spy_target)
    monkeypatch.setattr(seed_cli, "apply_seed", spy_apply_seed)
    assert seed_cli.main([]) == 0
    assert [name for name, _ in calls] == ["guard", "seed"]
    assert calls[0][1] is calls[1][1]


@pytest.mark.usefixtures("dev_env")
def test_database_error_in_target_check_is_exit_1_without_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """E-6: ошибка запроса проверки (нет соединения, нет таблицы) — код 1 через ``describe_error``."""

    async def failing_target(session: AsyncSession) -> None:
        raise RuntimeError(f"connection to dev:{PASSWORD}@db failed")

    called: list[object] = []
    monkeypatch.setattr(seed_cli, "ensure_seed_target", failing_target)
    monkeypatch.setattr(seed_cli, "apply_seed", lambda session: called.append(session))
    assert seed_cli.main([]) == seed_cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert PASSWORD not in captured.err + captured.out
    assert "***" in captured.err
    assert "alembic upgrade head" in captured.err
    assert FOREIGN_TENANTS_REFUSAL not in captured.err
    assert called == []


def test_module_entry_point_refuses_prod_in_subprocess() -> None:
    """Настоящий ``python -m app.seed``: код выхода процесса 2 и текст на русском в stderr."""
    env = {**os.environ, "APP_ENV": "prod", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, "-m", "app.seed"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    assert "APP_ENV=prod" in result.stderr


@pytest.mark.filterwarnings("ignore:.*found in sys.modules.*:RuntimeWarning")
def test_module_guard_raises_system_exit_with_main_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Блок ``if __name__ == "__main__"`` в том же процессе (видит покрытие): код ``main`` уходит в
    ``SystemExit``. Отказ при ``APP_ENV=prod`` наступает до подключения к БД."""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setattr(sys, "argv", ["python -m app.seed"])
    with pytest.raises(SystemExit) as info:
        runpy.run_module("app.seed", run_name="__main__", alter_sys=True)
    assert info.value.code == seed_cli.EXIT_PROD_FORBIDDEN
    assert "APP_ENV=prod" in capsys.readouterr().err
