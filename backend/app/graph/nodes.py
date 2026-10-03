"""The six steps of the bot (PLAN.md → "LangGraph flow").

Each visitor message goes:  router → one of greet / qualify / capture_lead /
contact / answer.  qualify, capture_lead and contact only decide what the
reply should add (a note for the AI, contact buttons); answer then writes
the reply with the AI and streams it word by word.

The router uses fixed rules, not AI: cheap, fast and predictable.
"""

from langgraph.types import StreamWriter

from app.config import settings
from app.graph.state import MAX_MESSAGES, QUALIFY_FIELDS, ChatState
from app.leads import extract
from app.llm.models import LLMUnavailable, Usage, stream_reply, summarize

TEXTS = {
    "en": {
        "nice_to_meet": "Nice to meet you, {name}! How can I help you grow your store today?",
        "name_again": "Sorry, I didn't catch that. What's your name?",
        "error": "Something went wrong. You can reach us on WhatsApp or email.",
        "calendly": "Book your Growth Audit",
        "whatsapp": "WhatsApp us",
        "email": "Email us",
        "contact_page": "Contact page",
    },
    "ar": {
        "nice_to_meet": "تشرفنا يا {name}! كيف يمكنني مساعدتك في تنمية متجرك اليوم؟",
        "name_again": "عذرًا، لم ألتقط اسمك. ما اسمك؟",
        "error": "حدث خطأ. يمكنك التواصل معنا عبر واتساب أو البريد الإلكتروني.",
        "calendly": "احجز تقييم النمو",
        "whatsapp": "راسلنا على واتساب",
        "email": "راسلنا بالبريد",
        "contact_page": "صفحة التواصل",
    },
}

QUALIFY_QUESTIONS = {
    "platform": "their e-commerce platform (Shopify, Salla, Zid or other)",
    "market": "their main market (Saudi Arabia, GCC, UK or other)",
    "store_url": "their store's website address",
}


def text(state: ChatState, key: str) -> str:
    return TEXTS[state.get("language", "en")][key]


def contact_buttons(state: ChatState) -> list[dict]:
    """Quick-reply buttons for the contact options that are configured."""
    links = {
        "calendly": settings.calendly_url,
        "whatsapp": settings.whatsapp_url,
        "email": f"mailto:{settings.contact_email}" if settings.contact_email else "",
        "contact_page": settings.contact_page_url,
    }
    return [{"type": t, "label": text(state, t), "url": url} for t, url in links.items() if url]


def lead_status(name: str, lead: dict) -> str:
    """complete = name + email + WhatsApp; partial = we know their name."""
    if name and lead.get("email") and lead.get("whatsapp"):
        return "complete"
    return "partial" if name else "none"


# ---- router -------------------------------------------------------------


def router(state: ChatState) -> dict:
    """Read the new message: pick up lead details and interest signals."""
    message = state["user_message"]
    if not state.get("name"):
        return {"instruction": "", "actions": [], "problems": []}

    found = extract.find(message)
    lead = dict(state["lead"])
    for field in lead:
        if getattr(found, field):
            lead[field] = getattr(found, field)

    before = state.get("lead_status", "none")
    after = lead_status(state["name"], lead)
    return {
        "lead": lead,
        "lead_status": after,
        "lead_just_completed": after == "complete" and before != "complete",
        "interest_signal": extract.shows_interest(message),
        "wants_contact": extract.wants_contact(message),
        "problems": found.problems,
        "instruction": "",
        "actions": [],
    }


def next_step(state: ChatState) -> str:
    """PLAN.md → "Routing rules", in order."""
    if not state.get("name"):
        return "greet"
    complete = state["lead_status"] == "complete"
    if state.get("lead_just_completed"):
        return "contact"
    if state.get("problems"):
        return "capture_lead"  # e.g. WhatsApp number without a country code
    if state.get("interest_signal") and not complete and state.get("capture_asks", 0) < 2:
        return "capture_lead"
    if state.get("wants_contact") or (state.get("interest_signal") and not complete):
        return "contact"  # asked twice already: respect it, just show the options
    if next_qualify_field(state) and state.get("last_step") != "qualify":
        return "qualify"  # never two replies in a row, never the same question twice
    return "answer"


def next_qualify_field(state: ChatState) -> str | None:
    """The first detail we still don't know and haven't asked about yet."""
    asked = state.get("qualify_asked") or []
    return next((f for f in QUALIFY_FIELDS if not state["lead"].get(f) and f not in asked), None)


# ---- greet --------------------------------------------------------------


