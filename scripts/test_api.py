# scripts/test_api.py

import sys
import time
from pathlib import Path

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

from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_api_endpoints():
    print("\n=======================================================")
    print("           FASTAPI BACKEND ENDPOINT TESTS              ")
    print("=======================================================")

    # 1. Root & Health Check
    print("\n[1/5] Testing GET / and GET /health ...")
    r_root = client.get("/")
    assert r_root.status_code == 200, f"Root failed: {r_root.text}"
    print("  • GET / -> Status:", r_root.status_code, "|", r_root.json().get("service"))

    r_health = client.get("/health")
    assert r_health.status_code == 200, f"Health check failed: {r_health.text}"
    print("  • GET /health -> Status:", r_health.status_code, "|", r_health.json().get("status"))

    # 2. Chat Endpoint (English)
    print("\n[2/5] Testing POST /api/chat (English) ...")
    time.sleep(2)  # Respect free tier rate limit
    session_id = f"test_api_sess_{int(time.time())}"
    r_chat_en = client.post("/api/chat", json={
        "message": "What is the Growth Audit and how much does it cost?",
        "session_id": session_id,
        "language": "en"
    })
    assert r_chat_en.status_code == 200, f"Chat EN failed: {r_chat_en.text}"
    data_en = r_chat_en.json()
    print("  • Bot Response (EN):\n", data_en.get("response")[:250], "...\n")

    # 3. Session History Retrieval
    print(f"\n[3/5] Testing GET /api/session/{session_id} ...")
    r_sess = client.get(f"/api/session/{session_id}")
    assert r_sess.status_code == 200, f"Session retrieval failed: {r_sess.text}"
    history_data = r_sess.json()
    print(f"  • Retrieved {history_data.get('turns_count')} turns in session history.")

    # 4. Direct Leads Submission & Listing
    print("\n[4/5] Testing POST /api/leads and GET /api/leads ...")
    r_lead_post = client.post("/api/leads", json={
        "name": "Marcus Vance",
        "email": "marcus@velocitybrand.co.uk",
        "phone": "+44 792 111 2233",
        "store_url_or_name": "velocitybrand.co.uk",
        "platform": "Shopify Plus",
        "service_interest": "Conversion Rate Optimization Sprint",
        "notes": "Looking to migrate and optimize checkout before Black Friday",
        "language": "en"
    })
    assert r_lead_post.status_code == 200, f"Lead post failed: {r_lead_post.text}"
    print("  • Lead submitted successfully! Response snippet:")
    print("   ", r_lead_post.json().get("confirmation")[:160], "...")

    r_leads_list = client.get("/api/leads")
    assert r_leads_list.status_code == 200
    print(f"  • Total leads in database: {r_leads_list.json().get('total_leads')}")

    # 5. Direct Escalation Endpoint
    print("\n[5/5] Testing POST /api/escalate and GET /api/escalations ...")
    r_esc_post = client.post("/api/escalate", json={
        "reason": "Enterprise inquiry for 5 regional storefronts",
        "user_contact": "marcus@velocitybrand.co.uk",
        "urgency": "HIGH",
        "summary": "Owner wants a direct discussion regarding bespoke retainer agreement.",
        "language": "en"
    })
    assert r_esc_post.status_code == 200, f"Escalation post failed: {r_esc_post.text}"
    print("  • Escalation submitted successfully!")

    r_esc_list = client.get("/api/escalations")
    assert r_esc_list.status_code == 200
    print(f"  • Total escalations recorded: {r_esc_list.json().get('total_escalations')}")

    print("\n=======================================================")
    print("           ALL API ENDPOINTS TESTED SUCCESSFULLY!      ")
    print("=======================================================\n")


if __name__ == "__main__":
    test_api_endpoints()
