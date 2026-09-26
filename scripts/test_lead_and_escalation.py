# scripts/test_lead_and_escalation.py

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
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

from src.tools.lead_tool import capture_lead, load_all_leads, LEADS_FILE
from src.tools.escalation_tool import escalate_to_human, load_all_escalations, ESCALATIONS_FILE
from src.agent.graph import get_agent


def test_direct_lead_and_escalation_tools():
    print("\n=======================================================")
    print("      TEST 1: DIRECT LEAD & ESCALATION TOOLS           ")
    print("=======================================================")

    print("\n[Tool Test] capture_lead (English):")
    res_en = capture_lead.invoke({
        "name": "David Miller",
        "email": "david@glowbeauty.com",
        "phone": "+44 789 555 1234",
        "store_url_or_name": "glowbeauty.com",
        "platform": "Shopify",
        "service_interest": "The Growth Audit ($150)",
        "notes": "Looking to increase mobile conversion rate from 1.2% to 2.5%",
        "language": "en"
    })
    print(res_en)

    print("\n[Tool Test] capture_lead (Arabic):")
    res_ar = capture_lead.invoke({
        "name": "عبدالعزيز الغامدي",
        "email": "abdulaziz@perfumery.sa",
        "phone": "+966 50 123 4567",
        "store_url_or_name": "عطور النخبة",
        "platform": "سلة (Salla)",
        "service_interest": "تطوير المتجر وزيادة المبيعات",
        "notes": "متجر عطور فاخرة في الرياض",
        "language": "ar"
    })
    print(res_ar)

    print("\n[Tool Test] escalate_to_human (English):")
    esc_res_en = escalate_to_human.invoke({
        "reason": "Client has $5M GMV portfolio requesting custom enterprise contract and SLA",
        "user_contact": "david@glowbeauty.com",
        "urgency": "HIGH",
        "summary": "Owner wants a dedicated strategist for 3 regional storefronts.",
        "language": "en"
    })
    print(esc_res_en)

    print("\n[Tool Test] escalate_to_human (Arabic):")
    esc_res_ar = escalate_to_human.invoke({
        "reason": "طلب اتصال هاتفي مباشر مع المدير التنفيذي لمناقشة عقد سنوي",
        "user_contact": "+966 50 123 4567",
        "urgency": "HIGH",
        "summary": "العميل يرغب في باقة نمو سنوية متكاملة لـ 3 متاجر.",
        "language": "ar"
    })
    print(esc_res_ar)


def test_agent_lead_capture_conversational_en():
    print("\n=======================================================")
    print("      TEST 2: AGENT CONVERSATIONAL LEAD CAPTURE (EN)   ")
    print("=======================================================")
    import time
    time.sleep(2)
    agent = get_agent()
    thread_id = f"test_lead_en_{uuid.uuid4().hex[:4]}"

    print("\n[User]: Hi! I am interested in getting the Growth Audit for my Shopify store. My name is Jessica and my email is jessica@lumistore.co.uk")
    r1 = agent.chat("Hi! I am interested in getting the Growth Audit for my Shopify store. My name is Jessica and my email is jessica@lumistore.co.uk", thread_id=thread_id, language="en")
    print("\n[Agent]:\n" + r1)


def test_agent_escalation_conversational_ar():
    print("\n=======================================================")
    print("      TEST 3: AGENT CONVERSATIONAL ESCALATION (AR)     ")
    print("=======================================================")
    import time
    time.sleep(2)
    agent = get_agent()
    thread_id = f"test_esc_ar_{uuid.uuid4().hex[:4]}"

    print("\n[User]: أريد التحدث مع أحد مدراء الفريق لديكم فوراً بخصوص مشروع خاص بمتجري، رقمي 0555123456")
    r1 = agent.chat("أريد التحدث مع أحد مدراء الفريق لديكم فوراً بخصوص مشروع خاص بمتجري، رقمي 0555123456", thread_id=thread_id, language="ar")
    print("\n[Agent]:\n" + r1)


def verify_storage():
    print("\n=======================================================")
    print("      TEST 4: VERIFY SAVED DATA IN JSON STORAGE       ")
    print("=======================================================")
    leads = load_all_leads()
    print(f"Total Leads in '{LEADS_FILE.name}': {len(leads)}")
    for idx, lead in enumerate(leads[-3:], 1):
        print(f"  {idx}. [{lead.get('lead_id')}] {lead.get('name')} ({lead.get('email')}) -> {lead.get('service_interest')}")

    escalations = load_all_escalations()
    print(f"\nTotal Escalations in '{ESCALATIONS_FILE.name}': {len(escalations)}")
    for idx, esc in enumerate(escalations[-3:], 1):
        print(f"  {idx}. [{esc.get('escalation_id')}] {esc.get('reason')} -> {esc.get('user_contact')} [{esc.get('urgency')}]")


if __name__ == "__main__":
    test_direct_lead_and_escalation_tools()
    test_agent_lead_capture_conversational_en()
    test_agent_escalation_conversational_ar()
    verify_storage()
