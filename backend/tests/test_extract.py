"""Tests for finding and checking lead details in messages."""

from app.leads.extract import clean_name, find, shows_interest, valid_name, wants_contact


def test_email_and_whatsapp_with_country_code():
    found = find("Sure, it's sara@mystore.com and +966 50 123 4567")
    assert found.email == "sara@mystore.com"
    assert found.whatsapp == "+966501234567"
    assert found.problems == []


def test_00_prefix_becomes_plus():
    assert find("my number is 0044 7700 900123").whatsapp == "+447700900123"


def test_number_without_country_code_is_flagged():
    found = find("call me on 0501234567")
    assert found.whatsapp == ""
    assert "whatsapp_needs_country_code" in found.problems


def test_platform_market_and_store_url():
    found = find("We sell on Salla in Riyadh, store is mystore.sa")
    assert (found.platform, found.market, found.store_url) == ("Salla", "KSA", "https://mystore.sa")


def test_arabic_platform_and_market():
    found = find("متجري على زد في السعودية")
    assert (found.platform, found.market) == ("Zid", "KSA")


def test_email_domain_is_not_taken_as_store_url():
    assert find("email me at ali@gmail.com").store_url == ""


def test_names_with_dots_are_not_websites():
    assert find("Mr.Smith here").store_url == ""


def test_names():
    assert clean_name("My name is Sara.") == "Sara"
    assert clean_name("hi, I'm Omar") == "Omar"
    assert clean_name("اسمي سارة") == "سارة"
    assert valid_name("Al") and not valid_name("A") and not valid_name("x" * 61)


def test_interest_and_contact_signals():
    assert shows_interest("How much is the audit?")
    assert shows_interest("كم سعر التقييم؟")
    assert not shows_interest("We run facebook ads")  # "book" inside "facebook"
    assert wants_contact("Can I talk to someone?")
    assert not wants_contact("What do you do?")
