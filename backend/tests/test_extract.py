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
    assert valid_name("Mary Ann Smith")
    for not_a_name in ["How much is the audit?", "كم السعر؟", "sara@x.com", "+966501234567",
                       "I want to grow my online store fast"]:
        assert not valid_name(not_a_name), not_a_name


def test_interest_and_contact_signals():
    assert shows_interest("How much is the audit?")
    assert shows_interest("كم سعر التقييم؟")
    assert not shows_interest("We run facebook ads")  # "book" inside "facebook"
    assert wants_contact("Can I talk to someone?")
    assert not wants_contact("What do you do?")


def test_market_is_not_read_from_a_web_address():
    found = find("our store is glowbeauty.co.uk")
    assert found.store_url == "https://glowbeauty.co.uk"
    assert found.market == ""


def test_big_numbers_are_not_taken_for_a_phone():
    assert find("we did 10000000 in sales last year").problems == []


def test_number_is_checked_when_the_bot_asked_for_whatsapp():
    assert "whatsapp_needs_country_code" in find("0501234567", expecting_phone=True).problems
    assert "whatsapp_needs_country_code" in find("my whatsapp is 0501234567").problems


def test_numbers_inside_links_are_not_phones():
    assert find("see https://shop.com/products/123456789 please", expecting_phone=True).problems == []


def test_greetings_are_not_names():
    for text in ["Hello there", "hi", "Good morning", "ok", "السلام عليكم"]:
        assert not valid_name(clean_name(text)), text
    assert valid_name(clean_name("Hello, I'm Noor"))
