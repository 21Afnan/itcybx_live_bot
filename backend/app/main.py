"""The API server (PLAN.md → "API contract").

    POST /session   start or resume a chat
    POST /chat      send a message; the reply streams back (Server-Sent Events)
    GET  /widget.js the chat widget for the website
    GET  /health    are Supabase and Redis working?
"""

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import sessions
from app.db import repo
from app.config import settings
from app.db.engine import get_engine
from app.graph.build import GREETING, run_turn
from app.graph.state import new_state
from app.knowledge.sync import start_scheduler
from app.leads.notify import notify_team
from app.security import ratelimit

CHECK_TIMEOUT_SECONDS = 10  # the first connection to Supabase can take a few seconds

WELCOME_BACK = {
    "en": "Welcome back, {name}! How can I help you today?",
    "ar": "أهلًا بعودتك يا {name}! كيف يمكنني مساعدتك اليوم؟",
}

UNAVAILABLE = {
    "en": "Something went wrong. You can reach us on WhatsApp or email.",
    "ar": "حدث خطأ. يمكنك التواصل معنا عبر واتساب أو البريد الإلكتروني.",
}

TOO_FAST = {
    "en": "You're sending messages too fast. Please wait a moment.",
    "ar": "ترسل الرسائل بسرعة كبيرة. يرجى الانتظار قليلًا.",
}
TOO_LONG = {
    "en": "That message is too long. Please keep it under {n} characters.",
    "ar": "الرسالة طويلة جدًا. يرجى ألا تتجاوز {n} حرفًا.",
}

log = logging.getLogger("chatbot")
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the weekly website check with the server (not in tests)."""
    scheduler = start_scheduler() if settings.app_env != "test" else None
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="IT Cybx Chatbot", lifespan=lifespan)

# Browsers on itcybx.co.uk may call the API; the check below rejects the rest.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def allowed_origin(request: Request) -> None:
    """403 for calls from any other website (PLAN.md → "CORS").

    Requests without an Origin header (curl, uptime monitors) are not from a
    browser on another site, so they pass; the rate limits still apply.
    """
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in settings.allowed_origins_list:
        raise HTTPException(403, "Origin not allowed")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def sse_error(status: int, code: str, message: str) -> Response:
    """An error as both an HTTP status and an SSE `error` event, so the widget
    can treat it like any other reply."""
    return Response(sse("error", {"code": code, "message": message}), status_code=status,
                    media_type="text/event-stream")


# ---- /session -----------------------------------------------------------


class SessionRequest(BaseModel):
    session_id: uuid.UUID | None = None
    language: Literal["en", "ar"] = "en"
    page_url: str | None = Field(default=None, max_length=2000)


async def load_state(session_id: str):
    """The chat's memory: from Redis, or rebuilt from Supabase. None if unknown."""
    state = await sessions.load(session_id)
    if state is None:
        conversation = await repo.find_conversation(session_id)
        if conversation is None:
            return None
        state = await repo.rebuild_state(conversation)
        await sessions.save(state)
    return state


@app.post("/session", dependencies=[Depends(allowed_origin)])
async def start_session(body: SessionRequest, request: Request):
    """Resume the visitor's chat if we know it, otherwise start a new one."""
    if not await ratelimit.allow(f"session:ip:{client_ip(request)}"):
        raise HTTPException(429, TOO_FAST[body.language])
    if body.session_id:
        state = await load_state(str(body.session_id))
        if state:
            name = state.get("name") or None
            greeting = (WELCOME_BACK[state["language"]].format(name=name) if name
                        else GREETING[state["language"]])
            return {"session_id": state["session_id"], "name": name, "greeting": greeting}

    session_id = str(uuid.uuid4())
    await repo.create_conversation(session_id, body.language, body.page_url)
    await sessions.save(new_state(session_id, body.language))
    return {"session_id": session_id, "name": None, "greeting": GREETING[body.language]}


# ---- /chat --------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: uuid.UUID
    message: str = Field(min_length=1)


