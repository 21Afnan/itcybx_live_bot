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
    print("\n[1/3] Testing GET / and GET /health ...")
    r_root = client.get("/")
    assert r_root.status_code == 200, f"Root failed: {r_root.text}"
    print("  • GET / -> Status:", r_root.status_code, "|", r_root.json().get("service"))

    r_health = client.get("/health")
    assert r_health.status_code == 200, f"Health check failed: {r_health.text}"
    print("  • GET /health -> Status:", r_health.status_code, "|", r_health.json().get("status"))

    # 2. Chat Endpoint (English)
    print("\n[2/3] Testing POST /api/chat (English) ...")
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

    # 3. Session History Retrieval (requires ADMIN_API_KEY to be configured)
    print(f"\n[3/3] Testing GET /api/session/{session_id} ...")
    import os
    admin_key = os.environ.get("ADMIN_API_KEY", "")
    if admin_key:
        r_sess = client.get(f"/api/session/{session_id}", headers={"X-Admin-Api-Key": admin_key})
        assert r_sess.status_code == 200, f"Session retrieval failed: {r_sess.text}"
        history_data = r_sess.json()
        print(f"  • Retrieved {history_data.get('turns_count')} turns in session history.")
    else:
        print("  • Skipped: set ADMIN_API_KEY to test this admin-only endpoint.")

    print("\n=======================================================")
    print("           ALL API ENDPOINTS TESTED SUCCESSFULLY!      ")
    print("=======================================================\n")


if __name__ == "__main__":
    test_api_endpoints()
