# src/api/main.py

import os
import re
import sys
import secrets
import time
import asyncio
import threading
import collections
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

# Ensure root directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.agent.graph import get_agent
from src.memory.session_store import get_session_store
from src.config.settings import (
    LLM_MODEL,
    EMBEDDING_MODEL,
    PINECONE_INDEX_NAME,
    REDIS_URL,
    ADMIN_API_KEY,
)
from src.utils.logger import get_logger

logger = get_logger("FastAPI")

# Initialize FastAPI App
app = FastAPI(
    title="IT Cybx Live Bot API",
    description="Production-grade bilingual conversational agent API for itcybx.co.uk",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for WordPress site embedding and local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permits embedding on any WordPress domain or local dev
    allow_credentials=False,  # Must be False with a wildcard origin (browsers reject "*" + credentials); the widget uses no cookies/auth headers
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount frontend directory for serving static widget files
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/widget", StaticFiles(directory=str(FRONTEND_DIR)), name="widget")


# =====================================================================
# PYDANTIC SCHEMAS
# =====================================================================

# Format of a server-issued session id (see _new_session_id below). A
# client-supplied id that doesn't match this shape is never trusted as an
# existing session — it's replaced with a freshly generated one instead,
# so a low-entropy or guessed id can never be used to attach to someone
# else's conversation.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")

MAX_MESSAGE_LENGTH = 4000


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH, description="The user's input message in English or Arabic.")
    session_id: Optional[str] = Field(None, max_length=128, description="Server-issued session ID from a prior response. Omit to start a new session.")
    language: Literal["auto", "en", "ar"] = Field("auto", description="Language mode: 'auto', 'en', or 'ar'.")

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("message cannot be blank or whitespace-only")
        return stripped


class ChatResponse(BaseModel):
    response: str
    session_id: str
    language: str
    timestamp: float
    status: str = "success"


def require_admin_key(x_admin_api_key: Optional[str] = Header(None)):
    """
    Guards read/delete access to session transcripts. Fails CLOSED: if
    ADMIN_API_KEY isn't configured on the server, these endpoints are
    refused entirely rather than left open, since chat transcripts can
    contain visitor PII.
    """
    if not ADMIN_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="This endpoint is disabled until ADMIN_API_KEY is configured on the server.",
        )
    if not x_admin_api_key or x_admin_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid X-Admin-Api-Key header.")


# =====================================================================
# CORE ENDPOINTS
# =====================================================================

