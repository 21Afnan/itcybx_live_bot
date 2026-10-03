"""Create the 4 tables and lock them with Row Level Security.

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# RLS on with no policies: Supabase's public API cannot read or write these
# tables. The bot connects as the database owner, so it is not affected.
# alembic_version is included because it also lives in the public schema.
LOCKED_TABLES = ["conversations", "messages", "leads", "kb_versions", "alembic_version"]


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(60)),
        sa.Column("language", sa.String(2), server_default="en", nullable=False),
        sa.Column("source_page", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("lead_status", sa.String(10), server_default="none", nullable=False),
        sa.Column("summary", sa.Text()),
        sa.CheckConstraint("language IN ('en', 'ar')", name="language_valid"),
        sa.CheckConstraint("lead_status IN ('none', 'partial', 'complete')", name="lead_status_valid"),
    )
    op.create_index("ix_conversations_session_id", "conversations", ["session_id"], unique=True)

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_used", sa.String(100)),
        sa.Column("tokens_in", sa.Integer()),
        sa.Column("tokens_out", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="role_valid"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "leads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("email", sa.String(254)),
        sa.Column("whatsapp", sa.String(20)),
        sa.Column("platform", sa.String(20)),
        sa.Column("market", sa.String(20)),
        sa.Column("store_url", sa.Text()),
        sa.Column("status", sa.String(10), server_default="partial", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('partial', 'complete')", name="status_valid"),
    )

    op.create_table(
        "kb_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("file", sa.String(200), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_kb_versions_file", "kb_versions", ["file"])

    for table in LOCKED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("kb_versions")
    op.drop_table("leads")
    op.drop_table("messages")
    op.drop_table("conversations")
