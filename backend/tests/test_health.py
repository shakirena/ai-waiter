from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_health_liveness(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["mode"] == "single"
    assert body["version"]


async def test_ready_in_single_mode_skips_redis(client: AsyncClient) -> None:
    r = await client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"redis": "skipped"}}


async def test_ready_returns_503_without_details_when_check_fails() -> None:
    pytest.skip("TODO(developer): подменить ping() на исключение → 503, текст исключения не в теле")
