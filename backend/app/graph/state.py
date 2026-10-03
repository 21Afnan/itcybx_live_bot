"""What the bot remembers about one conversation (PLAN.md → "State")."""

from typing import TypedDict

LEAD_FIELDS = ["email", "whatsapp", "platform", "market", "store_url"]
QUALIFY_FIELDS = ["platform", "market", "store_url"]  # asked in this order, one per turn
MAX_MESSAGES = 8  # older messages are folded into `summary`


class ChatState(TypedDict, total=False):
    # Saved between turns
    session_id: str
    language: str  # "en" or "ar"
    name: str
    messages: list[dict]  # last few {"role", "content"}, oldest first
    summary: str  # short summary of older messages
    lead: dict  # email, whatsapp, platform, market, store_url
    lead_status: str  # "none", "partial" or "complete"
    capture_asks: int  # times we asked for email + WhatsApp

    # This turn only
    user_message: str
    interest_signal: bool
    wants_contact: bool
    problems: list[str]  # e.g. ["whatsapp_needs_country_code"]
    lead_just_completed: bool
    instruction: str  # note for the AI about this reply
    reply: str
    actions: list[dict]  # contact buttons to show under the reply
    usage: dict  # model_used, tokens_in, tokens_out, cached_tokens, fallback_used


def new_state(session_id: str, language: str) -> ChatState:
    """State for a brand-new conversation."""
    return ChatState(
        session_id=session_id,
        language=language if language in ("en", "ar") else "en",
        name="",
        messages=[],
        summary="",
        lead={field: "" for field in LEAD_FIELDS},
        lead_status="none",
        capture_asks=0,
    )
