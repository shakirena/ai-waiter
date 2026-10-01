from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.web.spa import is_reserved
from tests.conftest import make_settings


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api", True),
        ("/api/orders", True),
        ("/integration/v1/hello", True),
        ("/health/ready", True),
        ("/ws", True),
        ("/apiary", False),
        ("/t/abc", False),
        ("/staff", False),
        ("/", False),
    ],
)
def test_is_reserved(path: str, expected: bool) -> None:
    assert is_reserved(path) is expected


@pytest.fixture
async def spa_client(spa_dist: Path) -> AsyncIterator[AsyncClient]:
    app = create_app(make_settings(serve_frontend=True, frontend_dist_dir=spa_dist))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c


@pytest.mark.parametrize("path", ["/", "/t/some-token", "/staff", "/admin/menu"])
async def test_spa_routes_fall_back_to_index(spa_client: AsyncClient, path: str) -> None:
    r = await spa_client.get(path)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "no-cache" in r.headers["cache-control"]


async def test_hashed_assets_are_immutable(spa_client: AsyncClient) -> None:
    r = await spa_client.get("/assets/app-abc123.js")
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]


@pytest.mark.parametrize("path", ["/api/unknown", "/integration/v1/unknown", "/missing.png"])
async def test_reserved_and_missing_files_are_404(spa_client: AsyncClient, path: str) -> None:
    r = await spa_client.get(path)
    assert r.status_code == 404
    assert "text/html" not in r.headers.get("content-type", "")
