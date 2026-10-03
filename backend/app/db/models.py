"""The 4 database tables (PLAN.md → "Supabase tables").

Tables are created and changed only through Alembic migrations
(app/db/migrations), never by hand in the Supabase dashboard.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def created_now() -> Mapped[datetime]:
    """A timestamp column filled in by the database when the row is added."""
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Conversation(Base):
    """One chat with one visitor."""

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("language IN ('en', 'ar')", name="language_valid"),
        CheckConstraint("lead_status IN ('none', 'partial', 'complete')", name="lead_status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(60))
    language: Mapped[str] = mapped_column(String(2), server_default="en")
    source_page: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = created_now()
    last_message_at: Mapped[datetime] = created_now()
    lead_status: Mapped[str] = mapped_column(String(10), server_default="none")
    summary: Mapped[str | None] = mapped_column(Text)


class Message(Base):
    """One message in a chat, from the visitor or the bot."""

    __tablename__ = "messages"
    __table_args__ = (CheckConstraint("role IN ('user', 'assistant')", name="role_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    model_used: Mapped[str | None] = mapped_column(String(100))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_now()


class Lead(Base):
    """Contact details collected in a chat. One lead per conversation."""

    __tablename__ = "leads"
    __table_args__ = (CheckConstraint("status IN ('partial', 'complete')", name="status_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    name: Mapped[str] = mapped_column(String(60))
    email: Mapped[str | None] = mapped_column(String(254))
    whatsapp: Mapped[str | None] = mapped_column(String(20))
    platform: Mapped[str | None] = mapped_column(String(20))
    market: Mapped[str | None] = mapped_column(String(20))
    store_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="partial")
    created_at: Mapped[datetime] = created_now()
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KbVersion(Base):
    """A record of each knowledge file version the weekly sync saw."""

    __tablename__ = "kb_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    file: Mapped[str] = mapped_column(String(200), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    synced_at: Mapped[datetime] = created_now()
