"""``python -m app.seed [--database-url URL]`` — загрузить демо-данные (ADR-7.12).

Шаги (одна транзакция):

1. Отказ с кодом 2, если ``APP_ENV=prod``.
2. Upsert заведения с фиксированным UUID ``DEMO_TENANT_ID``.
3. Справочник аллергенов (``EU14_ALLERGEN_CODES`` + названия AZ/RU) — по ``(tenant_id, code)``.
4. Залы, столы с детерминированными ``qr_token`` (только для dev) — по ``qr_token``.
5. Категории и позиции — по ``(tenant_id, external_id)``; цены ``default``/``vip``; мета
   (часть блюд с ``allergens_verified = true``, часть — без флага, одна скрытая, одна в стоп-листе).
6. Печать ссылок вида ``/t/{token}`` для локальной проверки.

Повторный запуск не создаёт дублей и возвращает данные к эталонным значениям.
"""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI; возвращает код выхода процесса."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
