"""Tests for the tables and the migration. No database needed."""

import subprocess
import sys
from pathlib import Path

from app.db.models import Base

BACKEND = Path(__file__).resolve().parents[1]

EXPECTED_COLUMNS = {
    "conversations": {"id", "session_id", "name", "language", "source_page", "started_at",
                      "last_message_at", "lead_status", "summary"},
    "messages": {"id", "conversation_id", "role", "content", "model_used", "tokens_in",
                 "tokens_out", "created_at"},
    "leads": {"id", "conversation_id", "name", "email", "whatsapp", "platform", "market",
              "store_url", "status", "created_at", "notified_at"},
    "kb_versions": {"id", "file", "content_hash", "synced_at"},
}


def test_tables_match_the_plan():
    actual = {name: set(t.columns.keys()) for name, t in Base.metadata.tables.items()}
    assert actual == EXPECTED_COLUMNS


def migration_sql() -> str:
    """The SQL the migration would run, printed without touching a database."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND, capture_output=True, text=True, check=True,
    )
    return result.stdout


def test_migration_creates_every_table_with_its_columns():
    sql = migration_sql()
    for table, columns in EXPECTED_COLUMNS.items():
        assert f"CREATE TABLE {table}" in sql
        for column in columns:
            assert f"{column} " in sql


def test_migration_locks_every_table_with_rls():
    sql = migration_sql()
    for table in [*EXPECTED_COLUMNS, "alembic_version"]:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
