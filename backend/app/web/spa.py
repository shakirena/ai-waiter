"""Раздача собранного фронтенда с SPA fallback (ADR-3).

Монтируется на "/" ПОСЛЕДНИМ, после всех роутеров. Список RESERVED_PREFIXES должен совпадать
с ``navigateFallbackDenylist`` в ``frontend/vite.config.ts`` и с proxy Vite.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

RESERVED_PREFIXES: tuple[str, ...] = (
    "/api",
    "/integration",
    "/health",
    "/ws",
    "/docs",
    "/redoc",
    "/openapi.json",
)

NO_CACHE_FILES: frozenset[str] = frozenset({"index.html", "sw.js", "manifest.webmanifest"})
IMMUTABLE_PREFIX = "assets/"


def is_reserved(path: str) -> bool:
    """True для ``/api``, ``/api/...``; False для ``/apiary`` (граница сегмента)."""
    raise NotImplementedError


class SPAStaticFiles(StaticFiles):
    """StaticFiles(html=True, follow_symlink=False) с fallback на index.html.

    - файл найден → отдать с заголовками кэша (no-cache для NO_CACHE_FILES, immutable для assets/);
    - 404 и путь зарезервирован → 404 (JSON-ответ формирует FastAPI для своих префиксов);
    - 404 и у последнего сегмента есть расширение → 404;
    - иначе → index.html, 200, no-cache.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        raise NotImplementedError


def mount_spa(app: FastAPI, dist_dir: Path) -> bool:
    """Смонтировать SPA на "/". Если ``dist_dir/index.html`` нет — warning в лог, False, ничего не монтировать."""
    raise NotImplementedError
