"""Доменные исключения гостя (#9). HTTP-коды и тело ошибки назначает ``app/api/guest.py`` (ADR-9.6).

В текстах исключений нет токена, cookie, названий заведения и стола: они не должны попасть в лог
или ответ. Соответствие исключение → ответ API:

| Исключение | Ответ |
|---|---|
| ``QrInvalidError`` | 404 ``qr_invalid`` (неизвестный, перевыпущенный, неверный по формату, демо в prod) |
| ``TableInactiveError`` | 403 ``table_inactive`` |
| ``VisitOpenConflictError`` | 503 ``try_again`` |
| ``GuestSessionInvalidError`` | 401 ``guest_session_invalid`` |
| ``VisitClosedError`` | 401 ``visit_closed`` |
| ``LangNotSupportedError`` | 422 ``lang_not_supported`` |
| ``TableNotFoundError`` | — (вызывающий #27 решает сам; гостевой API её не получает) |
"""

from __future__ import annotations


class GuestError(Exception):
    """Базовое исключение сервисов гостя."""


class QrInvalidError(GuestError):
    """Токен не найден, не соответствует ``QR_TOKEN_PATTERN`` или (при ``reject_demo``) принадлежит
    ``DEMO_TENANT_ID``. Причины снаружи неразличимы (ADR-9.6, FR-3/FR-4 spec)."""


class TableInactiveError(GuestError):
    """Токен найден, но ``tables.is_active = false`` (ADR-9.6)."""


class VisitOpenConflictError(GuestError):
    """Визит не удалось ни найти, ни открыть за ``OPEN_VISIT_ATTEMPTS`` попыток (ADR-9.3; практически недостижимо)."""


class TableNotFoundError(GuestError):
    """Перевыпуск токена: стола с таким ``tenant_id``/``id`` нет (ADR-9.5)."""


class GuestSessionInvalidError(GuestError):
    """Сессия подписана верно, но больше не действует: визит не найден по ``tid``/``vid``/``tbl``,
    токен стола перевыпущен (``tia``), стол отключён, демо-заведение в prod (ADR-9.2, spec FR-6)."""


class VisitClosedError(GuestError):
    """Визит сессии закрыт (FR-14a): официант, касса или таймаут (ADR-9.2)."""


class LangNotSupportedError(GuestError):
    """Язык допустим (``Lang``), но не входит в ``tenants.languages`` (ADR-9.4)."""
