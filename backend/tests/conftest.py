"""Test setup: tests never touch the real Supabase database."""

import os

os.environ["APP_ENV"] = "test"  # no weekly scheduler during tests
os.environ["LLM_PRIMARY"] = "claude"  # tests pick the main model themselves
# Fake keys: tests never call the real AI providers.
os.environ["ANTHROPIC_API_KEY"] = "test-claude-key"
os.environ["MISTRAL_API_KEY"] = "test-mistral-key-1"
os.environ["MISTRAL_API_KEYS"] = ""
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1:1/test")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_model_chain():
    """Each test starts with no model resting after an earlier failure."""
    from app.llm import models
    models._resting_until.clear()
    yield
    models._resting_until.clear()
