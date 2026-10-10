"""Раздача собранного фронтенда с SPA fallback (ADR-3, DEC-003).

Монтируется на "/" ПОСЛЕДНИМ, после всех роутеров: ``Mount("/")`` совпадает с любым путём, поэтому
роутер, подключённый после него, недостижим. Список ``RESERVED_PREFIXES`` должен совпадать
с ``BACKEND_PREFIXES`` в ``frontend/vite.config.ts`` (proxy и ``navigateFallbackDenylist``);
совпадение проверяет ``tests/test_spa.py``.
"""

from __future__ import annotations

import logging
import os
import re
import stat
from pathlib import Path, PurePath

import anyio.to_thread
from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import PathLike, StaticFiles
from starlette.types import Scope

logger = logging.getLogger(__name__)

RESERVED_PREFIXES: tuple[str, ...] = (
    "/api",
    "/integration",
    "/health",
    "/ws",
    "/docs",
    "/redoc",
    "/openapi.json",
)

INDEX_FILE = "index.html"
IMMUTABLE_PREFIX = "assets/"

# Хешированные имена Vite в assets/ не меняются: кэш на год без перепроверки.
CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
# index.html, sw.js, manifest.webmanifest и прочие файлы с постоянными именами — всегда перепроверка
# (ETag/Last-Modified), иначе браузер или Service Worker застрянут на старой версии.
CACHE_NO_CACHE = "no-cache"

_SLASHES = re.compile(r"/{2,}")


def is_reserved(path: str) -> bool:
    """True для ``/api``, ``/api/...``; False для ``/apiary`` (граница сегмента).

    Повторные слеши схлопываются: ``//api/x`` тоже зарезервирован."""
    path = _SLASHES.sub("/", path)
    return any(path == prefix or path.startswith(prefix + "/") for prefix in RESERVED_PREFIXES)


def cache_control_for(relative_path: str) -> str:
    """Значение ``Cache-Control`` для файла сборки по его пути относительно каталога dist (через ``/``)."""
    return CACHE_IMMUTABLE if relative_path.startswith(IMMUTABLE_PREFIX) else CACHE_NO_CACHE


def _has_extension(route_path: str) -> bool:
    """У последнего сегмента URL есть расширение (``/foo.png``) — это запрос файла, а не маршрута SPA."""
    return PurePath(route_path.replace("\\", "/")).suffix != ""


def _route_path(scope: Scope) -> str:
    """Путь запроса без ``root_path`` (приложение за прокси с префиксом)."""
    path: str = scope["path"]
    root_path: str = scope.get("root_path", "")
    if root_path and path.startswith(root_path):
        return path[len(root_path) :] or "/"
    return path


def _escapes_root(path: str) -> bool:
    """Нормализованный путь выходит за каталог сборки: ``..`` в начале, абсолютный путь или диск Windows."""
    pure = PurePath(path)
    return pure.is_absolute() or bool(pure.drive or pure.root) or (bool(pure.parts) and pure.parts[0] == "..")


class SPAStaticFiles(StaticFiles):
    """``StaticFiles(follow_symlink=False)`` с fallback на ``index.html``.

    - путь зарезервирован → 404 (JSON формирует обработчик исключений FastAPI), файлы не ищутся;
    - путь выходит за каталог сборки (``..``, абсолютный путь, диск Windows) → 404;
    - файл найден → отдать с заголовком кэша (immutable для ``assets/``, иначе no-cache);
    - файла нет и у последнего сегмента есть расширение → 404;
    - иначе → ``index.html``, 200, no-cache.

    ``html=False`` намеренно: каталог (``/``, ``/assets``) не перенаправляется на ``/…/``
    и ``404.html`` не подставляется — этими случаями управляет fallback.
    Защита от path traversal базовая (``realpath`` + ``commonpath`` в ``lookup_path``)
    плюс собственная проверка ``_escapes_root``.
    """

    def __init__(self, *, directory: PathLike) -> None:
        super().__init__(directory=directory, html=False, check_dir=True, follow_symlink=False)
        self._root = Path(directory).resolve()

    async def get_response(self, path: str, scope: Scope) -> Response:
        route_path = _route_path(scope)
        if is_reserved(route_path) or _escapes_root(path):
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or _has_extension(route_path):
                raise
        return await self._index_response(scope)

    async def _index_response(self, scope: Scope) -> Response:
        full_path, stat_result = await anyio.to_thread.run_sync(self.lookup_path, INDEX_FILE)
        if stat_result is None or not stat.S_ISREG(stat_result.st_mode):
            # Сборку удалили после старта: честный 404 вместо 500.
            raise HTTPException(status_code=404)
        return self.file_response(full_path, stat_result, scope)

    def file_response(
        self,
        full_path: PathLike,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        try:
            relative = Path(full_path).relative_to(self._root).as_posix()
        except ValueError:
            relative = ""
        response.headers["Cache-Control"] = cache_control_for(relative)
        return response


def mount_spa(app: FastAPI, dist_dir: Path) -> bool:
    """Смонтировать SPA на "/". Если ``dist_dir/index.html`` нет — warning в лог, False, ничего не монтировать.

    Вызывается последним в ``create_app``: после него маршруты не добавляются."""
    index = dist_dir / INDEX_FILE
    if not index.is_file():
        logger.warning(
            "Сборка фронтенда не найдена, интерфейсы не раздаются; выполните npm run build "
            "или задайте FRONTEND_DIST_DIR",
            extra={"frontend_dist_dir": str(dist_dir)},
        )
        return False
    app.mount("/", SPAStaticFiles(directory=dist_dir), name="spa")
    logger.info("Фронтенд раздаётся из каталога сборки", extra={"frontend_dist_dir": str(dist_dir)})
    return True