def sse(event: str, data: dict) -> str:
    """One Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


running_turns: set[asyncio.Task] = set()  # keeps background work alive until it finishes


def background(coro) -> None:
    """Run work after the reply without making the visitor wait for it."""
    task = asyncio.create_task(coro)
    running_turns.add(task)
    task.add_done_callback(running_turns.discard)


async def process_turn(state: dict, message: str, out: asyncio.Queue) -> None:
    """Run the bot on one message, putting SSE events on `out`, then save it.

    Runs as its own task, so the chat is still saved if the visitor closes
    the page halfway through the reply.
    """
    try:
        final = None
        try:
            async for event in run_turn(state, message):
                if event["type"] == "token":
                    out.put_nowait(sse("token", {"text": event["text"]}))
                elif event["type"] == "error":
                    out.put_nowait(sse("error", {"code": event["code"], "message": event["message"]}))
                elif event["type"] == "state":
                    final = event["state"]
        except Exception:
            log.exception("Bot failed on a message")
            out.put_nowait(sse("error", {"code": "unavailable", "message": UNAVAILABLE[state["language"]]}))
            return

        if final.get("actions"):
            out.put_nowait(sse("actions", {"buttons": final["actions"]}))
        message_id = None
        try:
            await sessions.save(final)
            message_id = await repo.save_turn(final, message, final.get("reply", ""),
                                              final.get("usage") or {})
        except Exception:
            log.exception("Could not save the message")  # the visitor already has the reply
        if final.get("lead_just_completed"):
            background(notify_team(final))
        out.put_nowait(sse("done", {"message_id": message_id,
                                    "lead_status": final.get("lead_status", "none")}))
    finally:
        await sessions.unlock(state["session_id"])
        out.put_nowait(None)  # end of stream


async def reply_events(state: dict, message: str):
    """Stream the events of one turn to the visitor as they happen."""
    out: asyncio.Queue = asyncio.Queue()
    background(process_turn(state, message, out))
    while (item := await out.get()) is not None:
        yield item


@app.post("/chat", dependencies=[Depends(allowed_origin)])
async def chat(body: ChatRequest, request: Request):
    """Send one message. The reply streams back word by word."""
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "Message is empty")
    state = await load_state(str(body.session_id))
    if state is None:
        raise HTTPException(404, "Unknown session_id")
    language = state["language"]
    if len(message) > settings.max_message_chars:
        return sse_error(400, "too_long", TOO_LONG[language].format(n=settings.max_message_chars))
    if not (await ratelimit.allow(f"chat:ip:{client_ip(request)}")
            and await ratelimit.allow(f"chat:session:{state['session_id']}")):
        return sse_error(429, "rate_limited", TOO_FAST[language])
    if not await sessions.lock(state["session_id"]):
        raise HTTPException(429, "Please wait for the current reply")
    return StreamingResponse(
        reply_events(state, message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---- /widget.js ----------------------------------------------------------

WIDGET_FILE = Path(__file__).resolve().parents[2] / "widget" / "widget.js"  # /widget in Docker


@app.get("/widget.js")
async def widget():
    """The chat widget the website loads with one script tag."""
    return FileResponse(WIDGET_FILE, media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=300"})


# ---- /health ------------------------------------------------------------


async def database_status() -> str:
    """Ask Supabase a tiny question. "ok", or the error's type name."""

    async def ping():
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(ping(), CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception as e:
        return type(e).__name__  # never the message: it may contain the connection string


async def redis_status() -> str:
    """Ping Redis. "ok", or the error's type name."""
    try:
        await asyncio.wait_for(sessions.get_redis().ping(), CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception as e:
        return type(e).__name__


@app.get("/health")
async def health(response: Response):
    """Say whether Supabase and Redis are working."""
    db = await database_status()
    redis = await redis_status()
    all_ok = db == "ok" and redis == "ok"

    if not all_ok:
        response.status_code = 503  # tells uptime monitors something is wrong

    return {"status": "ok" if all_ok else "degraded", "db": db, "redis": redis}
