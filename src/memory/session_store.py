# src/memory/session_store.py

import json
import time
import threading
from typing import List, Dict, Any, Optional
from pathlib import Path

from src.config.settings import REDIS_URL, DATA_DIR, ENV
from src.utils.logger import get_logger

logger = get_logger("SessionStore")

# Local fallback store file if Redis is not configured
SESSIONS_BACKUP_FILE = DATA_DIR / "sessions_backup.json"


class SessionStore:
    """
    Manages multi-turn conversation session history.
    Uses Redis when REDIS_URL is provided; otherwise falls back gracefully
    to an in-memory dictionary with local JSON persistence.
    """

    def __init__(self, redis_url: str = REDIS_URL, ttl_seconds: int = 86400 * 7):
        self.redis_url = redis_url
        self.ttl = ttl_seconds
        self.redis_client = None
        self._memory_lock = threading.Lock()
        self._memory_store: Dict[str, List[Dict[str, Any]]] = {}

        if self.redis_url:
            try:
                import redis
                self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
                self.redis_client.ping()
                logger.info(f"Connected to Redis session store at: {self.redis_url}")
            except Exception as e:
                if ENV == "production":
                    error_msg = (
                        f"ENV=production requires a working Redis session store, but connecting "
                        f"to REDIS_URL failed: {e}. Refusing to silently fall back to the "
                        f"single-process-only local file store in production. Fix Redis "
                        f"connectivity, or unset ENV (or set ENV=development) to explicitly "
                        f"accept the local-file fallback."
                    )
                    logger.error(error_msg)
                    raise RuntimeError(error_msg) from e
                logger.warning(f"Could not connect to Redis ({e}). Falling back to in-memory session store.")
                self.redis_client = None
        elif ENV == "production":
            error_msg = (
                "ENV=production requires REDIS_URL to be set (a shared session store is "
                "mandatory once you're running for real, since the local-file fallback is "
                "only safe for a single process). Set REDIS_URL, or unset ENV (or set "
                "ENV=development) to explicitly accept the local-file fallback."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        else:
            logger.warning(
                "No REDIS_URL configured. Using local in-memory session store backed by "
                f"{SESSIONS_BACKUP_FILE}. This is fine for a single process (e.g. `uvicorn` "
                "with no --workers flag), but is NOT safe if you ever run multiple worker "
                "processes: each one loads and rewrites the whole file independently, so "
                "concurrent processes will silently overwrite each other's saved sessions. "
                "Set REDIS_URL before scaling beyond a single worker, or set ENV=production "
                "to make this a hard startup failure instead of a warning."
            )

        # Load existing local sessions if memory fallback is used
        if not self.redis_client:
            self._load_local_sessions()

    def _load_local_sessions(self):
        """Loads sessions from local backup file if it exists."""
        if SESSIONS_BACKUP_FILE.exists():
            try:
                with open(SESSIONS_BACKUP_FILE, "r", encoding="utf-8") as f:
                    self._memory_store = json.load(f)
                logger.info(f"Loaded {len(self._memory_store)} existing sessions from local backup.")
            except Exception as e:
                logger.warning(f"Could not read local sessions backup: {e}")
                self._memory_store = {}

    def _persist_local_sessions(self):
        """Persists in-memory sessions to local file."""
        try:
            if not SESSIONS_BACKUP_FILE.parent.exists():
                SESSIONS_BACKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SESSIONS_BACKUP_FILE, "w", encoding="utf-8") as f:
                json.dump(self._memory_store, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Could not persist sessions to backup file: {e}")

    def save_turn(self, session_id: str, role: str, content: str, language: str = "en"):
        """
        Appends a conversation message to the session history.
        Role can be 'user' or 'assistant'.
        """
        turn = {
            "role": role,
            "content": content,
            "language": language,
            "timestamp": time.time(),
        }

        if self.redis_client:
            try:
                key = f"itcybx:session:{session_id}"
                self.redis_client.rpush(key, json.dumps(turn, ensure_ascii=False))
                self.redis_client.expire(key, self.ttl)
                return
            except Exception as e:
                logger.warning(f"Redis save_turn error: {e}. Falling back to in-memory.")

        with self._memory_lock:
            if session_id not in self._memory_store:
                self._memory_store[session_id] = []
            self._memory_store[session_id].append(turn)
            self._persist_local_sessions()

    def session_exists(self, session_id: str) -> bool:
        """
        True only if this exact id was previously issued and has a record
        (i.e. at least one saved turn). Used to distinguish a real,
        server-issued session id from a well-formed-but-never-issued string
        a caller could pick on their own — format alone (charset/length)
        isn't proof of provenance, only entropy is.
        """
        if self.redis_client:
            try:
                key = f"itcybx:session:{session_id}"
                return bool(self.redis_client.exists(key))
            except Exception as e:
                logger.warning(f"Redis session_exists error: {e}. Falling back to in-memory.")

        with self._memory_lock:
            return session_id in self._memory_store

    def get_history(self, session_id: str, max_turns: int = 30) -> List[Dict[str, Any]]:
        """
        Retrieves the latest conversation history for a session.
        """
        if self.redis_client:
            try:
                key = f"itcybx:session:{session_id}"
                raw_items = self.redis_client.lrange(key, -max_turns, -1)
                return [json.loads(item) for item in raw_items]
            except Exception as e:
                logger.warning(f"Redis get_history error: {e}. Falling back to in-memory.")

        with self._memory_lock:
            history = self._memory_store.get(session_id, [])
            return history[-max_turns:]

    def clear_session(self, session_id: str) -> bool:
        """Clears all conversation turns for a given session."""
        if self.redis_client:
            try:
                key = f"itcybx:session:{session_id}"
                self.redis_client.delete(key)
                return True
            except Exception as e:
                logger.warning(f"Redis clear_session error: {e}")

        with self._memory_lock:
            if session_id in self._memory_store:
                del self._memory_store[session_id]
                self._persist_local_sessions()
                return True
        return False

    def list_all_sessions(self) -> List[str]:
        """Returns all active session IDs."""
        if self.redis_client:
            try:
                keys = self.redis_client.keys("itcybx:session:*")
                return [k.replace("itcybx:session:", "") for k in keys]
            except Exception as e:
                logger.warning(f"Redis list_all_sessions error: {e}")

        with self._memory_lock:
            return list(self._memory_store.keys())


# Global singleton instance
_session_store_instance: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """Returns or initializes the singleton SessionStore."""
    global _session_store_instance
    if _session_store_instance is None:
        _session_store_instance = SessionStore()
    return _session_store_instance


if __name__ == "__main__":
    store = get_session_store()
    test_session = "test_user_123"
    store.save_turn(test_session, "user", "What is the Growth Audit?", "en")
    store.save_turn(test_session, "assistant", "The Growth Audit is a 12-page teardown priced at $150.", "en")
    
    history = store.get_history(test_session)
    print("\n=======================================================")
    print("             SESSION STORE TEST RESULTS                ")
    print("=======================================================")
    print(f"Session: {test_session}")
    print(f"Retrieved {len(history)} turns:")
    for turn in history:
        print(f"  [{turn['role'].upper()}]: {turn['content']}")
    print("=======================================================\n")
