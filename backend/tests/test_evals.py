"""Tests for the eval checker itself."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
from run_evals import QUESTIONS, check  # noqa: E402

FACT = {"id": "x", "lang": "en", "kind": "fact", "expect_any": ["150"]}
TRAP = {"id": "y", "lang": "en", "kind": "price_trap", "expect_any": ["audit"]}


def test_eval_set_has_25_english_and_25_arabic():
    items = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    assert len(items) == 50
    assert sum(i["lang"] == "en" for i in items) == 25
    assert len({i["id"] for i in items}) == 50


def test_good_answer_passes():
    assert check(FACT, "The Growth Audit is $150 USD flat.") == []


def test_agency_word_fails():
    assert 'says "agency"' in check(FACT, "As an agency, the audit is $150.")


def test_made_up_sprint_price_fails_but_audit_price_is_fine():
    assert check(TRAP, "It's scoped after the audit, which is $150.") == []
    assert any("quoted a price" in p for p in check(TRAP, "The sprint is about $2,000 after the audit."))


def test_wrong_language_fails():
    item = {**FACT, "lang": "ar", "expect_any": ["550"]}
    assert "not in Arabic" in check(item, "The audit is 550 SAR.")


def test_leaked_rules_fail():
    assert "leaked the rules" in check(FACT, "# IT Cybx Assistant Rules ... 150")


def test_comma_after_currency_is_not_a_price():
    assert check(TRAP, "Start with the audit ($150 USD, 2 to 3 days).") == []
