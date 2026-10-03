"""Tests for /session and /chat, with fake Redis, Supabase and AI."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app import main, sessions
from app.graph import nodes

pytestmark = pytest.mark.skipif(
    __import__("sys").version_info < (3, 11), reason="LangGraph streaming needs Python 3.11+ (Docker has 3.12)"
)


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture
def api(monkeypatch):
    """A test client with everything outside the app faked."""
    redis = FakeRedis()
    saved = {"conversations": {}, "turns": []}
    monkeypatch.setattr(sessions, "get_redis", lambda: redis)

    async def create_conversation(session_id, language, source_page):
        saved["conversations"][session_id] = {"language": language, "source_page": source_page}

    async def find_conversation(session_id):
        return None

    async def save_turn(state, user_message, reply, usage):
        saved["turns"].append({"user": user_message, "reply": reply, "usage": usage})
        return "msg-1"

    async def fake_ai(question, language, history, usage, instruction=""):
        usage.model_used = "fake-model"
        for word in ["The audit ", "is $150."]:
            yield word

    monkeypatch.setattr(main.repo, "create_conversation", create_conversation)
    monkeypatch.setattr(main.repo, "find_conversation", find_conversation)
    monkeypatch.setattr(main.repo, "save_turn", save_turn)
    async def notify_team(state):
        saved.setdefault("alerts", []).append(state["lead"]["email"])

    monkeypatch.setattr(nodes, "stream_reply", fake_ai)
    monkeypatch.setattr(main, "notify_team", notify_team)
    client = TestClient(main.app)
    client.redis, client.saved = redis, saved
    return client


def events(resp) -> list[tuple[str, dict]]:
    """Parse an SSE response into (event, data) pairs."""
    out = []
    for block in resp.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_new_session(api):
    resp = api.post("/session", json={"session_id": None, "language": "en",
                                      "page_url": "https://itcybx.co.uk/pricing/"})
    body = resp.json()
    assert resp.status_code == 200
    assert body["name"] is None
    assert body["greeting"] == "Hi! I'm the IT Cybx assistant. What's your name?"
    assert api.saved["conversations"][body["session_id"]]["source_page"] == "https://itcybx.co.uk/pricing/"


def test_arabic_session_greets_in_arabic(api):
    assert api.post("/session", json={"language": "ar"}).json()["greeting"].startswith("أهلًا!")


def test_chat_streams_tokens_then_done(api):
    sid = api.post("/session", json={"language": "en"}).json()["session_id"]
    api.post("/chat", json={"session_id": sid, "message": "Sara"})
    resp = api.post("/chat", json={"session_id": sid, "message": "How much is the audit?"})

    assert resp.headers["content-type"].startswith("text/event-stream")
    got = events(resp)
    assert [e for e, _ in got] == ["token", "token", "done"]
    assert "".join(d["text"] for e, d in got if e == "token") == "The audit is $150."
    assert got[-1][1] == {"message_id": "msg-1", "lead_status": "partial"}
    assert api.saved["turns"][-1]["usage"]["model_used"] == "fake-model"


def test_returning_visitor_resumes_with_name(api):
    sid = api.post("/session", json={"language": "en"}).json()["session_id"]
    api.post("/chat", json={"session_id": sid, "message": "My name is Sara"})
    body = api.post("/session", json={"session_id": sid, "language": "en"}).json()
    assert body["session_id"] == sid
    assert body["name"] == "Sara"
    assert body["greeting"] == "Welcome back, Sara! How can I help you today?"


def test_complete_lead_sends_actions_before_done(api, monkeypatch):
    monkeypatch.setattr(nodes.settings, "calendly_url", "https://calendly.com/x")
    sid = api.post("/session", json={"language": "en"}).json()["session_id"]
    api.post("/chat", json={"session_id": sid, "message": "Sara"})
    got = events(api.post("/chat", json={"session_id": sid, "message": "sara@x.com +966501234567"}))
    names = [e for e, _ in got]
    assert names[-2:] == ["actions", "done"]
    assert got[-2][1]["buttons"][0]["type"] == "calendly"
    assert got[-1][1]["lead_status"] == "complete"
    assert api.saved["alerts"] == ["sara@x.com"]  # team alerted once


def test_unknown_session_is_404(api):
    resp = api.post("/chat", json={"session_id": str(uuid.uuid4()), "message": "hi"})
    assert resp.status_code == 404


def test_bad_requests_are_400_or_422(api):
    sid = api.post("/session", json={"language": "en"}).json()["session_id"]
    assert api.post("/chat", json={"session_id": sid, "message": "   "}).status_code == 400
    assert api.post("/chat", json={"session_id": "not-a-uuid", "message": "hi"}).status_code == 422
    assert api.post("/session", json={"language": "fr"}).status_code == 422


def test_second_message_while_replying_is_refused(api):
    sid = api.post("/session", json={"language": "en"}).json()["session_id"]
    api.redis.data[f"chat:lock:{sid}"] = "1"  # a reply is in progress
    assert api.post("/chat", json={"session_id": sid, "message": "hi"}).status_code == 429


def test_lock_is_released_after_reply(api):
    sid = api.post("/session", json={"language": "en"}).json()["session_id"]
    api.post("/chat", json={"session_id": sid, "message": "Sara"})
    assert f"chat:lock:{sid}" not in api.redis.data
