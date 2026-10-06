"""Reading and saving chats in Supabase."""

import uuid
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.db.engine import db_session
from app.db.models import Conversation, KbVersion, Lead, Message
from app.graph.state import MAX_MESSAGES, ChatState, new_state


async def create_conversation(session_id: str, language: str, source_page: str | None) -> None:
    async with db_session() as db:
        db.add(Conversation(session_id=uuid.UUID(session_id), language=language,
                            source_page=source_page))
        await db.commit()


async def find_conversation(session_id: str) -> Conversation | None:
    async with db_session() as db:
        return await db.scalar(
            select(Conversation).where(Conversation.session_id == uuid.UUID(session_id))
        )


async def rebuild_state(conversation: Conversation) -> ChatState:
    """Recreate the bot's memory from Supabase (used when Redis has forgotten it)."""
    async with db_session() as db:
        lead = await db.scalar(select(Lead).where(Lead.conversation_id == conversation.id))
        rows = (await db.scalars(
            select(Message).where(Message.conversation_id == conversation.id)
            .order_by(Message.sequence.desc()).limit(MAX_MESSAGES)
        )).all()
    state = new_state(str(conversation.session_id), conversation.language)
    state.update(
        name=conversation.name or "",
        summary=conversation.summary or "",
        lead_status=conversation.lead_status,
        messages=[{"role": m.role, "content": m.content} for m in reversed(rows)],
        capture_asks=conversation.capture_asks,
        qualify_asked=conversation.qualify_asked or [],
        last_step=conversation.last_step,
    )
    if lead:
        state["lead"] = {f: getattr(lead, f) or "" for f in state["lead"]}
    if state["messages"] and state["messages"][0]["role"] != "user":
        state["messages"] = state["messages"][1:]  # history must start with the visitor
    return state


async def save_turn(state: ChatState, user_message: str, reply: str, usage: dict) -> str:
    """Save the visitor's message and the bot's reply. Returns the reply's id."""
    reply_id = uuid.uuid4()
    async with db_session() as db:
        conversation = await db.scalar(
            select(Conversation).where(Conversation.session_id == uuid.UUID(state["session_id"]))
        )
        db.add(Message(conversation_id=conversation.id, role="user", content=user_message))
        # Flush the visitor first so identity values encode the turn order.
        await db.flush()
        db.add(Message(
            id=reply_id, conversation_id=conversation.id, role="assistant", content=reply,
            model_used=usage.get("model_used") or None,
            tokens_in=usage.get("tokens_in"), tokens_out=usage.get("tokens_out"),
        ))
        await db.execute(
            update(Conversation).where(Conversation.id == conversation.id).values(
                name=state.get("name") or None,
                lead_status=state.get("lead_status", "none"),
                summary=state.get("summary") or None,
                last_message_at=func.now(),
                capture_asks=state.get("capture_asks", 0),
                qualify_asked=state.get("qualify_asked") or [],
                last_step=state.get("last_step", ""),
            )
        )
        if state.get("name"):
            await db.execute(lead_upsert(conversation.id, state))
        await db.commit()
    return str(reply_id)


def lead_upsert(conversation_id: uuid.UUID, state: ChatState):
    """Insert or update the chat's lead (partial leads are kept too)."""
    values = {
        "name": state["name"],
        **{f: state["lead"].get(f) or None for f in ("email", "whatsapp", "platform", "market", "store_url")},
        "status": "complete" if state.get("lead_status") == "complete" else "partial",
    }
    stmt = insert(Lead).values(id=uuid.uuid4(), conversation_id=conversation_id, **values)
    return stmt.on_conflict_do_update(index_elements=[Lead.conversation_id], set_=values)


async def record_kb_versions(hashes: dict[str, str]) -> None:
    """Save a new fingerprint for each file that was written."""
    if not hashes:
        return
    async with db_session() as db:
        db.add_all(KbVersion(file=f, content_hash=h) for f, h in hashes.items())
        await db.commit()


ALERT_COLUMNS = {"email": Lead.emailed_at, "sheet": Lead.sheet_added_at}


@asynccontextmanager
async def alert_lock(session_id: str):
    """Serialize alert attempts across workers; release on disconnect or exit."""
    key = int.from_bytes(hashlib.sha256(f"lead-alert:{session_id}".encode()).digest()[:8],
                         "big", signed=True)
    async with db_session() as db:
        acquired = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})
        yield bool(acquired)


def _lead_of(session_id: str):
    """SELECT of the lead row for a chat."""
    return select(Lead).join(Conversation, Lead.conversation_id == Conversation.id).where(
        Conversation.session_id == uuid.UUID(session_id))


async def sent_alerts(session_id: str) -> set[str]:
    """Which lead alerts ("email", "sheet") already went out for this chat."""
    async with db_session() as db:
        lead = await db.scalar(_lead_of(session_id))
    if lead is None:
        return set()
    return {channel for channel, column in ALERT_COLUMNS.items() if getattr(lead, column.key)}


async def mark_alert_sent(session_id: str, channel: str) -> None:
    async with db_session() as db:
        lead = await db.scalar(_lead_of(session_id))
        if lead:
            setattr(lead, ALERT_COLUMNS[channel].key, func.now())
            await db.commit()


async def mark_lead_notified(session_id: str) -> None:
    async with db_session() as db:
        lead = await db.scalar(_lead_of(session_id))
        if lead:
            lead.notified_at = func.now()
            await db.commit()


async def unnotified_leads(min_age: timedelta, max_age: timedelta) -> list[Conversation]:
    """Chats with a complete lead whose alerts didn't all go out.

    Age is counted from the chat's last message (a lead completes on a
    message), so a chat still within `min_age` may have its first alert
    attempt running and is left alone.
    """
    now = datetime.now(timezone.utc)
    async with db_session() as db:
        return list((await db.scalars(
            select(Conversation).join(Lead, Lead.conversation_id == Conversation.id).where(
                Lead.status == "complete", Lead.notified_at.is_(None),
                Conversation.last_message_at <= now - min_age,
                Conversation.last_message_at >= now - max_age,
            )
        )).all())
