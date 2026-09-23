# scripts/test_booking.py

import sys
from pathlib import Path
import json
import uuid

# Fix Python path to resolve src modules from any working directory
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Fix Windows console encoding for Arabic characters
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

from src.tools.booking_tool import check_availability, book_meeting, BOOKINGS_FILE
from src.agent.graph import get_agent



def test_direct_tools():
    print("\n=======================================================")
    print("      TEST 1: DIRECT TOOL EXECUTION (EN & AR)          ")
    print("=======================================================")

    print("\n[Tool Test] check_availability(language='en'):")
    res_en = check_availability.invoke({"language": "en"})
    print(res_en)

    print("\n[Tool Test] check_availability(language='ar'):")
    res_ar = check_availability.invoke({"language": "ar"})
    print(res_ar)

    print("\n[Tool Test] book_meeting(name='John Doe', email='john@example.com', slot_time='Sunday at 2:00 PM'):")
    book_res_en = book_meeting.invoke({
        "name": "John Doe",
        "email": "john@example.com",
        "slot_time": "Sunday at 2:00 PM",
        "notes": "Interested in CRO Audit",
        "language": "en"
    })
    print(book_res_en)

    print("\n[Tool Test] book_meeting in Arabic:")
    book_res_ar = book_meeting.invoke({
        "name": "سعد القحطاني",
        "email": "saad@example.com",
        "slot_time": "يوم الإثنين الساعة 3:00 مساءً",
        "notes": "متجر سلة لمنتجات العناية",
        "language": "ar"
    })
    print(book_res_ar)


def test_agent_multiturn_booking_en():
    print("\n=======================================================")
    print("      TEST 2: AGENT MULTI-TURN BOOKING (ENGLISH)       ")
    print("=======================================================")
    agent = get_agent()
    thread_id = f"test_booking_en_{uuid.uuid4().hex[:4]}"

    # Turn 1: Ask for consultation slots
    print("\n[User]: I want to book a consultation call for my Shopify store. When are you available?")
    r1 = agent.chat("I want to book a consultation call for my Shopify store. When are you available?", thread_id=thread_id, language="en")
    print("\n[Agent]:\n" + r1)

    # Turn 2: Select slot and provide details
    print("\n[User]: Let's book for Sunday at 2:00 PM. My name is Alex Smith and my email is alex.smith@brand.com")
    r2 = agent.chat("Let's book for Sunday at 2:00 PM. My name is Alex Smith and my email is alex.smith@brand.com", thread_id=thread_id, language="en")
    print("\n[Agent]:\n" + r2)


def test_agent_multiturn_booking_ar():
    print("\n=======================================================")
    print("      TEST 3: AGENT MULTI-TURN BOOKING (ARABIC)        ")
    print("=======================================================")
    agent = get_agent()
    thread_id = f"test_booking_ar_{uuid.uuid4().hex[:4]}"

    # Turn 1: Ask for consultation slots in Arabic
    print("\n[User]: مرحباً، أرغب بحجز موعد استشارة لمتجري الإلكتروني. ما هي المواعيد المتاحة لديكم؟")
    r1 = agent.chat("مرحباً، أرغب بحجز موعد استشارة لمتجري الإلكتروني. ما هي المواعيد المتاحة لديكم؟", thread_id=thread_id, language="ar")
    print("\n[Agent]:\n" + r1)

    # Turn 2: Select slot and provide details in Arabic
    print("\n[User]: أنا أختار يوم الإثنين الساعة 2:00 مساءً، اسمي فيصل السبيعي وإيميلي faisal@brand.sa")
    r2 = agent.chat("أنا أختار يوم الإثنين الساعة 2:00 مساءً، اسمي فيصل السبيعي وإيميلي faisal@brand.sa", thread_id=thread_id, language="ar")
    print("\n[Agent]:\n" + r2)


def check_saved_bookings():
    print("\n=======================================================")
    print("      TEST 4: VERIFY SAVED BOOKINGS IN STORAGE        ")
    print("=======================================================")
    if BOOKINGS_FILE.exists():
        with open(BOOKINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"Total Bookings in '{BOOKINGS_FILE.name}': {len(data)}")
        for idx, item in enumerate(data[-4:], 1):
            print(f"{idx}. [{item.get('booking_id')}] {item.get('name')} ({item.get('email')}) -> {item.get('slot_time')} | Status: {item.get('status')}")
    else:
        print(f"File {BOOKINGS_FILE} not found!")


if __name__ == "__main__":
    test_direct_tools()
    test_agent_multiturn_booking_en()
    test_agent_multiturn_booking_ar()
    check_saved_bookings()
