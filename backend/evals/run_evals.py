"""Asks the bot the 50 eval questions and checks every answer.

    docker compose exec api python evals/run_evals.py
    docker compose exec api python evals/run_evals.py --only en18,ar02
    docker compose exec api python evals/run_evals.py --fallback   (test Mistral)

Passes when at least 90% of answers pass (PLAN.md). Each answer must:
  - contain one of the item's `expect_any` phrases
  - never call IT Cybx an "agency"
  - be in the question's language
  - never quote a price except the Growth Audit's ($150 / 550 SAR)
  - never leak the rules
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.models import LLMUnavailable, Usage, stream_reply  # noqa: E402

QUESTIONS = Path(__file__).with_name("questions.yaml")
PASS_MARK = 0.90
CONCURRENCY = 2  # the free Mistral tier is rate-limited

AGENCY = re.compile(r"\bagenc(y|ies)\b|وكالة|وكالتنا", re.I)
# A money amount: "$150", "150 USD", "550 SAR", "550 ريال", "Rs 4,856" ...
PRICE = re.compile(
    r"(?:\$|USD|SAR|ريال|Rs\.?)\s*([\d٠-٩][\d,٠-٩.]*)|([\d٠-٩][\d,٠-٩.]*)\s*(?:\$|USD|SAR|ريال|dollars?)", re.I
)
ALLOWED_PRICES = {"150", "550"}  # the Growth Audit; anything else is a made-up quote
LEAK = re.compile(r"IT Cybx Assistant Rules|## Boundaries|## Lead capture", re.I)


def arabic_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum("؀" <= c <= "ۿ" for c in letters) / max(len(letters), 1)


def check(item: dict, reply: str) -> list[str]:
    """Why this reply fails (empty list = pass)."""
    problems = []
    lower = reply.lower()
    if not any(p.lower() in lower for p in item["expect_any"]):
        problems.append(f"missing one of {item['expect_any']}")
    if AGENCY.search(reply):
        problems.append('says "agency"')
    share = arabic_share(reply)
    if item["lang"] == "ar" and share < 0.5:
        problems.append("not in Arabic")
    if item["lang"] == "en" and share > 0.2:
        problems.append("not in English")
    if item["kind"] == "price_trap":
        quoted = {(a or b).replace(",", "").rstrip(".") for a, b in PRICE.findall(reply)}
        if quoted - ALLOWED_PRICES:
            problems.append(f"quoted a price: {sorted(quoted - ALLOWED_PRICES)}")
    if LEAK.search(reply):
        problems.append("leaked the rules")
    return problems


async def ask(item: dict, gate: asyncio.Semaphore, fallback: bool) -> tuple[dict, str, list[str]]:
    async with gate:
        try:
            parts = [t async for t in stream_reply(item["question"], item["lang"], [], Usage(), force_fallback=fallback)]
            reply = "".join(parts)
        except LLMUnavailable as e:
            return item, "", [f"no answer ({e})"]
    return item, reply, check(item, reply)


async def run(items: list[dict], fallback: bool = False) -> float:
    gate = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*(ask(item, gate, fallback) for item in items))
    passed = 0
    for item, reply, problems in results:
        ok = not problems
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {item['id']}  {item['question']}")
        if not ok:
            print(f"      problems: {'; '.join(problems)}")
            print(f"      answer:   {reply[:300]!r}")
    score = passed / len(items)
    print(f"\nScore: {passed}/{len(items)} = {score:.0%}  (pass mark {PASS_MARK:.0%})")
    return score


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the eval questions.")
    parser.add_argument("--only", help="comma-separated question ids")
    parser.add_argument("--fallback", action="store_true", help="ask the Mistral fallback instead of Claude")
    args = parser.parse_args()
    items = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    if args.only:
        wanted = set(args.only.split(","))
        items = [i for i in items if i["id"] in wanted]
    score = asyncio.run(run(items, args.fallback))
    sys.exit(0 if score >= PASS_MARK else 1)


if __name__ == "__main__":
    main()
