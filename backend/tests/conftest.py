"""Test setup: tests never touch the real Supabase database."""

import os

os.environ["APP_ENV"] = "test"  # no weekly scheduler during tests
os.environ["LLM_PRIMARY"] = "claude"  # tests pick the main model themselves
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1:1/test")
