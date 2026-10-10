"""Base, NAMING_CONVENTION и миксины (ADR-7.1, 7.3, 7.8) без БД.

Модели проверки объявлены на отдельной ``MetaData`` (не ``Base.metadata``), чтобы тестовые
таблицы не попали в autogenerate Alembic.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Index, MetaData, Numeric, String, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import CreateTable

from app.db.base import NAMING_CONVENTION, Base, Money
from app.db.ids import new_id
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class _ProbeBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class _Tenant(UUIDPrimaryKeyMixin, _ProbeBase):
    __tablename__ = "tenants"


class _Hall(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, _ProbeBase):
    __tablename__ = "halls"
    __extra_table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint("length(name) > 0", name="name_not_empty"),
        {"comment": "залы"},
    )

    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[object] = mapped_column(Money)


class _Link(TenantMixin, _ProbeBase):
    """Таблица-связка с составным PK — без ``UNIQUE (tenant_id, id)``."""

    __tablename__ = "links"

    hall_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), primary_key=True)


class _Indexed(UUIDPrimaryKeyMixin, TenantMixin, _ProbeBase):
    __tablename__ = "indexed"
    __extra_table_args__ = (Index(None, "tenant_id", "code"),)

    code: Mapped[str] = mapped_column(String(10))


def _ddl(model: type[_ProbeBase]) -> str:
    return str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


def test_base_metadata_uses_naming_convention() -> None:
    for key, template in NAMING_CONVENTION.items():
        assert Base.metadata.naming_convention[key] == template


def test_money_is_numeric_10_2_decimal() -> None:
    assert isinstance(Money, Numeric)
    assert (Money.precision, Money.scale, Money.asdecimal) == (10, 2, True)


def test_uuid_primary_key_defaults() -> None:
    column = _Tenant.__table__.c.id
    assert column.primary_key
    assert column.default is not None
    assert isinstance(column.default.arg(None), uuid.UUID)  # SQLAlchemy оборачивает new_id в fn(ctx)
    assert column.default.arg.__wrapped__ is new_id
    assert "gen_random_uuid()" in str(column.server_default.arg)
    ddl = _ddl(_Tenant)
    assert "id UUID DEFAULT gen_random_uuid() NOT NULL" in ddl
    assert "CONSTRAINT pk_tenants PRIMARY KEY (id)" in ddl


def test_tenant_mixin_constraints_and_names() -> None:
    ddl = _ddl(_Hall)
    assert "tenant_id UUID NOT NULL" in ddl
    assert (
        "CONSTRAINT fk_halls_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE RESTRICT" in ddl
    )
    assert "CONSTRAINT uq_halls_tenant_id_id UNIQUE (tenant_id, id)" in ddl
    assert "CONSTRAINT uq_halls_tenant_id_name UNIQUE (tenant_id, name)" in ddl
    assert "CONSTRAINT ck_halls_name_not_empty CHECK (length(name) > 0)" in ddl
    assert "price NUMERIC(10, 2)" in ddl
    assert _Hall.__table__.comment == "залы"


def test_tenant_mixin_without_id_has_no_tenant_id_id_unique() -> None:
    ddl = _ddl(_Link)
    assert "uq_links_tenant_id_id" not in ddl
    assert "CONSTRAINT pk_links PRIMARY KEY (hall_id, code)" in ddl
    assert "fk_links_tenant_id_tenants" in ddl


def test_extra_index_gets_conventional_name() -> None:
    assert {index.name for index in _Indexed.__table__.indexes} == {"ix_indexed_tenant_id_code"}


def test_timestamp_mixin_is_timestamptz_with_now_default() -> None:
    ddl = _ddl(_Hall)
    assert "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in ddl
    assert "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in ddl
    assert _Hall.__table__.c.updated_at.onupdate is not None
    assert _Hall.__table__.c.created_at.onupdate is None
