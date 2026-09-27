# src/api/main.py

import os
import sys
import uuid
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field

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

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="The user's input message in English or Arabic.")
    session_id: Optional[str] = Field(None, description="Unique session ID for multi-turn history. Generated if empty.")
    language: Optional[str] = Field("auto", description="Language mode: 'auto', 'en', or 'ar'.")


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


@app.post("/api/chat", response_model=ChatResponse, tags=["Chat"])
async def handle_chat(payload: ChatRequest):
    """
    Main chat endpoint for conversation turns with the LangGraph agent.
    Maintains session history and executes tools automatically.
    """
    session_id = payload.session_id.strip() if payload.session_id else f"web_{uuid.uuid4().hex[:10]}"
    user_msg = payload.message.strip()
    req_lang = payload.language or "auto"

    logger.info(f"Incoming /api/chat [session={session_id}, lang={req_lang}]: '{user_msg}'")

    try:
        agent = get_agent()
        session_store = get_session_store()

        # 1. Load prior turns (Redis-backed, or local-file fallback) BEFORE
        #    appending this turn, so it can be replayed as conversation context.
        #    This is what makes multi-turn memory survive server restarts and
        #    work consistently across multiple worker processes, instead of
        #    relying solely on LangGraph's in-process, per-worker MemorySaver.
        prior_history = session_store.get_history(session_id)

        # 2. Save user turn to session history
        session_store.save_turn(session_id, role="user", content=user_msg, language=req_lang)

        # 3. Invoke LangGraph agent with the durable history as context
        bot_response = agent.chat(
            user_message=user_msg,
            thread_id=session_id,
            language=req_lang,
            history=prior_history,
        )

        # 4. Detect language returned for response metadata
        has_arabic = any('\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F' for char in bot_response)
        detected_lang = "ar" if has_arabic else "en"

        # 5. Save assistant response to session history
        session_store.save_turn(session_id, role="assistant", content=bot_response, language=detected_lang)

        return ChatResponse(
            response=bot_response,
            session_id=session_id,
            language=detected_lang,
            timestamp=time.time(),
            status="success",
        )

    except Exception as e:
        logger.error(f"Error processing chat request for session {session_id}: {e}")
        is_ar = req_lang == "ar" or any('\u0600' <= c <= '\u06FF' for c in user_msg)
        fallback_msg = (
            "نعتذر، نواجه ضغطاً مؤقتاً في الخدمة حالياً. يمكنك التواصل مباشرة مع فريقنا عبر info@itcybx.co.uk أو +44 793 389 5500."
            if is_ar
            else "We are currently experiencing high traffic. For immediate assistance, please contact our team at info@itcybx.co.uk or +44 793 389 5500."
        )
        return ChatResponse(
            response=fallback_msg,
            session_id=session_id,
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
