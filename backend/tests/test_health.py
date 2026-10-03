"""Tests for /health. They never touch the real Supabase or Redis."""

import pytest
from fastapi.testclient import TestClient

from app import main


def fake(answer):
    async def check():
        return answer

    return check


@pytest.mark.parametrize(
    "db, redis, code, status",
    [
        ("ok", "ok", 200, "ok"),
        ("TimeoutError", "ok", 503, "degraded"),
        ("ok", "ConnectionError", 503, "degraded"),
    ],
)
def test_health(monkeypatch, db, redis, code, status):
    monkeypatch.setattr(main, "database_status", fake(db))
    monkeypatch.setattr(main, "redis_status", fake(redis))

    resp = TestClient(main.app).get("/health")

    assert resp.status_code == code
    assert resp.json() == {"status": status, "db": db, "redis": redis}


def test_wrong_database_url_is_reported_not_crashing(monkeypatch):
    """A broken DATABASE_URL shows an error name and never leaks the URL."""
    secret_url = "not-a-real-url-with-secret-password"
    monkeypatch.setattr(main.settings, "database_url", secret_url)
    monkeypatch.setattr(main.settings, "redis_url", "redis://127.0.0.1:1/0")
    main.get_database.cache_clear()
    main.get_redis.cache_clear()

    resp = TestClient(main.app).get("/health")

    assert resp.status_code == 503
    assert resp.json()["db"] == "ArgumentError"
    assert resp.json()["redis"] not in ("ok", "")
    assert secret_url not in resp.text

    main.get_database.cache_clear()
    main.get_redis.cache_clear()
