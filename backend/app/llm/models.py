"""Talks to the AI models, trying them in order until one answers.

    python -m app.llm.models --test "What is the Growth Audit?"
    python -m app.llm.models --test "What is the Growth Audit?" --force-fallback
    python -m app.llm.models --check-keys

The order comes from .env: with LLM_PRIMARY=mistral it is every Mistral key
(MISTRAL_API_KEY, then each one in MISTRAL_API_KEYS), then Claude; with
LLM_PRIMARY=claude it is Claude first, then the Mistral keys.

If a model fails (limit reached, timeout, error) before writing anything,
the next one answers instead, and the failed one is skipped for
COOLDOWN_SECONDS so visitors don't wait on it again. If all fail,
LLMUnavailable is raised so the caller can show the contact options.
"""

import argparse
import asyncio
import functools
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable

import anthropic
from mistralai.client import Mistral

from app.config import settings
from app.knowledge.loader import KNOWLEDGE_DIR
from app.llm.prompts import claude_system, system_text


FALLBACK_REMINDER = """# Most important rules (always follow)
- Growth Sprint and Growth Retainer have NO public price. Never give a price, range,
  estimate or "starting from" figure for them, even if asked for a ballpark. Say they
  are scoped after the Growth Audit.
- Only state facts and numbers that appear in the knowledge above. Never invent any.
- Call IT Cybx a "growth studio", never an "agency".
- Answer the question in the first sentence. About 60 words. Reply in the visitor's language."""


log = logging.getLogger("chatbot.llm")

# For background jobs (chat summaries): no website knowledge, no bot rules.
TASK_SYSTEM = ("You help the IT Cybx team (an e-commerce growth studio) with internal notes "
               "about website chats. Follow the instructions exactly and add nothing else.")

# Claude models that accept a system message in the middle of the chat. On
# the others, this turn's note goes in a second system block instead.
MID_CHAT_SYSTEM_MODELS = ("claude-sonnet-5-5", "claude-opus-5", "claude-opus-4-8",
                          "claude-fable-5", "claude-mythos-5")

COOLDOWN_SECONDS = 60
_resting_until: dict[str, float] = {}  # model/key name -> time it may be tried again

# Models whose thinking can't be turned off (or is on unless told otherwise):
# their thinking counts against max_tokens, so they get this much extra room
# or the reply itself would be cut short.
THINKING_ALLOWANCE = 2000

# One client per provider and key, reused: a new client per reply would open
# a new connection (and TLS handshake) every time.
_clients: dict[tuple[str, str], object] = {}


def claude_client() -> anthropic.AsyncAnthropic:
    key = settings.anthropic_api_key.get_secret_value()
    if ("claude", key) not in _clients:
        _clients["claude", key] = anthropic.AsyncAnthropic(
            api_key=key, timeout=settings.llm_timeout_seconds, max_retries=1,
        )
    return _clients["claude", key]


def mistral_client(api_key: str) -> Mistral:
    if ("mistral", api_key) not in _clients:
        _clients["mistral", api_key] = Mistral(
            api_key=api_key, timeout_ms=int(settings.llm_timeout_seconds * 1000),
        )
    return _clients["mistral", api_key]


class LLMUnavailable(Exception):
    """None of the models could answer."""


@dataclass
class Usage:
    """What one reply cost and who wrote it. Filled in as the reply streams."""

    model_used: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cached_tokens: int = 0
    fallback_used: bool = False
    source: str = ""  # which entry of the chain answered, e.g. "mistral-2"