async def greet(state: ChatState, writer: StreamWriter) -> dict:
    """First message: it is the visitor's name."""
    name = extract.clean_name(state["user_message"])
    if not extract.valid_name(name):
        reply = text(state, "name_again")
        writer({"type": "token", "text": reply})
        return {"reply": reply}

    reply = text(state, "nice_to_meet").format(name=name)
    writer({"type": "token", "text": reply})
    return {
        "name": name,
        "lead_status": "partial",
        "reply": reply,
        # The history must start with a visitor message, so the name goes in too.
        "messages": [
            *state["messages"],
            {"role": "user", "content": state["user_message"]},
            {"role": "assistant", "content": reply},
        ],
    }


# ---- qualify / capture_lead / contact -----------------------------------


def qualify(state: ChatState) -> dict:
    """Ask once for the next missing detail: platform, then market, then store URL."""
    missing = next_qualify_field(state)
    return {
        "instruction": f"After answering, ask ONE short, natural question to learn "
        f"{QUALIFY_QUESTIONS[missing]}. Ask nothing else.",
        "qualify_asked": [*(state.get("qualify_asked") or []), missing],
        "last_step": "qualify",
    }


def capture_lead(state: ChatState) -> dict:
    """Ask for email + WhatsApp (only what is still missing)."""
    if "whatsapp_needs_country_code" in state.get("problems", []):
        note = (
            "The WhatsApp number they gave has no country code. After answering, "
            "ask them to send it again with the country code (for example +966 or +44)."
        )
    else:
        missing = [label for field, label in (("email", "email"), ("whatsapp", "WhatsApp number"))
                   if not state["lead"].get(field)]
        note = (
            f"The visitor is interested. After answering their question, ask for their "
            f"{' and '.join(missing)} so the team can send them a Growth Audit plan. "
            f"Explain why in one short sentence. If they don't want to share it, that's fine."
        )
    return {"instruction": note, "capture_asks": state.get("capture_asks", 0) + 1,
            "last_step": "capture_lead"}


def contact(state: ChatState) -> dict:
    """Show the contact buttons; thank them if the lead just completed."""
    if state.get("lead_just_completed"):
        note = (
            "They have just shared their email and WhatsApp. Thank them by name, say the "
            "team will reach out shortly, and invite them to book their Growth Audit with "
            "the button below. Two sentences at most."
        )
    else:
        note = (
            "Offer the contact options: booking a Growth Audit, WhatsApp, email or the "
            "contact page. Buttons with these links appear below your reply, so don't "
            "write the links out."
        )
    return {"instruction": note, "actions": contact_buttons(state), "last_step": "contact"}


# ---- answer -------------------------------------------------------------


def known_details(state: ChatState) -> str:
    """A short note of what we know, so the AI never re-asks it."""
    details = ", ".join(f"{k}: {v}" for k, v in state["lead"].items() if v) or "none yet"
    note = f"Visitor's name: {state['name']}. Details they've shared: {details}."
    if state.get("summary"):
        note += f"\nEarlier in this chat: {state['summary']}"
    return note


async def answer(state: ChatState, writer: StreamWriter) -> dict:
    """Write the reply with the AI, streaming each piece as it arrives."""
    note = state.get("instruction", "")
    if not note:  # a plain answer: no follow-up questions about their store
        note = ("Do not ask about their platform, market or store website in this reply. "
                "Don't end with a question unless something they said is unclear.")
    instruction = "\n".join([known_details(state), note])
    usage = Usage()
    parts = []
    try:
        async for piece in stream_reply(
            state["user_message"], state["language"], state["messages"], usage,
            instruction=instruction,
        ):
            parts.append(piece)
            writer({"type": "token", "text": piece})
    except LLMUnavailable:
        writer({"type": "error", "code": "unavailable", "message": text(state, "error")})
        return {"reply": text(state, "error"), "actions": contact_buttons(state), "usage": {}}

    reply = "".join(parts)
    messages = [
        *state["messages"],
        {"role": "user", "content": state["user_message"]},
        {"role": "assistant", "content": reply},
    ]
    summary = state.get("summary", "")
    if len(messages) > MAX_MESSAGES + 4:  # fold the oldest into the summary, a few at a time
        cut = len(messages) - MAX_MESSAGES
        try:
            summary = await summarize(summary, messages[:cut], state["language"])
        except LLMUnavailable:
            pass  # keep the old summary; trimming still happens
        messages = messages[cut:]

    last = state.get("last_step") if state.get("instruction") else "answer"
    return {"reply": reply, "messages": messages, "summary": summary, "usage": usage.__dict__,
            "last_step": last}
