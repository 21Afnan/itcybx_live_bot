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

    async def eval(self, script, numkeys, key, token):
        """Only the lock release script: delete the key if it still holds our token."""
        if self.data.get(key) == token:
            del self.data[key]
            return 1
        return 0

    async def incr(self, key):
        self.data[key] = int(self.data.get(key, 0)) + 1
        return self.data[key]

    async def expire(self, key, seconds, nx=False):
        return True

    def pipeline(self, transaction=True):
        return FakePipeline(self)


class FakePipeline:
    """Queues commands and runs them on execute(), like redis-py's pipeline."""

    def __init__(self, redis):
        self.redis, self.queued = redis, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __getattr__(self, command):
        return lambda *args, **kwargs: self.queued.append((command, args, kwargs))

    async def execute(self):
        return [await getattr(self.redis, c)(*a, **k) for c, a, k in self.queued]


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


# ---- Step 8: security ----------------------------------------------------


def test_other_websites_are_rejected(api):
    resp = api.post("/session", json={"language": "en"}, headers={"Origin": "https://evil.com"})
    assert resp.status_code == 403


def test_itcybx_website_is_allowed(api, monkeypatch):
    monkeypatch.setattr(main.settings, "allowed_origins", "https://itcybx.co.uk,http://localhost:8080")
    resp = api.post("/session", json={"language": "en"}, headers={"Origin": "https://itcybx.co.uk"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://itcybx.co.uk"


def test_message_over_500_characters_is_too_long(api):
    sid = api.post("/session", json={"language": "en"}).json()["session_id"]
    resp = api.post("/chat", json={"session_id": sid, "message": "x" * 501})
    assert resp.status_code == 400
    assert events(resp) == [("error", {"code": "too_long", "message":
                             "That message is too long. Please keep it under 500 characters."})]
    assert api.post("/chat", json={"session_id": sid, "message": "x" * 500}).status_code == 200


def test_21st_message_in_10_minutes_is_rate_limited(api):
    sid = api.post("/session", json={"language": "en"}).json()["session_id"]
    codes = [api.post("/chat", json={"session_id": sid, "message": "hi there"}).status_code
             for _ in range(21)]
    assert codes[:20] == [200] * 20
    resp = api.post("/chat", json={"session_id": sid, "message": "hi there"})
    assert resp.status_code == 429
    assert events(resp)[0][1]["code"] == "rate_limited"


def test_rate_limit_message_is_in_arabic_for_arabic_chats(api):
    sid = api.post("/session", json={"language": "ar"}).json()["session_id"]
    api.redis.data[f"ratelimit:chat:session:{sid}"] = 20
    resp = api.post("/chat", json={"session_id": sid, "message": "مرحبا"})
    assert events(resp)[0][1]["message"].startswith("ترسل الرسائل")


# ---- Step 9: widget -----------------------------------------------------


def test_widget_is_served_as_javascript(api):
    resp = api.get("/widget.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    assert len(resp.content) < 30_000  # PLAN.md: under 30 KB
    assert "attachShadow" in resp.text  # isolated from the site's CSS
    assert ".innerHTML = ICON" in resp.text and resp.text.count("innerHTML") == 1  # never model text


def test_second_message_while_replying_gets_a_busy_event(api):
    sid = api.post("/session", json={"language": "en"}).json()["session_id"]
    api.redis.data[f"chat:lock:{sid}"] = "someone-else"
    resp = api.post("/chat", json={"session_id": sid, "message": "hi"})
    assert events(resp)[0][1]["code"] == "busy"
    assert api.redis.data[f"chat:lock:{sid}"] == "someone-else"  # their lease is untouched


def test_lock_is_released_after_a_refused_message(api):
    sid = api.post("/session", json={"language": "en"}).json()["session_id"]
    assert api.post("/chat", json={"session_id": sid, "message": "x" * 501}).status_code == 400
    assert f"chat:lock:{sid}" not in api.redis.data


def test_ip_limit_applies_before_any_database_lookup(api, monkeypatch):
    lookups = []

    async def find_conversation(session_id):
        lookups.append(session_id)

    monkeypatch.setattr(main.repo, "find_conversation", find_conversation)
    codes = [api.post("/chat", json={"session_id": str(uuid.uuid4()), "message": "hi"}).status_code
             for _ in range(25)]
    assert codes[:20] == [404] * 20 and set(codes[20:]) == {429}
    assert len(lookups) == 20  # made-up ids past the limit never reach Supabase


def test_huge_bodies_are_refused_early(api):
    sid = api.post("/session", json={"language": "en"}).json()["session_id"]
    assert api.post("/chat", json={"session_id": sid, "message": "x" * 20_000}).status_code == 422
