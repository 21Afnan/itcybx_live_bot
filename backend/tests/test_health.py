"""Tests for /health. They fake Postgres and Redis, so they run anywhere."""

import pytest
from fastapi.testclient import TestClient

from app import main


def fake(answer):
    async def check():
        return answer

    return check


@pytest.mark.parametrize(
    "db_ok, redis_ok, code, status",
    [
        (True, True, 200, "ok"),
        (False, True, 503, "degraded"),
        (True, False, 503, "degraded"),
    ],
)
def test_health(monkeypatch, db_ok, redis_ok, code, status):
    monkeypatch.setattr(main, "database_works", fake(db_ok))
    monkeypatch.setattr(main, "redis_works", fake(redis_ok))

    resp = TestClient(main.app).get("/health")

    assert resp.status_code == code
    assert resp.json()["status"] == status
    assert resp.json()["database"] == ("ok" if db_ok else "error")
    assert resp.json()["redis"] == ("ok" if redis_ok else "error")


def test_health_says_error_when_services_are_down(monkeypatch):
    """Point at addresses where nothing runs: both checks must say error."""
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import create_async_engine

    monkeypatch.setattr(main, "database", create_async_engine("postgresql+asyncpg://x:y@127.0.0.1:1/z"))
    monkeypatch.setattr(main, "redis", Redis.from_url("redis://127.0.0.1:1/0"))

    resp = TestClient(main.app).get("/health")

    assert resp.status_code == 503
    assert resp.json() == {"status": "degraded", "database": "error", "redis": "error"}