async def claude_stream(
    system: str, messages: list[dict], usage: Usage, instruction: str = ""
) -> AsyncIterator[str]:
    """Stream a reply from Claude, with the rules + knowledge cached.

    `instruction` is this turn's note (e.g. "ask for their platform"). It is
    sent as a system message after the visitor's message, so the cached
    rules + knowledge block in front stays unchanged.
    """
    model = settings.anthropic_model
    system_blocks = claude_system(system)
    if instruction and model.startswith(MID_CHAT_SYSTEM_MODELS):
        messages = [*messages, {"role": "system", "content": instruction}]
    elif instruction:
        system_blocks = [*system_blocks, {"type": "text", "text": instruction}]  # after the cached block
    max_tokens = settings.max_output_tokens + (THINKING_ALLOWANCE if thinks(model) else 0)
    async with claude_client().messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system_blocks,
        messages=messages,
        **claude_speed_options(model),
    ) as stream:
        async for text in stream.text_stream:
            yield text
        final = await stream.get_final_message()

    if final.stop_reason == "refusal":
        raise anthropic.AnthropicError("Claude declined to answer")
    if final.stop_reason == "max_tokens":
        log.warning("Claude reply cut off at max_tokens (%s); raise MAX_OUTPUT_TOKENS", model)
    usage.model_used = final.model
    usage.tokens_in = final.usage.input_tokens + (final.usage.cache_creation_input_tokens or 0)
    usage.cached_tokens = final.usage.cache_read_input_tokens or 0
    usage.tokens_out = final.usage.output_tokens


def thinks(model: str) -> bool:
    """True for Claude models that think with the settings below (see claude_speed_options)."""
    if model.startswith("claude-sonnet-5-5"):
        return False  # thinking turned off with "between_tools"
    return model.startswith(("claude-opus-5", "claude-fable", "claude-mythos", "claude-sonnet-5"))


def claude_speed_options(model: str) -> dict:
    """The fastest settings each Claude model accepts (a chat reply needs no deep thinking).

    Only Sonnet 5.5 can turn thinking off ("between_tools"); sending that to
    another model is an error, so the others just think at low effort.
    Haiku 4.5 and older models take neither setting.
    """
    if model.startswith("claude-sonnet-5-5"):
        return {"thinking": {"type": "between_tools"}, "output_config": {"effort": "low"}}
    if model.startswith(("claude-haiku", "claude-3", "claude-sonnet-4-5")):
        return {}
    return {"output_config": {"effort": "low"}}


async def mistral_stream(
    system: str, messages: list[dict], usage: Usage, instruction: str = "", api_key: str = "",
    repeat_rules: bool = True,
) -> AsyncIterator[str]:
    """Stream a reply from Mistral.

    Smaller models tend to forget rules placed before a long knowledge
    block, so the full rules and the most important ones are repeated
    after it (the last instructions are the ones they follow best).
    `repeat_rules=False` is for background jobs that don't use the bot prompt.
    """
    if repeat_rules:
        rules = (KNOWLEDGE_DIR / "rules.md").read_text(encoding="utf-8").strip()
        system = f"{system}\n\n---\n\n{rules}\n\n{FALLBACK_REMINDER}"
    if instruction:
        system = f"{system}\n\n# Note for this reply\n{instruction}"
    client = mistral_client(api_key or settings.mistral_api_key.get_secret_value())
    response = await client.chat.stream_async(
        model=settings.mistral_model,
        max_tokens=settings.max_output_tokens,
        messages=[{"role": "system", "content": system}, *messages],
    )
    async with response as events:
        async for event in events:
            chunk = event.data
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            if chunk.choices and chunk.choices[0].finish_reason == "length":
                log.warning("Mistral reply cut off at max_tokens; raise MAX_OUTPUT_TOKENS")
            if chunk.usage:
                usage.tokens_in = chunk.usage.prompt_tokens or 0
                usage.tokens_out = chunk.usage.completion_tokens or 0
            usage.model_used = chunk.model or settings.mistral_model


def model_chain(task: bool = False) -> list[tuple[str, Callable]]:
    """The models to try, in order, as (name, stream function).

    Names are for logs and cooldowns ("mistral-1", "mistral-2", "claude");
    they never contain the keys themselves. `task` is for background jobs
    with their own short system prompt.
    """
    extra = {"repeat_rules": False} if task else {}
    mistral = [
        (f"mistral-{i}", functools.partial(mistral_stream, api_key=key, **extra))
        for i, key in enumerate(settings.mistral_keys, start=1)
    ]
    claude = [("claude", claude_stream)] if settings.anthropic_api_key.get_secret_value() else []
    return mistral + claude if settings.llm_primary == "mistral" else claude + mistral


