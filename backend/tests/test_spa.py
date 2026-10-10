"""SPA fallback и раздача сборки фронтенда (story #42, AC-6, ADR-3)."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path, PurePath
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.routing import Mount

from app.core.config import Settings
from app.main import create_app
from app.web import spa
from app.web.spa import (
    CACHE_IMMUTABLE,
    CACHE_NO_CACHE,
    RESERVED_PREFIXES,
    SPAStaticFiles,
    cache_control_for,
    is_reserved,
    mount_spa,
)
from tests.conftest import make_settings

INDEX_HTML = "<!doctype html><div id=root></div>"
SECRET = "SECRET-OUTSIDE-DIST"
VITE_CONFIG = Path(__file__).resolve().parents[2] / "frontend" / "vite.config.ts"


# ---------------------------------------------------------------- фикстуры


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """Сборка в подкаталоге: рядом лежат «секретные» файлы, которые нельзя отдать через traversal."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "icons").mkdir()
    (root / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (root / "sw.js").write_text("self.skipWaiting()", encoding="utf-8")
    (root / "manifest.webmanifest").write_text('{"name":"AI Waiter"}', encoding="utf-8")
    (root / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (root / "icons" / "icon-192.png").write_bytes(b"\x89PNG")
    (tmp_path / "secret.txt").write_text(SECRET, encoding="utf-8")
    (tmp_path / "secret").write_text(SECRET, encoding="utf-8")
    return root


def _settings(dist_dir: Path) -> Settings:
    return make_settings(serve_frontend=True, frontend_dist_dir=dist_dir)


@pytest.fixture
async def spa_app(dist: Path) -> AsyncIterator[FastAPI]:
    app = create_app(_settings(dist))
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def spa_client(spa_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=spa_app), base_url="http://t") as c:
        yield c


async def raw_request(
    app: Any, path: str, *, method: str = "GET", root_path: str = "", headers: list[tuple[bytes, bytes]] | None = None
) -> tuple[int, dict[str, str], bytes]:
    """Запрос в ASGI-приложение с точным ``scope["path"]`` — без нормализации URL клиентом.

    Так сервер (uvicorn) передаёт уже раскодированный путь: ``/..%2f..`` превращается в ``/../..``."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": root_path + path,
        "raw_path": (root_path + path).encode("utf-8", "surrogateescape"),
        "root_path": root_path,
        "query_string": b"",
        "headers": [(b"host", b"t"), *(headers or [])],
        "client": ("127.0.0.1", 1),
        "server": ("t", 80),
    }
    messages: list[dict[str, Any]] = []
    received = False

    async def receive() -> dict[str, Any]:
        nonlocal received
        if received:  # pragma: no cover - FileResponse не читает тело после первого сообщения
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    resp_headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], resp_headers, body


# ---------------------------------------------------------------- is_reserved / cache_control_for


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api", True),
        ("/api/", True),
        ("/api/orders", True),
        ("//api/orders", True),
        ("/integration/v1/hello", True),
        ("/health", True),
        ("/health/ready", True),
        ("/ws", True),
        ("/ws/staff", True),
        ("/docs", True),
        ("/redoc/x", True),
        ("/openapi.json", True),
        ("/apiary", False),
        ("/api-docs", False),
        ("/healthz", False),
        ("/wsx", False),
        ("/documents", False),
        ("/integrations", False),
        ("/t/abc", False),
        ("/t/api", False),
        ("/staff", False),
        ("/admin/menu", False),
        ("/", False),
    ],
)
def test_is_reserved(path: str, expected: bool) -> None:
    assert is_reserved(path) is expected


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("assets/app-abc123.js", CACHE_IMMUTABLE),
        ("assets/sub/font.woff2", CACHE_IMMUTABLE),
        ("index.html", CACHE_NO_CACHE),
        ("sw.js", CACHE_NO_CACHE),
        ("manifest.webmanifest", CACHE_NO_CACHE),
        ("icons/icon-192.png", CACHE_NO_CACHE),
        ("", CACHE_NO_CACHE),
    ],
)
def test_cache_control_for(relative: str, expected: str) -> None:
    assert cache_control_for(relative) == expected


def test_immutable_value_matches_adr() -> None:
    assert CACHE_IMMUTABLE == "public, max-age=31536000, immutable"
    assert CACHE_NO_CACHE == "no-cache"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (str(PurePath("..", "secret.txt")), True),
        ("..", True),
        (str(Path.cwd()), True),
        (str(PurePath("assets", "app.js")), False),
        ("..foo", False),
        (".", False),
    ],
)
def test_escapes_root(path: str, expected: bool) -> None:
    assert spa._escapes_root(path) is expected


def test_reserved_prefixes_match_vite_config() -> None:
    """DEC-003: BACKEND_PREFIXES в vite.config.ts (proxy и navigateFallbackDenylist) = RESERVED_PREFIXES."""
    source = VITE_CONFIG.read_text(encoding="utf-8")
    match = re.search(r"const\s+BACKEND_PREFIXES\s*=\s*\[(?P<items>[^\]]*)\]", source)
    assert match is not None, "в vite.config.ts не найден массив BACKEND_PREFIXES"
    vite_prefixes = tuple(re.findall(r"""["']([^"']+)["']""", match.group("items")))
    assert vite_prefixes == RESERVED_PREFIXES


# ---------------------------------------------------------------- маршруты интерфейсов


@pytest.mark.parametrize("path", ["/", "/t/some-token", "/t/demo", "/staff", "/staff/", "/admin/menu", "/assets"])
async def test_spa_routes_fall_back_to_index(spa_client: AsyncClient, path: str) -> None:
    r = await spa_client.get(path)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert r.headers["cache-control"] == CACHE_NO_CACHE
    assert r.text == INDEX_HTML


async def test_head_falls_back_to_index(spa_client: AsyncClient) -> None:
    r = await spa_client.head("/staff")
    assert r.status_code == 200
    assert r.headers["cache-control"] == CACHE_NO_CACHE


async def test_non_get_on_spa_route_is_405(spa_client: AsyncClient) -> None:
    r = await spa_client.post("/staff")
    assert r.status_code == 405
    assert "text/html" not in r.headers.get("content-type", "")


# ---------------------------------------------------------------- статические файлы и кэш


async def test_hashed_assets_are_immutable(spa_client: AsyncClient) -> None:
    r = await spa_client.get("/assets/app-abc123.js")
    assert r.status_code == 200
    assert r.text == "console.log(1)"
    assert r.headers["cache-control"] == CACHE_IMMUTABLE


@pytest.mark.parametrize("path", ["/index.html", "/sw.js", "/manifest.webmanifest", "/icons/icon-192.png"])
async def test_entry_files_are_no_cache(spa_client: AsyncClient, path: str) -> None:
    r = await spa_client.get(path)
    assert r.status_code == 200
    assert r.headers["cache-control"] == CACHE_NO_CACHE


async def test_not_modified_keeps_cache_header(spa_client: AsyncClient) -> None:
    first = await spa_client.get("/assets/app-abc123.js")
    r = await spa_client.get("/assets/app-abc123.js", headers={"if-none-match": first.headers["etag"]})
    assert r.status_code == 304
    assert r.headers["cache-control"] == CACHE_IMMUTABLE


# ---------------------------------------------------------------- зарезервированные префиксы и 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/unknown",
        "/api",
        "/integration/v1/unknown",
        "/health/unknown",
        "/ws/x",
        "/docs/x",
        "/openapi.json/x",
        "/missing.png",
        "/assets/missing-abc.js",
        "/t/demo/app.js",
    ],
)
async def test_reserved_and_missing_files_are_json_404(spa_client: AsyncClient, path: str) -> None:
    r = await spa_client.get(path)
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/json"
    assert r.json() == {"detail": "Not Found"}


async def test_reserved_path_is_404_for_any_method(spa_client: AsyncClient) -> None:
    r = await spa_client.post("/api/unknown")
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/json"


async def test_api_routes_are_not_intercepted(spa_client: AsyncClient) -> None:
    r = await spa_client.get("/health")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    docs = await spa_client.get("/openapi.json")
    assert docs.status_code == 200
    assert docs.json()["info"]["title"] == "AI Waiter"


async def test_reserved_path_behind_root_path(spa_app: FastAPI) -> None:
    status, headers, _ = await raw_request(spa_app, "/api/unknown", root_path="/prefix")
    assert status == 404
    assert headers["content-type"] == "application/json"
    status, _, body = await raw_request(spa_app, "/staff", root_path="/prefix")
    assert status == 200
    assert body.decode() == INDEX_HTML


# ---------------------------------------------------------------- path traversal


@pytest.mark.parametrize(
    "path",
    [
        "/../secret.txt",
        "/../../secret.txt",
        "/assets/../../secret.txt",
        "/../secret",
        "/..%2fsecret.txt",
        "/%2e%2e/secret.txt",
        "/..\\secret.txt",
        "/assets\\..\\..\\secret.txt",
        "/C:/Windows/win.ini",
        "/secret.txt\x00.js",
    ],
)
async def test_path_traversal_never_leaks_files(spa_app: FastAPI, path: str) -> None:
    status, _, body = await raw_request(spa_app, path)
    assert SECRET.encode() not in body
    assert status in (200, 404)
    if status == 200:
        # Безопасный исход — только fallback на index.html (путь без расширения внутри dist).
        assert body.decode() == INDEX_HTML


async def test_dot_dot_prefix_is_rejected_before_lookup(spa_app: FastAPI) -> None:
    status, headers, _ = await raw_request(spa_app, "/../secret")
    assert status == 404
    assert headers["content-type"] == "application/json"


async def test_symlink_outside_dist_is_not_followed(dist: Path, spa_client: AsyncClient) -> None:
    link = dist / "leak.txt"
    try:
        link.symlink_to(dist.parent / "secret.txt")
    except (OSError, NotImplementedError):
        pytest.skip("создание символических ссылок недоступно (Windows без прав)")
    r = await spa_client.get("/leak.txt")
    assert r.status_code == 404
    assert SECRET not in r.text


# ---------------------------------------------------------------- монтирование


def test_spa_is_mounted_last(dist: Path) -> None:
    app = create_app(_settings(dist))
    last = app.router.routes[-1]
    assert isinstance(last, Mount)
    assert last.path == ""
    assert isinstance(last.app, SPAStaticFiles)
    assert last.app.follow_symlink is False
    assert sum(isinstance(r, Mount) and isinstance(r.app, SPAStaticFiles) for r in app.router.routes) == 1


def test_serve_frontend_false_does_not_mount(dist: Path) -> None:
    app = create_app(make_settings(serve_frontend=False, frontend_dist_dir=dist))
    assert not any(isinstance(r, Mount) for r in app.router.routes)


@pytest.mark.parametrize("kind", ["missing_dir", "no_index"])
async def test_missing_build_warns_and_app_starts(tmp_path: Path, caplog: pytest.LogCaptureFixture, kind: str) -> None:
    dist_dir = tmp_path / "dist"
    if kind == "no_index":
        dist_dir.mkdir()
    with caplog.at_level(logging.WARNING, logger="app.web.spa"):
        app = create_app(_settings(dist_dir))
    warnings = [r for r in caplog.records if r.name == "app.web.spa" and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert getattr(warnings[0], "frontend_dist_dir", None) == str(dist_dir)
    assert not any(isinstance(r, Mount) for r in app.router.routes)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/health")).status_code == 200
            assert (await c.get("/staff")).status_code == 404


def test_mount_spa_returns_flag(dist: Path, tmp_path: Path) -> None:
    assert mount_spa(FastAPI(), dist) is True
    assert mount_spa(FastAPI(), tmp_path / "nowhere") is False


async def test_index_removed_after_start_is_404(dist: Path, spa_client: AsyncClient) -> None:
    (dist / "index.html").unlink()
    r = await spa_client.get("/staff")
    assert r.status_code == 404
    assert "text/html" not in r.headers.get("content-type", "")


def test_file_response_outside_root_gets_no_cache(dist: Path) -> None:
    files = SPAStaticFiles(directory=dist)
    outside = dist.parent / "secret.txt"
    scope = {"type": "http", "method": "GET", "headers": []}
    response = files.file_response(outside, outside.stat(), scope)
    assert response.headers["cache-control"] == CACHE_NO_CACHE
