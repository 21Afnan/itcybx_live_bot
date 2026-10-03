"""Talks to the AI models: Claude first, Mistral if Claude fails.

    python -m app.llm.models --test "What is the Growth Audit?"
    python -m app.llm.models --test "What is the Growth Audit?" --force-fallback

Claude is given LLM_TIMEOUT_SECONDS and one retry. If it still fails (or
declines) before writing anything, Mistral answers instead. If both fail,
LLMUnavailable is raised so the caller can show the contact options.
"""

import argparse
import asyncio
import time
from dataclasses import dataclass
from typing import AsyncIterator

import anthropic
from mistralai.client import Mistral

from app.config import settings
from app.llm.prompts import claude_system, system_text


FALLBACK_REMINDER = """# Most important rules (always follow)
- Growth Sprint and Growth Retainer have NO public price. Never give a price, range,
  estimate or "starting from" figure for them, even if asked for a ballpark. Say they
  are scoped after the Growth Audit.
- Only state facts and numbers that appear in the knowledge above. Never invent any.
- Call IT Cybx a "growth studio", never an "agency".
- Answer the question in the first sentence. About 60 words. Reply in the visitor's language."""


class LLMUnavailable(Exception):
    """Neither Claude nor Mistral could answer."""


@dataclass
class Usage:
    """What one reply cost and who wrote it. Filled in as the reply streams."""

    model_used: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cached_tokens: int = 0
    fallback_used: bool = False


async def claude_stream(
    system: str, messages: list[dict], usage: Usage, instruction: str = ""
) -> AsyncIterator[str]:
    """Stream a reply from Claude, with the rules + knowledge cached.

    `instruction` is this turn's note (e.g. "ask for their platform"). It is
    sent as a system message after the visitor's message, so the cached
    rules + knowledge block in front stays unchanged.
    """
    if instruction:
        messages = [*messages, {"role": "system", "content": instruction}]
    client = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
    )
    async with client.messages.stream(
        model=settings.anthropic_model,
        max_tokens=settings.max_output_tokens,
        thinking={"type": "between_tools"},  # no extended thinking: fast first word
        output_config={"effort": "low"},
        system=claude_system(system),
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text
        final = await stream.get_final_message()

    if final.stop_reason == "refusal":
        raise anthropic.AnthropicError("Claude declined to answer")
    usage.model_used = final.model
    usage.tokens_in = final.usage.input_tokens + (final.usage.cache_creation_input_tokens or 0)
    usage.cached_tokens = final.usage.cache_read_input_tokens or 0
    usage.tokens_out = final.usage.output_tokens


async def mistral_stream(
    system: str, messages: list[dict], usage: Usage, instruction: str = ""
) -> AsyncIterator[str]:
    """Stream a reply from Mistral (the fallback model).

    The smaller fallback model tends to forget rules placed before a long
    knowledge block, so the most important ones are repeated at the end.
    """
    system = f"{system}\n\n{FALLBACK_REMINDER}"
    if instruction:
        system = f"{system}\n\n# Note for this reply\n{instruction}"
    client = Mistral(
        api_key=settings.mistral_api_key.get_secret_value(),
        timeout_ms=int(settings.llm_timeout_seconds * 1000),
    )
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
            if chunk.usage:
                usage.tokens_in = chunk.usage.prompt_tokens or 0
                usage.tokens_out = chunk.usage.completion_tokens or 0
            usage.model_used = chunk.model or settings.mistral_model


async def stream_reply(
    question: str,
    language: str,
    history: list[dict],
    usage: Usage,
    force_fallback: bool = False,
    instruction: str = "",
) -> AsyncIterator[str]:
    """Stream the bot's reply to `question`, falling back to Mistral if needed.

    `history` is the earlier messages ({"role", "content"}), oldest first.
    `instruction` is an optional note for this reply only.
    `usage` is filled in once the reply is complete.
    """
    system = system_text(question, language)
    messages = [*history, {"role": "user", "content": question}]

    if not force_fallback:
        started = False
        try:
            async for text in claude_stream(system, messages, usage, instruction):
                started = True
                yield text
            return
        except Exception:
            if started:  # half a reply already went out: don't start a second one
                raise LLMUnavailable("Claude stopped mid-reply")

    usage.fallback_used = True
    try:
        async for text in mistral_stream(system, messages, usage, instruction):
            yield text
    except Exception as e:
        raise LLMUnavailable("Mistral failed too") from e


async def summarize(summary: str, messages: list[dict], language: str) -> str:
    """Fold older messages into a short running summary (keeps prompts small)."""
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    question = (
        "Update this summary of an earlier part of the chat with the messages below. "
        "Keep facts about the visitor and their store. Max 80 words. Reply with the summary only.\n\n"
        f"Summary so far: {summary or '(none)'}\n\nMessages:\n{transcript}"
    )
    usage = Usage()
    parts = [t async for t in stream_reply(question, language, [], usage)]
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
    print(f"model: {usage.model_used}   fallback used: {'yes' if usage.fallback_used else 'no'}")
    print(f"tokens in: {usage.tokens_in}   from cache: {usage.cached_tokens}   out: {usage.tokens_out}")
    print(f"first word after: {first or 0:.1f}s   total: {time.monotonic() - start:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the AI one question.")
    parser.add_argument("--test", required=True, metavar="QUESTION")
    parser.add_argument("--language", default="en", choices=["en", "ar"])
    parser.add_argument("--force-fallback", action="store_true", help="skip Claude, use Mistral")
    args = parser.parse_args()
    asyncio.run(_cli(args.test, args.language, args.force_fallback))


if __name__ == "__main__":
    main()
