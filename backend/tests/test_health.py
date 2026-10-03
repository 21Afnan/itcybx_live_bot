"""Tests for /health. They never touch the real Supabase or Redis."""

import pytest
from fastapi.testclient import TestClient

from app import main, sessions
from app.db import engine


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
    monkeypatch.setattr(engine.settings, "database_url", secret_url)
    monkeypatch.setattr(sessions.settings, "redis_url", "redis://127.0.0.1:1/0")
    engine.get_engine.cache_clear()
    sessions.get_redis.cache_clear()

    resp = TestClient(main.app).get("/health")

    assert resp.status_code == 503
    assert resp.json()["db"] == "ArgumentError"
    assert resp.json()["redis"] not in ("ok", "")
    assert secret_url not in resp.text

    engine.get_engine.cache_clear()
    sessions.get_redis.cache_clear()
