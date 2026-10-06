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
# 2026-10-06, 06/10/2026, 6.10.26: never phone numbers.
DATE = re.compile(r"\b(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})\b")
# Country codes of the markets we serve (KSA, UAE, Qatar, Kuwait, Bahrain, Oman,
# UK, Pakistan). People often write them without "+": 966501234567.
COUNTRY_CODES = ("966", "971", "974", "965", "973", "968", "44", "92")

PLATFORMS = {
    "shopify": "Shopify", "شوبيفاي": "Shopify",
    "salla": "Salla", "zid": "Zid",
    "woocommerce": "other", "magento": "other", "wix": "other", "bigcommerce": "other",
}

# In Arabic, سلة also means "basket" (سلة التسوق, the shopping cart) and زد
# means "increase" (زد مبيعاتي). They count as platforms only after a word
# that points at a platform, or when the bot has just asked for the platform.
ARABIC_PLATFORMS = {"سلة": "Salla", "زد": "Zid"}
PLATFORM_LEADS = ["على", "منصة", "متجر", "متجري", "متجرنا", "عبر", "نستخدم", "أستخدم", "استخدم"]

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
    # Not a bare "كم" ("how many / how much"): it starts most Arabic questions.
    "سعر", "السعر", "الأسعار", "تكلفة", "التكلفة", "بكم", "كم سعر", "كم السعر", "كم تكلفة",
    "كم التكلفة", "تقييم", "حجز", "احجز", "تواصل", "اتصال", "مكالمة", "شخص",
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

# A first word that starts a question or a request, not a name ("what do you do",
# "can you help", "I need ads"). "I am Sara" is fine: clean_name drops "I am".
NOT_NAME_START = {
    "what", "whats", "what's", "how", "why", "when", "where", "who", "which", "can", "could",
    "would", "should", "do", "does", "did", "is", "are", "was", "will", "tell", "i", "we",
    "my", "our", "need", "want", "please", "looking", "show", "give",
    "هل", "ما", "ماذا", "كيف", "كم", "لماذا", "متى", "أين", "وين", "ممكن", "أريد", "اريد",
    "أبغى", "ابغى", "ابي", "أبي", "عندي", "نحن", "عندنا",
}

# Words about the store or the service, never part of a name ("Shopify store").
BUSINESS_WORDS = {
    "store", "shop", "website", "site", "sales", "ads", "marketing", "audit", "seo", "ecommerce",
    "e-commerce", "متجر", "متجري", "مبيعات", "تسويق", "إعلانات", "اعلانات", "موقع",
    *PLATFORMS, *ARABIC_PLATFORMS,
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
    words = [w.strip(",.!") for w in name.lower().split()]
    return (
        2 <= len(name) <= 60
        and len(words) <= 4
        and not any(ch in name for ch in "?؟@/:")
        and not any(ch.isdigit() for ch in name)
        and not all(word in NOT_NAME_WORDS for word in words)
        and not looks_like_question(name)
    )


def looks_like_question(text: str) -> bool:
    """The visitor asked something instead of giving their name."""
    words = [w.strip(",.!") for w in text.lower().split()]
    return bool(words) and (
        any(ch in text for ch in "?؟")
        or words[0] in NOT_NAME_START
        or any(word in BUSINESS_WORDS for word in words)
    )


def clean_name(text: str) -> str:
    """'My name is Sara.' / 'I'm Sara' / 'اسمي سارة' -> 'Sara' / 'سارة'."""
    text = text.strip().strip(".!")
    text = re.sub(r"^(hi|hello|hey|salam|مرحبا|أهلا)[,!\s]+", "", text, flags=re.I)
    text = re.sub(r"^(my name is|my name's|i am|i'm|it's|this is|name:|اسمي|أنا)\s+", "", text, flags=re.I)
    text = " ".join(text.split())  # one line: the name goes into the alert email's subject
    return text.strip().strip(".!")[:60]


def normalise_phone(raw: str, expecting_phone: bool = False) -> str:
    """Digits only, with a leading +. '00966 50-123 4567' -> '+966501234567'.

    When the number is meant as a phone, one that starts with a known country
    code and has the full length gets its "+": '966501234567' -> '+966501234567'.
    """
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("00"):
        digits = digits[2:]
        return "+" + digits
    if raw.strip().startswith("+"):
        return "+" + digits
    if expecting_phone and 11 <= len(digits) <= 12 and digits.startswith(COUNTRY_CODES):
        return "+" + digits
    return digits


def find(text: str, expecting_phone: bool = False, expecting_platform: bool = False) -> Found:
    """Look for email, WhatsApp, platform, market and store URL in a message.

    A number without a country code is only flagged when it is meant as a
    phone number: the bot just asked for one, or the message says so.
    Otherwise "we do 10000000 a year" would be taken for a phone number.
    `expecting_platform`: the bot just asked for the platform, so a bare
    "سلة" or "زد" is the answer.
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
    for match in PHONE.findall(DATE.sub(" ", plain)):
        number = normalise_phone(match, expecting_phone)
        if E164.match(number):
            found.whatsapp = number
            break
        if expecting_phone and len(re.sub(r"\D", "", number)) >= 7:
            found.problems.append("whatsapp_needs_country_code")

    for word, platform in PLATFORMS.items():
        if mentions(lower, [word]):
            found.platform = platform
            break
    else:
        for word, platform in ARABIC_PLATFORMS.items():
            pointed_at = [f"{lead} {word}" for lead in PLATFORM_LEADS]
            if mentions(lower, pointed_at) or (expecting_platform and mentions(lower, [word])):
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
