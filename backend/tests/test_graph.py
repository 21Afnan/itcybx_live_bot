"""Tests for the conversation flow, with a fake AI (no API calls)."""

import asyncio

import pytest

from app.graph import build, nodes
from app.graph.state import new_state

pytestmark = pytest.mark.skipif(
    __import__("sys").version_info < (3, 11), reason="LangGraph streaming needs Python 3.11+ (Docker has 3.12)"
)


@pytest.fixture
def fake_ai(monkeypatch):
    """Replace the AI with one that records the instruction it was given."""
    calls = []

    async def fake_stream_reply(question, language, history, usage, instruction=""):
        calls.append({"question": question, "history": history, "instruction": instruction})
        usage.model_used = "fake"
        yield "Answer."

    monkeypatch.setattr(nodes, "stream_reply", fake_stream_reply)
    monkeypatch.setattr(nodes.settings, "calendly_url", "https://calendly.com/itcybx/audit")
    return calls


def turn(state, message):
    async def go():
        events = [e async for e in build.run_turn(state, message)]
        return events[-1]["state"], events[:-1]

    return asyncio.run(go())


def test_first_message_is_the_name(fake_ai):
    state, events = turn(new_state("s1", "en"), "My name is Sara")
    assert state["name"] == "Sara"
    assert state["lead_status"] == "partial"
    assert events == [{"type": "token", "text": "Nice to meet you, Sara! How can I help you grow your store today?"}]
    assert fake_ai == []  # no AI needed to greet


def test_question_then_one_qualify_question(fake_ai):
    state, _ = turn(new_state("s1", "en"), "Sara")
    state, events = turn(state, "What do you do?")
    assert [e["text"] for e in events] == ["Answer."]
    assert "e-commerce platform" in fake_ai[-1]["instruction"]
    assert fake_ai[-1]["history"][0]["role"] == "user"  # history starts with the visitor


def test_known_details_are_not_asked_again(fake_ai):
    state, _ = turn(new_state("s1", "en"), "Sara")
    state, _ = turn(state, "We're on Shopify")
    assert state["lead"]["platform"] == "Shopify"
    assert "main market" in fake_ai[-1]["instruction"]  # next missing field, not platform


def test_interest_asks_for_email_and_whatsapp(fake_ai):
    state, _ = turn(new_state("s1", "en"), "Sara")
    state, _ = turn(state, "How much is the audit?")
    assert "email and WhatsApp number" in fake_ai[-1]["instruction"]
    assert state["capture_asks"] == 1


def test_complete_lead_shows_contact_buttons(fake_ai):
    state, _ = turn(new_state("s1", "en"), "Sara")
    state, _ = turn(state, "sara@mystore.com, +966501234567")
    assert state["lead_status"] == "complete"
    assert [b["type"] for b in state["actions"]] == ["calendly", "whatsapp", "email", "contact_page"]
    assert "Thank them by name" in fake_ai[-1]["instruction"]


def test_missing_country_code_is_asked_again(fake_ai):
    state, _ = turn(new_state("s1", "en"), "Sara")
    state, _ = turn(state, "my whatsapp is 0501234567")
    assert state["lead"]["whatsapp"] == ""
    assert "country code" in fake_ai[-1]["instruction"]


def test_asks_for_details_at_most_twice_then_just_offers_contact(fake_ai):
    state, _ = turn(new_state("s1", "en"), "Sara")
    for _ in range(2):
        state, _ = turn(state, "What's the price?")
    state, _ = turn(state, "What's the price?")
    assert state["capture_asks"] == 2
    assert state["actions"]  # contact buttons instead of asking a third time


def test_ai_down_sends_error_and_contact_buttons(monkeypatch, fake_ai):
    async def broken(*args, **kwargs):
        raise nodes.LLMUnavailable("down")
        yield  # pragma: no cover

    monkeypatch.setattr(nodes, "stream_reply", broken)
    state, _ = turn(new_state("s1", "en"), "Sara")
    state, events = turn(state, "Hello?")
    assert events[-1]["type"] == "error" and events[-1]["code"] == "unavailable"
    assert state["actions"]


def test_arabic_greeting(fake_ai):
    state, events = turn(new_state("s1", "ar"), "اسمي سارة")
    assert state["name"] == "سارة"
    assert events[0]["text"].startswith("تشرفنا يا سارة")
