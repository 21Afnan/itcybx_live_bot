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


def test_platform_question_is_asked_only_once(fake_ai):
    state, _ = turn(new_state("s1", "en"), "Sara")
    state, _ = turn(state, "What do you do?")  # asks platform
    assert "e-commerce platform" in fake_ai[-1]["instruction"]
    state, _ = turn(state, "What about your process?")  # visitor ignored it: rest turn
    assert "Do not ask about their platform" in fake_ai[-1]["instruction"]
    state, _ = turn(state, "And case studies?")  # next detail, never platform again
    assert "main market" in fake_ai[-1]["instruction"]
    for question in ["Refunds?", "Who founded you?", "Contact?", "Anything else?"]:
        state, _ = turn(state, question)
        assert "e-commerce platform" not in fake_ai[-1]["instruction"]


def test_no_store_questions_two_replies_in_a_row(fake_ai):
    state, _ = turn(new_state("s1", "en"), "Sara")
    asked = []
    for question in ["Q1?", "Q2?", "Q3?", "Q4?", "Q5?", "Q6?", "Q7?"]:
        state, _ = turn(state, question)
        asked.append("After answering, ask ONE" in fake_ai[-1]["instruction"])
    # platform, rest, market, rest, store URL, then never again
    assert asked == [True, False, True, False, True, False, False]


def test_first_market_stays_unless_the_bot_asked_for_it(fake_ai):
    state, _ = turn(new_state("s1", "en"), "Sara")
    state, _ = turn(state, "We sell in Saudi on Salla")
    state, _ = turn(state, "Maybe the UK one day")
    assert state["lead"]["market"] == "KSA"  # a passing mention doesn't replace it


def test_answer_to_the_market_question_replaces_it(fake_ai):
    state, _ = turn(new_state("s1", "en"), "Sara")
    state["lead"]["market"] = "KSA"
    state.update(last_step="qualify", qualify_asked=["market"])
    state, _ = turn(state, "Actually mostly the UK")
    assert state["lead"]["market"] == "UK"


def test_hello_there_is_not_taken_as_a_name(fake_ai):
    state, _ = turn(new_state("s1", "en"), "Hello there")
    assert state.get("name") == ""


def test_question_before_the_name_is_acknowledged(fake_ai):
    state, events = turn(new_state("s1", "en"), "what do you do")
    assert state["name"] == ""
    assert events[0]["text"] == "Happy to help with that! First, what's your name?"


def test_ai_down_does_not_use_up_the_question_it_was_told_to_ask(monkeypatch, fake_ai):
    state, _ = turn(new_state("s1", "en"), "Sara")

    async def broken(*args, **kwargs):
        raise nodes.LLMUnavailable("down")
        yield  # pragma: no cover

    monkeypatch.setattr(nodes, "stream_reply", broken)
    state, _ = turn(state, "What do you do?")  # would have asked for the platform
    assert state["qualify_asked"] == [] and state["last_step"] == ""
    assert state["messages"][-1]["role"] == "assistant"  # same history Supabase saves
    monkeypatch.setattr(nodes, "stream_reply", fake_ai_stream(fake_ai))  # AI back up
    state, _ = turn(state, "What do you do?")
    assert "e-commerce platform" in fake_ai[-1]["instruction"]  # asked now instead


def test_lead_details_still_count_when_the_ai_is_down(monkeypatch, fake_ai):
    state, _ = turn(new_state("s1", "en"), "Sara")

    async def broken(*args, **kwargs):
        raise nodes.LLMUnavailable("down")
        yield  # pragma: no cover

    monkeypatch.setattr(nodes, "stream_reply", broken)
    state, _ = turn(state, "sara@mystore.com, +966501234567")
    assert state["lead_status"] == "complete" and state["lead_just_completed"]


def fake_ai_stream(calls):
    async def fake_stream_reply(question, language, history, usage, instruction=""):
        calls.append({"question": question, "history": history, "instruction": instruction})
        yield "Answer."
    return fake_stream_reply
