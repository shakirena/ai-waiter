"""Сервисы гостя: вход по QR-токену, визит, язык, гостевая сессия (#9, ``docs/arch/feature-9-guest-qr-entry.md``).

Пакет не зависит от FastAPI/Starlette и ``app.api`` (как ``app.menu_sync``, DEC-011): HTTP-коды,
cookie и заголовки — только в ``app/api/guest.py`` и ``app/api/guest_auth.py``. ``Settings`` пакет
не читает: нужные значения (секрет, TTL, ``reject_demo``) передаёт вызывающий.

- ``entry`` — сценарий входа и загрузка контекста гостя по сессии (транзакцию фиксирует сервис, DEC-007);
- ``tokens`` — генерация и перевыпуск QR-токена стола (ADR-9.5);
- ``visits`` — get-or-open / close визита (ADR-9.3);
- ``session`` — кодек подписанной cookie (HMAC-SHA256, ADR-9.2);
- ``lang`` — ``Accept-Language`` → ``az``/``ru`` (ADR-9.4);
- ``errors`` — доменные исключения.
"""
