"""Схемы гостевого API ``/api/guest/v1`` (#9, arch «API Contracts»).

Гостю не отдаются ``tenant_id``, ``table_id``, ``hall_id``, ``price_tier``, ``external_id``, ``qr_token``.
``visit.id`` (UUIDv7) доступа не даёт: доступ — только подписанная cookie. Время — ISO 8601 с зоной.
Модуль не зависит от FastAPI и ``app.api`` (``tests/test_import_boundaries.py``).
"""

from __future__ import annotations

import uuid

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models.enums import Lang, TableType

GUEST_TOKEN_MAX_LENGTH = 128


class GuestEntryRequest(BaseModel):
    """Тело ``POST /entry``. Формат токена проверяет сервис (→ 404 ``qr_invalid``, а не 422);
    здесь — только длина 1…128 (spec E-4)."""

    token: str = Field(min_length=1, max_length=GUEST_TOKEN_MAX_LENGTH)
    lang: Lang | None = None  # явный выбор устройства (localStorage); необязательно


class GuestLangRequest(BaseModel):
    """Тело ``PUT /session/lang``: значение вне ``Lang`` — 422 валидации, вне ``tenants.languages`` —
    422 ``lang_not_supported``."""

    lang: Lang


class GuestTenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    languages: list[Lang]
    default_lang: Lang  # tenants.languages[0]
    currency: str  # ISO 4217


class GuestTableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    type: TableType


class GuestVisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    opened_at: AwareDatetime


class GuestEntryVisitOut(GuestVisitOut):
    is_new: bool  # визит открыт этим входом


class GuestSessionResponse(BaseModel):
    """``GET /session`` и ``PUT /session/lang``."""

    tenant: GuestTenantOut
    table: GuestTableOut
    visit: GuestVisitOut
    lang: Lang


class GuestEntryResponse(BaseModel):
    """``POST /entry``: то же, что ``GuestSessionResponse``, плюс ``visit.is_new``."""

    tenant: GuestTenantOut
    table: GuestTableOut
    visit: GuestEntryVisitOut
    lang: Lang


__all__ = [
    "GUEST_TOKEN_MAX_LENGTH",
    "GuestEntryRequest",
    "GuestEntryResponse",
    "GuestEntryVisitOut",
    "GuestLangRequest",
    "GuestSessionResponse",
    "GuestTableOut",
    "GuestTenantOut",
    "GuestVisitOut",
]
