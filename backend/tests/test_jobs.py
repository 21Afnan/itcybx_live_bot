"""Tests for the background jobs' run-once lock."""

import asyncio

from app import jobs


class LockRedis:
    def __init__(self):
        self.keys = set()

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys.add(key)
        return True


def test_a_job_runs_once_across_workers(monkeypatch):
    redis = LockRedis()
    monkeypatch.setattr(jobs.sessions, "get_redis", lambda: redis)
    runs = []

    async def job():
        runs.append(1)

    async def two_workers():
        await jobs.run_once("sync", job, lock_seconds=600)
        await jobs.run_once("sync", job, lock_seconds=600)

    asyncio.run(two_workers())
    assert runs == [1]


def test_a_job_still_runs_when_redis_is_down(monkeypatch):
    class DownRedis:
        async def set(self, *args, **kwargs):
            raise ConnectionError("redis down")

    monkeypatch.setattr(jobs.sessions, "get_redis", lambda: DownRedis())
    runs = []

    async def job():
        runs.append(1)

    asyncio.run(jobs.run_once("lead-alerts", job, lock_seconds=60))
    assert runs == [1]
