"""Reading and saving chats in Supabase."""

import uuid

from sqlalchemy import func, select, update

from app.db.engine import db_session
from app.db.models import Conversation, Message
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
        rows = (await db.scalars(
            select(Message).where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc()).limit(MAX_MESSAGES)
        )).all()
    state = new_state(str(conversation.session_id), conversation.language)
    state.update(
        name=conversation.name or "",
        summary=conversation.summary or "",
        lead_status=conversation.lead_status,
        messages=[{"role": m.role, "content": m.content} for m in reversed(rows)],
    )
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
            )
        )
        await db.commit()
    return str(reply_id)
