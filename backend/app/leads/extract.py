"""Finds lead details in a visitor's message and checks they are valid.

Pattern matching only, no AI: fast, free and predictable. Validation rules
come from PLAN.md → "Lead fields".
"""

import re
from dataclasses import dataclass, field

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?:\+|00)?\d[\d\s().-]{6,18}\d")
URL_WITH_SCHEME = re.compile(r"https?://[^\s]+", re.I)
# Without http://, only accept common shop endings, so "Mr.Smith" is not a website.
URL_BARE = re.compile(
    r"(?<![\w@])(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\."
    r"(?:com|net|org|co|uk|sa|ae|qa|kw|bh|om|pk|store|shop|online|io|me|app)(?:/[^\s]*)?(?!\w)",
    re.I,
)
E164 = re.compile(r"^\+[1-9]\d{7,14}$")

PLATFORMS = {
    "shopify": "Shopify", "شوبيفاي": "Shopify",
    "salla": "Salla", "سلة": "Salla",
    "zid": "Zid", "زد": "Zid",
    "woocommerce": "other", "magento": "other", "wix": "other", "bigcommerce": "other",
}

MARKETS = {
    "ksa": "KSA", "saudi": "KSA", "riyadh": "KSA", "jeddah": "KSA", "السعودية": "KSA", "الرياض": "KSA",
    "uae": "GCC", "dubai": "GCC", "qatar": "GCC", "kuwait": "GCC", "bahrain": "GCC", "oman": "GCC",
    "gcc": "GCC", "الإمارات": "GCC", "قطر": "GCC", "الكويت": "GCC", "الخليج": "GCC",
    "uk": "UK", "united kingdom": "UK", "britain": "UK", "london": "UK", "england": "UK",
    "بريطانيا": "UK", "المملكة المتحدة": "UK",
}

INTEREST_WORDS = [
    "price", "pricing", "cost", "how much", "quote", "audit", "book", "booking", "work with you",
    "work together", "hire", "get started", "sign up", "talk to", "speak to", "call", "contact",
    "someone", "person", "human", "meeting",
    "سعر", "الأسعار", "تكلفة", "كم", "تقييم", "حجز", "احجز", "تواصل", "اتصال", "مكالمة", "شخص",
]

# Words that show a number in the message is meant as a phone number.
PHONE_WORDS = [
    "whatsapp", "phone", "number", "mobile", "cell", "call me", "text me", "reach me",
    "واتساب", "رقم", "جوال", "هاتف", "موبايل",
]

# Greetings and filler that are not a name ("Hello there", "ok", "السلام عليكم").
NOT_NAME_WORDS = {
    "hi", "hello", "hey", "there", "salam", "salaam", "assalam", "assalamualaikum", "o", "alaikum",
    "good", "morning", "afternoon", "evening", "yes", "no", "ok", "okay", "sure", "thanks",
    "thank", "you", "help", "test", "price", "pricing",
    "مرحبا", "أهلا", "اهلا", "السلام", "عليكم", "نعم", "لا", "شكرا",
}

CONTACT_WORDS = [
    "talk to", "speak to", "call me", "contact", "someone", "person", "human", "whatsapp",
    "email you", "book", "تواصل", "اتصال", "مكالمة", "شخص", "واتساب",
]


@dataclass
class Found:
    """Lead details found in one message. Empty fields were not mentioned."""

    email: str = ""
    whatsapp: str = ""
    platform: str = ""
    market: str = ""
    store_url: str = ""
    problems: list[str] = field(default_factory=list)  # e.g. "whatsapp_needs_country_code"


def valid_name(name: str) -> bool:
    """2-60 characters, and looks like a name rather than a question or contact detail."""
    name = name.strip()
    return (
        2 <= len(name) <= 60
        and len(name.split()) <= 4
        and not any(ch in name for ch in "?؟@/:")
        and not any(ch.isdigit() for ch in name)
        and not all(word in NOT_NAME_WORDS for word in name.lower().split())
    )


def clean_name(text: str) -> str:
    """'My name is Sara.' / 'I'm Sara' / 'اسمي سارة' -> 'Sara' / 'سارة'."""
    text = text.strip().strip(".!")
    text = re.sub(r"^(hi|hello|hey|salam|مرحبا|أهلا)[,!\s]+", "", text, flags=re.I)
    text = re.sub(r"^(my name is|my name's|i am|i'm|it's|this is|name:|اسمي|أنا)\s+", "", text, flags=re.I)
    return text.strip().strip(".!")[:60]


def normalise_phone(raw: str) -> str:
    """Digits only, with a leading +. '00966 50-123 4567' -> '+966501234567'."""
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("00"):
        digits = digits[2:]
        return "+" + digits
    return ("+" + digits) if raw.strip().startswith("+") else digits


def find(text: str, expecting_phone: bool = False) -> Found:
    """Look for email, WhatsApp, platform, market and store URL in a message.

    A number without a country code is only flagged when it is meant as a
    phone number: the bot just asked for one, or the message says so.
    Otherwise "we do 10000000 a year" would be taken for a phone number.
    """
    found = Found()

    emails = EMAIL.findall(text)
    if emails:
        found.email = emails[0].lower()

    without_emails = EMAIL.sub(" ", text)
    match = URL_WITH_SCHEME.search(without_emails) or URL_BARE.search(without_emails)
    if match:
        url = match.group(0).rstrip(".,)")
        found.store_url = url if url.lower().startswith("http") else "https://" + url

    # Phone, platform and market are looked for outside emails and links, so
    # "mystore.co.uk" does not mean the market is the UK.
    plain = URL_BARE.sub(" ", URL_WITH_SCHEME.sub(" ", without_emails))
    lower = plain.lower()
    expecting_phone = expecting_phone or mentions(lower, PHONE_WORDS)
    for match in PHONE.findall(plain):
        number = normalise_phone(match)
        if E164.match(number):
            found.whatsapp = number
            break
        if expecting_phone and len(re.sub(r"\D", "", number)) >= 7:
            found.problems.append("whatsapp_needs_country_code")

    for word, platform in PLATFORMS.items():
        if mentions(lower, [word]):
            found.platform = platform
            break

    for word, market in MARKETS.items():
        if mentions(lower, [word]):
            found.market = market
            break

    return found


def mentions(text: str, words: list[str]) -> bool:
    """True if any word appears as a whole word ("book", but not "facebook")."""
    lower = text.lower()
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", lower) for w in words)


def shows_interest(text: str) -> bool:
    """True when the visitor asks about price, the audit, or talking to someone."""
    return mentions(text, INTEREST_WORDS)


def wants_contact(text: str) -> bool:
    """True when the visitor asks to talk to someone or how to reach the team."""
    return mentions(text, CONTACT_WORDS)
