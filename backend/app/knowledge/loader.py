"""Gives the bot its knowledge.

All retrieval goes through get_context(). In Phase 1 it returns the whole
rules.md plus every knowledge file for the chat's language; in Phase 3 it
can switch to a search without anything else changing.
"""

from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"

_cache: dict[str, str] = {}


def load(language: str, knowledge_dir: Path = KNOWLEDGE_DIR) -> str:
    """rules.md followed by every knowledge/<language>/*.md file, in name order."""
    rules = (knowledge_dir / "rules.md").read_text(encoding="utf-8").strip()
    pages = [
        p.read_text(encoding="utf-8").strip()
        for p in sorted((knowledge_dir / language).glob("*.md"))
    ]
    return rules + "\n\n# Knowledge\n\n" + "\n\n---\n\n".join(pages) + "\n"


def get_context(question: str, language: str) -> str:
    """Rules + knowledge for this language.

    The text is the same for every question, which is what lets the AI
    provider cache it. The question is unused in Phase 1.
    """
    if language not in ("en", "ar"):
        language = "en"
    if language not in _cache:
        _cache[language] = load(language)
    return _cache[language]


def reload() -> None:
    """Forget the loaded files so the next get_context() reads them again."""
    _cache.clear()
