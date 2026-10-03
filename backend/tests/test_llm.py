"""Tests for the AI layer and knowledge loader. Fake models, no API calls."""

import asyncio

import pytest

from app.knowledge import loader
from app.llm import models
from app.llm.models import LLMUnavailable, Usage, stream_reply
from app.llm.prompts import claude_system


def collect(question="What is the Growth Audit?", **kwargs) -> tuple[str, Usage]:
    usage = Usage()

    async def run():
        return "".join([t async for t in stream_reply(question, "en", [], usage, **kwargs)])

    return asyncio.run(run()), usage


def fake_model(name, chunks, fail_after=None):
    """A stand-in for claude_stream / mistral_stream."""

    async def stream(system, messages, usage):
        assert "IT Cybx Assistant Rules" in system  # rules + knowledge always sent
        for i, chunk in enumerate(chunks):
            if fail_after is not None and i == fail_after:
                raise TimeoutError("model too slow")
            yield chunk
        if fail_after is not None and fail_after >= len(chunks):
            raise TimeoutError("model too slow")
        usage.model_used = name

    return stream


def test_claude_answers_when_it_works(monkeypatch):
    monkeypatch.setattr(models, "claude_stream", fake_model("claude", ["The audit ", "is $150."]))
    monkeypatch.setattr(models, "mistral_stream", fake_model("mistral", ["unused"]))
    text, usage = collect()
    assert text == "The audit is $150."
    assert usage.model_used == "claude"
    assert usage.fallback_used is False


def test_mistral_takes_over_when_claude_fails(monkeypatch):
    monkeypatch.setattr(models, "claude_stream", fake_model("claude", [], fail_after=0))
    monkeypatch.setattr(models, "mistral_stream", fake_model("mistral", ["Backup answer."]))
    text, usage = collect()
    assert text == "Backup answer."
    assert usage.model_used == "mistral"
    assert usage.fallback_used is True


def test_force_fallback_skips_claude(monkeypatch):
    monkeypatch.setattr(models, "claude_stream", fake_model("claude", ["should not run"]))
    monkeypatch.setattr(models, "mistral_stream", fake_model("mistral", ["From Mistral."]))
    text, usage = collect(force_fallback=True)
    assert text == "From Mistral."
    assert usage.fallback_used is True


def test_both_failing_raises_unavailable(monkeypatch):
    monkeypatch.setattr(models, "claude_stream", fake_model("claude", [], fail_after=0))
    monkeypatch.setattr(models, "mistral_stream", fake_model("mistral", [], fail_after=0))
    with pytest.raises(LLMUnavailable):
        collect()


def test_no_second_reply_if_claude_fails_mid_answer(monkeypatch):
    monkeypatch.setattr(models, "claude_stream", fake_model("claude", ["Half an "], fail_after=1))
    monkeypatch.setattr(models, "mistral_stream", fake_model("mistral", ["Second answer"]))
    with pytest.raises(LLMUnavailable):
        collect()


def test_knowledge_is_rules_then_one_language_only(tmp_path):
    (tmp_path / "en").mkdir()
    (tmp_path / "ar").mkdir()
    (tmp_path / "rules.md").write_text("RULES", encoding="utf-8")
    (tmp_path / "en" / "b.md").write_text("English B", encoding="utf-8")
    (tmp_path / "en" / "a.md").write_text("English A", encoding="utf-8")
    (tmp_path / "ar" / "a.md").write_text("عربي", encoding="utf-8")

    text = loader.load("en", knowledge_dir=tmp_path)

    assert text.startswith("RULES")
    assert text.index("English A") < text.index("English B")
    assert "عربي" not in text


def test_context_is_identical_for_every_question_so_it_caches():
    loader.reload()
    assert loader.get_context("price?", "en") == loader.get_context("process?", "en")
    assert loader.get_context("x", "ar") != loader.get_context("x", "en")
    assert loader.get_context("x", "fr") == loader.get_context("x", "en")  # unknown -> English


def test_system_prompt_is_marked_for_caching():
    blocks = claude_system("rules and knowledge")
    assert blocks == [{"type": "text", "text": "rules and knowledge",
                       "cache_control": {"type": "ephemeral"}}]
