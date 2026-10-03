"""Builds what the AI is told before the conversation."""

from app.knowledge.loader import get_context


def system_text(question: str, language: str) -> str:
    """Rules + knowledge. Kept identical across messages so it stays cached."""
    return get_context(question, language)


def claude_system(text: str) -> list[dict]:
    """The system prompt in Claude's format, marked for prompt caching."""
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