async def stream_reply(
    question: str,
    language: str,
    history: list[dict],
    usage: Usage,
    force_fallback: bool = False,
    instruction: str = "",
    system: str | None = None,
) -> AsyncIterator[str]:
    """Stream the bot's reply to `question`, moving down the model chain on failure.

    `force_fallback` skips the first model in the chain (for testing).
    `history` is the earlier messages ({"role", "content"}), oldest first.
    `instruction` is an optional note for this reply only.
    `system` replaces the bot's rules + knowledge, for background jobs
    (e.g. TASK_SYSTEM) that don't need the whole website in the prompt.
    `usage` is filled in once the reply is complete.
    """
    task = system is not None
    system = system if task else system_text(question, language)
    messages = [*history, {"role": "user", "content": question}]
    chain = model_chain(task)[1:] if force_fallback else model_chain(task)
    now = time.monotonic()
    ready = [m for m in chain if _resting_until.get(m[0], 0) <= now]
    resting = [m for m in chain if m not in ready]  # tried last, in case all are resting

    for position, (name, stream) in enumerate(ready + resting):
        started = False
        try:
            async for text in stream(system, messages, usage, instruction):
                started = True
                yield text
            usage.fallback_used = force_fallback or name != chain[0][0]
            usage.source = name
            _resting_until.pop(name, None)
            return
        except Exception as e:
            # The type only: messages from the SDKs can contain request details.
            log.warning("AI model %s failed (%s), trying the next one", name, type(e).__name__)
            if started:  # half a reply already went out: don't start a second one
                raise LLMUnavailable(f"{name} stopped mid-reply")
            _resting_until[name] = time.monotonic() + COOLDOWN_SECONDS
    raise LLMUnavailable("every model failed")


async def summarize(summary: str, messages: list[dict], language: str) -> str:
    """Fold older messages into a short running summary (keeps prompts small)."""
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    question = (
        "Update this summary of an earlier part of the chat with the messages below. "
        "Keep facts about the visitor and their store. Max 80 words. Reply with the summary only.\n\n"
        f"Summary so far: {summary or '(none)'}\n\nMessages:\n{transcript}"
    )
    usage = Usage()
    parts = [t async for t in stream_reply(question, language, [], usage, system=TASK_SYSTEM)]
    return "".join(parts).strip()


async def _cli(question: str, language: str, force_fallback: bool) -> None:
    usage = Usage()
    start = time.monotonic()
    first = None
    try:
        async for text in stream_reply(question, language, [], usage, force_fallback):
            first = first or time.monotonic() - start
            print(text, end="", flush=True)
    except LLMUnavailable as e:
        print(f"\n\nBoth models failed: {e} ({type(e.__cause__).__name__})")
        return
    print("\n")
    print(f"model: {usage.model_used} ({usage.source})   fallback used: {'yes' if usage.fallback_used else 'no'}")
    print(f"tokens in: {usage.tokens_in}   from cache: {usage.cached_tokens}   out: {usage.tokens_out}")
    print(f"first word after: {first or 0:.1f}s   total: {time.monotonic() - start:.1f}s")


async def _check_keys() -> None:
    """Send a tiny message through each model in the chain and say which work."""
    chain = model_chain()
    print(f"{len(settings.mistral_keys)} Mistral key(s) found. Testing each one:\n")
    for name, stream in chain:
        usage = Usage()
        start = time.monotonic()
        try:
            async for _ in stream("Reply with OK.", [{"role": "user", "content": "OK?"}], usage):
                pass
            print(f"  OK      {name:<11} {usage.model_used}  ({time.monotonic() - start:.1f}s)")
        except Exception as e:
            print(f"  FAILED  {name:<11} {type(e).__name__}: {str(e)[:90]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the AI one question.")
    parser.add_argument("--test", metavar="QUESTION")
    parser.add_argument("--check-keys", action="store_true", help="test every AI key")
    parser.add_argument("--language", default="en", choices=["en", "ar"])
    parser.add_argument("--force-fallback", action="store_true", help="skip Claude, use Mistral")
    args = parser.parse_args()
    if args.check_keys:
        asyncio.run(_check_keys())
    elif args.test:
        asyncio.run(_cli(args.test, args.language, args.force_fallback))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
