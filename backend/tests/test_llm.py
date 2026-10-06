"""Tests for the AI layer and knowledge loader. Fake models, no API calls."""

import asyncio

import pytest

from app.knowledge import loader
from app.llm import models
from app.llm.models import LLMUnavailable, Usage, stream_reply
from pydantic import SecretStr
from app.llm.prompts import claude_system


def collect(question="What is the Growth Audit?", **kwargs) -> tuple[str, Usage]:
    usage = Usage()

    async def run():
        return "".join([t async for t in stream_reply(question, "en", [], usage, **kwargs)])

    return asyncio.run(run()), usage


def fake_model(name, chunks, fail_after=None):
    """A stand-in for claude_stream / mistral_stream."""

    async def stream(system, messages, usage, instruction="", api_key=""):
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


def test_fallback_model_gets_the_key_rules_repeated_at_the_end():
    assert "NO public price" in models.FALLBACK_REMINDER
    assert '"agency"' in models.FALLBACK_REMINDER


def test_mistral_can_be_the_main_model(monkeypatch):
    monkeypatch.setattr(models.settings, "llm_primary", "mistral")
    monkeypatch.setattr(models, "claude_stream", fake_model("claude", ["Backup."]))
    monkeypatch.setattr(models, "mistral_stream", fake_model("mistral", ["Main."]))
    text, usage = collect()
    assert (text, usage.model_used, usage.fallback_used) == ("Main.", "mistral", False)


def test_claude_backs_up_mistral(monkeypatch):
    monkeypatch.setattr(models.settings, "llm_primary", "mistral")
    monkeypatch.setattr(models, "mistral_stream", fake_model("mistral", [], fail_after=0))
    monkeypatch.setattr(models, "claude_stream", fake_model("claude", ["Backup."]))
    text, usage = collect()
    assert (text, usage.model_used, usage.fallback_used) == ("Backup.", "claude", True)


def keyed_mistral(answers_by_key):
    """A fake Mistral where each key either answers or fails (None)."""
    calls = []

    async def stream(system, messages, usage, instruction="", api_key=""):
        calls.append(api_key)
        if answers_by_key.get(api_key) is None:
            raise TimeoutError("limit reached")
        usage.model_used = "mistral"
        yield answers_by_key[api_key]

    stream.calls = calls
    return stream


def test_next_mistral_key_answers_when_the_first_is_limited(monkeypatch):
    monkeypatch.setattr(models.settings, "llm_primary", "mistral")
    monkeypatch.setattr(models.settings, "mistral_api_keys", SecretStr("key-2, key-3"))
    fake = keyed_mistral({"test-mistral-key-1": None, "key-2": "From key 2."})
    monkeypatch.setattr(models, "mistral_stream", fake)

    text, usage = collect()

    assert text == "From key 2."
    assert usage.source == "mistral-2" and usage.fallback_used is True
    assert fake.calls == ["test-mistral-key-1", "key-2"]


def test_limited_key_rests_so_the_next_visitor_waits_less(monkeypatch):
    monkeypatch.setattr(models.settings, "llm_primary", "mistral")
    monkeypatch.setattr(models.settings, "mistral_api_keys", SecretStr("key-2"))
    fake = keyed_mistral({"test-mistral-key-1": None, "key-2": "ok"})
    monkeypatch.setattr(models, "mistral_stream", fake)

    collect()
    collect()

    assert fake.calls == ["test-mistral-key-1", "key-2", "key-2"]  # key 1 skipped the 2nd time


def test_claude_is_the_last_resort_after_every_mistral_key(monkeypatch):
    monkeypatch.setattr(models.settings, "llm_primary", "mistral")
    monkeypatch.setattr(models.settings, "mistral_api_keys", SecretStr("key-2"))
    monkeypatch.setattr(models, "mistral_stream", keyed_mistral({}))
    monkeypatch.setattr(models, "claude_stream", fake_model("claude", ["Claude here."]))
    text, usage = collect()
    assert (text, usage.source) == ("Claude here.", "claude")


def test_keys_are_listed_once_without_blanks(monkeypatch):
    monkeypatch.setattr(models.settings, "mistral_api_keys",
                        SecretStr(" key-2 ,, test-mistral-key-1, key-3 "))
    assert models.settings.mistral_keys == ["test-mistral-key-1", "key-2", "key-3"]


def test_background_jobs_skip_the_website_knowledge(monkeypatch):
    seen = []

    async def mistral(system, messages, usage, instruction="", api_key="", repeat_rules=True):
        seen.append((system, repeat_rules))
        usage.model_used = "mistral"
        yield "summary"

    monkeypatch.setattr(models.settings, "llm_primary", "mistral")
    monkeypatch.setattr(models, "mistral_stream", mistral)
    text, _ = collect("Summarise this chat", system=models.TASK_SYSTEM)
    assert text == "summary"
    assert seen == [(models.TASK_SYSTEM, False)]  # no knowledge, no bot rules repeated


class FakeClaudeStream:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def words():
            yield "Hi"
        return words()

    async def get_final_message(self):
        from types import SimpleNamespace
        usage = SimpleNamespace(input_tokens=1, cache_creation_input_tokens=0,
                                cache_read_input_tokens=0, output_tokens=1)
        return SimpleNamespace(stop_reason="end_turn", model="claude", usage=usage)


def claude_request(monkeypatch, model: str) -> dict:
    """The request claude_stream sends for one reply with a note, on `model`."""
    calls = []

    class FakeClient:
        def __init__(self, **options):
            self.messages = self

        def stream(self, **request):
            calls.append(request)
            return FakeClaudeStream()

    monkeypatch.setattr(models.anthropic, "AsyncAnthropic", FakeClient)
    monkeypatch.setattr(models.settings, "anthropic_model", model)
    models._clients.clear()  # a fresh fake client for this request

    async def run():
        history = [{"role": "user", "content": "Hi"}]
        return [t async for t in models.claude_stream("RULES", history, Usage(), "Ask their platform")]

    assert asyncio.run(run()) == ["Hi"]
    return calls[0]


def test_sonnet_5_5_gets_thinking_off_and_the_note_after_the_message(monkeypatch):
    request = claude_request(monkeypatch, "claude-sonnet-5-5")
    assert request["thinking"] == {"type": "between_tools"}
    assert request["messages"][-1] == {"role": "system", "content": "Ask their platform"}
    assert len(request["system"]) == 1


def test_other_claude_models_get_only_settings_they_accept(monkeypatch):
    request = claude_request(monkeypatch, "claude-sonnet-5")
    assert "thinking" not in request  # "between_tools" would be an error here
    assert request["output_config"] == {"effort": "low"}
    assert request["messages"][-1]["role"] == "user"  # no mid-chat system message on this model
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert request["system"][1] == {"type": "text", "text": "Ask their platform"}
    assert models.claude_speed_options("claude-haiku-4-5") == {}


def test_thinking_models_get_room_for_their_thinking(monkeypatch):
    monkeypatch.setattr(models.settings, "max_output_tokens", 400)
    assert claude_request(monkeypatch, "claude-sonnet-5-5")["max_tokens"] == 400  # thinking off
    assert claude_request(monkeypatch, "claude-opus-5-5")["max_tokens"] == 400 + models.THINKING_ALLOWANCE
    assert not models.thinks("claude-haiku-4-5") and models.thinks("claude-sonnet-5")
