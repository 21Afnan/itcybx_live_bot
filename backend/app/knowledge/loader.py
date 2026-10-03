"""Gives the bot its knowledge.

All retrieval goes through get_context(). In Phase 1 it returns the whole
rules.md plus every knowledge file for the chat's language; in Phase 3 it
can switch to a search without anything else changing.
"""

from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"

_cache: dict[str, tuple[tuple, str]] = {}  # language -> (files' signature, text)


def load(language: str, knowledge_dir: Path | None = None) -> str:
    """rules.md followed by every knowledge/<language>/*.md file, in name order."""
    knowledge_dir = knowledge_dir or KNOWLEDGE_DIR
    rules = (knowledge_dir / "rules.md").read_text(encoding="utf-8").strip()
    pages = [
        p.read_text(encoding="utf-8").strip()
        for p in sorted((knowledge_dir / language).glob("*.md"))
    ]
    return rules + "\n\n# Knowledge\n\n" + "\n\n---\n\n".join(pages) + "\n"


def signature(language: str, knowledge_dir: Path | None = None) -> tuple:
    """Names, sizes and change times of the files; differs as soon as one changes."""
    knowledge_dir = knowledge_dir or KNOWLEDGE_DIR
    files = [knowledge_dir / "rules.md", *sorted((knowledge_dir / language).glob("*.md"))]
    return tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files)


def get_context(question: str, language: str) -> str:
    """Rules + knowledge for this language.

    The text is the same for every question, which is what lets the AI
    provider cache it. It is re-read automatically when the weekly sync (or
    a rollback) changes a file. The question is unused in Phase 1.
    """
    if language not in ("en", "ar"):
        language = "en"
    current = signature(language)
    cached = _cache.get(language)
    if cached is None or cached[0] != current:
        _cache[language] = (current, load(language))
    return _cache[language][1]


def reload() -> None:
    """Forget the loaded files so the next get_context() reads them again."""
    _cache.clear()