@app.get("/", tags=["General"])
async def root():
    """Serves the full-screen ChatGPT-style conversational interface."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {
        "service": "IT Cybx Live Bot API",
        "status": "active",
        "version": "1.0.0",
        "documentation": "/docs",
    }


@app.get("/health", tags=["General"])
async def health_check():
    """Performs real-time health verification of core components."""
    try:
        agent = get_agent()
        session_store = get_session_store()
        return {
            "status": "healthy",
            "llm_model": LLM_MODEL,
            "embedding_model": EMBEDDING_MODEL,
            "pinecone_index": PINECONE_INDEX_NAME,
            "redis_connected": session_store.redis_client is not None,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Service unhealthy: {str(e)}")


def _new_session_id() -> str:
    """Cryptographically random, unguessable session id (~256 bits)."""
    return secrets.token_urlsafe(32)


# The agent's LLM/embedding/vector-store calls, and the local-file session
# store fallback, are all synchronous (blocking) network/disk I/O. Calling
# them directly in an async route would tie up that worker's whole event
# loop for the duration of one slow request, stalling every other request
# on the same worker. Mitigations: (1) run the blocking work in a thread
# pool via run_in_threadpool so the event loop stays free while it waits,
# (2) bound how many can run at once, and (3) cap how long any one can take.
MAX_CONCURRENT_CHAT_TURNS = 10
CHAT_REQUEST_DEADLINE_SECONDS = 45
_chat_concurrency_limiter = asyncio.Semaphore(MAX_CONCURRENT_CHAT_TURNS)

# Per-session lock: serializes overlapping requests for the SAME session_id
# (e.g. a double-click send, a client retry, or a malicious duplicate) so
# they can't interleave their read-history / save-turn / invoke-agent steps
# and corrupt turn ordering. Different sessions are never blocked by each
# other. Locks are created lazily and intentionally never removed; for a
# small bot's session volume this is a few hundred bytes each, not a
# meaningful leak, but a periodic sweep would be the next step at scale.
_session_locks: Dict[str, threading.Lock] = {}
_session_locks_guard = threading.Lock()


def _get_session_lock(session_id: str) -> threading.Lock:
    with _session_locks_guard:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _session_locks[session_id] = lock
        return lock


# Basic per-IP abuse control. A concurrency cap alone doesn't stop one
# client from sending many requests in sequence; this bounds sustained
# volume from a single source. In-memory / per-process only — like the
# local session store fallback, this resets on restart and isn't shared
# across multiple worker processes. Fine for a small single-worker
# deployment; a real production gate at scale needs a shared store (e.g.
# Redis) for this too.
RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60
_rate_limit_buckets: Dict[str, collections.deque] = {}
_rate_limit_guard = threading.Lock()


def _check_rate_limit(client_key: str) -> bool:
    """Returns True if this request is allowed, False if the client should be rate-limited."""
    now = time.time()
    with _rate_limit_guard:
        bucket = _rate_limit_buckets.setdefault(client_key, collections.deque())
        while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
            return False
        bucket.append(now)
        return True


def _run_chat_turn_sync(supplied_id: str, user_msg: str, req_lang: str):
    """
    All blocking work for one turn, including resolving the session id.
    Runs off the event loop via run_in_threadpool.
    """
    agent = get_agent()
    session_store = get_session_store()

    # Only trust a client-supplied id if it (a) has the shape of one we
    # issue, AND (b) was actually issued by us before (session_exists).
    # Shape alone isn't provenance — a well-formed-but-never-issued string
    # could otherwise be picked by any caller and used as if it were a real
    # session, defeating the point of a high-entropy server-issued id.
    if _SESSION_ID_RE.match(supplied_id) and session_store.session_exists(supplied_id):
        session_id = supplied_id
    else:
        session_id = _new_session_id()

    # Serialize this session's ENTIRE turn (history read through both saves)
    # against any other concurrent request for the same session_id. This is
    # what stops a double-click, client retry, or duplicate request from
    # interleaving reads/writes and corrupting turn order — the second
    # request simply waits for the first to fully finish before it starts.
    with _get_session_lock(session_id):
        prior_history = session_store.get_history(session_id)
        session_store.save_turn(session_id, role="user", content=user_msg, language=req_lang)

        bot_response = agent.chat(
            user_message=user_msg,
            thread_id=session_id,
            language=req_lang,
            history=prior_history,
        )

        has_arabic = any('؀' <= char <= 'ۿ' or 'ݐ' <= char <= 'ݿ' for char in bot_response)
        detected_lang = "ar" if has_arabic else "en"
        session_store.save_turn(session_id, role="assistant", content=bot_response, language=detected_lang)

    return session_id, bot_response, detected_lang


@app.post("/api/chat", response_model=ChatResponse, tags=["Chat"])
async def handle_chat(payload: ChatRequest, request: Request):
    """
    Main chat endpoint for conversation turns with the LangGraph agent.
    Maintains session history and executes tools automatically.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {RATE_LIMIT_MAX_REQUESTS} requests per {RATE_LIMIT_WINDOW_SECONDS}s.",
        )

    supplied_id = payload.session_id.strip() if payload.session_id else ""
    # Actual session id resolution (shape + provenance check) happens inside
    # _run_chat_turn_sync, off the event loop. This is only a display
    # placeholder for the error/timeout paths below, where the real
    # resolution may never have completed.
    fallback_display_id = supplied_id if _SESSION_ID_RE.match(supplied_id) else _new_session_id()
    user_msg = payload.message
    req_lang = payload.language

    logger.info(f"Incoming /api/chat [session~={fallback_display_id}, lang={req_lang}, ip={client_ip}]: (len={len(user_msg)} chars)")

    is_ar = req_lang == "ar" or any('\u0600' <= c <= '\u06FF' for c in user_msg)

    try:
        async with _chat_concurrency_limiter:
            session_id, bot_response, detected_lang = await asyncio.wait_for(
                run_in_threadpool(_run_chat_turn_sync, supplied_id, user_msg, req_lang),
                timeout=CHAT_REQUEST_DEADLINE_SECONDS,
            )

        return ChatResponse(
            response=bot_response,
            session_id=session_id,
            language=detected_lang,
            timestamp=time.time(),
            status="success",
        )

    except asyncio.TimeoutError:
        logger.error(f"Chat turn for session ~{fallback_display_id} exceeded the {CHAT_REQUEST_DEADLINE_SECONDS}s deadline.")
        fallback_msg = (
            "\u0646\u0639\u062A\u0630\u0631\u060C \u0627\u0633\u062A\u063A\u0631\u0642\u062A \u0627\u0644\u0625\u062C\u0627\u0628\u0629 \u0648\u0642\u062A\u0627\u064B \u0623\u0637\u0648\u0644 \u0645\u0646 \u0627\u0644\u0645\u062A\u0648\u0642\u0639. \u064A\u0631\u062C\u0649 \u0627\u0644\u0645\u062D\u0627\u0648\u0644\u0629 \u0645\u0631\u0629 \u0623\u062E\u0631\u0649 \u0623\u0648 \u0627\u0644\u062A\u0648\u0627\u0635\u0644 \u0645\u0639\u0646\u0627 \u0639\u0628\u0631 itcybx@gmail.com."
            if is_ar
            else "Sorry, that took longer than expected. Please try again, or contact us at itcybx@gmail.com."
        )
        return ChatResponse(
            response=fallback_msg,
            session_id=fallback_display_id,
            language="ar" if is_ar else "en",
            timestamp=time.time(),
            status="timeout",
        )

    except Exception as e:
        logger.error(f"Error processing chat request for session ~{fallback_display_id}: {e}")
        fallback_msg = (
            "نعتذر، نواجه ضغطاً مؤقتاً في الخدمة حالياً. يمكنك التواصل مباشرة مع فريقنا عبر itcybx@gmail.com."
            if is_ar
            else "We are currently experiencing high traffic. For immediate assistance, please contact our team at itcybx@gmail.com."
        )
        return ChatResponse(
            response=fallback_msg,
            session_id=fallback_display_id,
            language="ar" if is_ar else "en",
            timestamp=time.time(),
            status="fallback",
        )


@app.get("/api/session/{session_id}", tags=["Chat"], dependencies=[Depends(require_admin_key)])
async def get_session_history(session_id: str):
    """Retrieves conversation history for a given session."""
    session_store = get_session_store()
    history = session_store.get_history(session_id)
    return {
        "session_id": session_id,
        "turns_count": len(history),
        "history": history,
    }


@app.delete("/api/session/{session_id}", tags=["Chat"], dependencies=[Depends(require_admin_key)])
async def delete_session(session_id: str):
    """Resets conversation memory for a given session."""
    session_store = get_session_store()
    cleared = session_store.clear_session(session_id)
    return {
        "session_id": session_id,
        "cleared": cleared,
        "message": "Session conversation history cleared.",
    }


# =====================================================================
# WIDGET DEMO REDIRECT
# =====================================================================

@app.get("/demo", tags=["General"])
async def demo_page():
    """Serves the test demo HTML page for the embedded widget."""
    demo_file = FRONTEND_DIR / "index.html"
    if demo_file.exists():
        return FileResponse(str(demo_file))
    return JSONResponse(status_code=404, content={"error": "Demo file not found."})


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    reload_mode = os.environ.get("ENV", "development").lower() == "development"
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=port, reload=reload_mode)
