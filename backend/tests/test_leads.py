"""Tests for lead alerts (email + Google Sheet). Nothing is really sent."""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.leads import notify

STATE = {
    "session_id": "00000000-0000-0000-0000-000000000001",
    "name": "Sara", "language": "en", "lead_status": "complete",
    "lead": {"email": "sara@glow.sa", "whatsapp": "+966501234567", "platform": "Salla",
             "market": "KSA", "store_url": "https://glow.sa"},
    "messages": [{"role": "user", "content": "How much is the audit?"}],
}


def test_sheet_row_has_every_column_in_order():
    row = notify.lead_row(STATE, "https://itcybx.co.uk/pricing/", "- wants an audit")
    assert len(row) == len(notify.SHEET_COLUMNS)
    assert row[1:] == ["Sara", "sara@glow.sa", "+966501234567", "Salla", "KSA", "https://glow.sa",
                       "en", "https://itcybx.co.uk/pricing/", "- wants an audit"]


def test_email_has_subject_details_and_reply_to(monkeypatch):
    monkeypatch.setattr(notify.settings, "smtp_user", "info@itcybx.co.uk")
    monkeypatch.setattr(notify.settings, "lead_email_to", "team@itcybx.co.uk")
    msg = notify.build_email(notify.lead_row(STATE, "", "- wants an audit"))
    assert msg["Subject"] == "New chatbot lead: Sara (Salla, KSA)"
    assert msg["To"] == "team@itcybx.co.uk"
    assert msg["Reply-To"] == "sara@glow.sa"
    body = msg.get_content()
    assert "WhatsApp: +966501234567" in body and "- wants an audit" in body


@pytest.fixture
def alerts(monkeypatch):
    """Both channels set up, no waiting between retries, the database faked."""
    sent = {"email": [], "sheet": [], "notified": [], "done": set()}

    async def summary(state):
        return "- summary"

    async def find_conversation(session_id):
        return None

    async def sent_alerts(session_id):
        return set(sent["done"])

    async def mark_alert_sent(session_id, channel):
        sent["done"].add(channel)

    async def mark(session_id):
        sent["notified"].append(session_id)

    @asynccontextmanager
    async def alert_lock(session_id):
        yield sent.get("lock_free", True)

    for name, value in [("smtp_host", "smtp.example"), ("smtp_user", "info@itcybx.co.uk"),
                        ("google_sheet_id", "sheet-1"), ("google_service_account_json", "/sa.json")]:
        monkeypatch.setattr(notify.settings, name, value)
    monkeypatch.setattr(notify, "RETRY_DELAYS", [0, 0])
    monkeypatch.setattr(notify, "chat_summary", summary)
    monkeypatch.setattr(notify.repo, "find_conversation", find_conversation)
    monkeypatch.setattr(notify.repo, "sent_alerts", sent_alerts)
    monkeypatch.setattr(notify.repo, "mark_alert_sent", mark_alert_sent)
    monkeypatch.setattr(notify.repo, "mark_lead_notified", mark)
    monkeypatch.setattr(notify.repo, "alert_lock", alert_lock)
    return sent


def test_alert_already_running_elsewhere_is_not_sent_twice(monkeypatch, alerts):
    alerts["lock_free"] = False  # another worker holds this lead's alert lock
    async def email(row): alerts["email"].append(row)
    monkeypatch.setattr(notify, "send_email", email)

    asyncio.run(notify.notify_team(STATE))

    assert alerts["email"] == [] and alerts["notified"] == []


def test_both_channels_sent_and_lead_marked(monkeypatch, alerts):
    async def email(row): alerts["email"].append(row)
    async def sheet(row): alerts["sheet"].append(row)
    monkeypatch.setattr(notify, "send_email", email)
    monkeypatch.setattr(notify, "append_to_sheet", sheet)

    asyncio.run(notify.notify_team(STATE))

    assert len(alerts["email"]) == 1 and len(alerts["sheet"]) == 1
    assert alerts["notified"] == [STATE["session_id"]]


def test_one_channel_failing_still_sends_the_other(monkeypatch, alerts):
    async def email(row): raise ConnectionError("smtp down")
    async def sheet(row): alerts["sheet"].append(row)
    monkeypatch.setattr(notify, "send_email", email)
    monkeypatch.setattr(notify, "append_to_sheet", sheet)

    asyncio.run(notify.notify_team(STATE))

    assert len(alerts["sheet"]) == 1
    assert alerts["done"] == {"sheet"}
    assert alerts["notified"] == []  # not marked: the team didn't get both


def test_failed_alert_is_tried_again(monkeypatch, alerts):
    tries = []

    async def email(row):
        tries.append(row)
        if len(tries) < 3:
            raise ConnectionError("smtp busy")
    async def sheet(row): alerts["sheet"].append(row)
    monkeypatch.setattr(notify, "send_email", email)
    monkeypatch.setattr(notify, "append_to_sheet", sheet)

    asyncio.run(notify.notify_team(STATE))

    assert len(tries) == 3
    assert alerts["notified"] == [STATE["session_id"]]


def test_later_retry_only_resends_what_failed(monkeypatch, alerts):
    alerts["done"].add("sheet")  # the sheet row went in on the first attempt
    async def email(row): alerts["email"].append(row)
    async def sheet(row): alerts["sheet"].append(row)
    monkeypatch.setattr(notify, "send_email", email)
    monkeypatch.setattr(notify, "append_to_sheet", sheet)

    asyncio.run(notify.notify_team(STATE))

    assert len(alerts["email"]) == 1 and alerts["sheet"] == []
    assert alerts["notified"] == [STATE["session_id"]]


def test_channel_not_set_up_is_skipped(monkeypatch, alerts):
    monkeypatch.setattr(notify.settings, "google_sheet_id", "")
    async def email(row): alerts["email"].append(row)
    monkeypatch.setattr(notify, "send_email", email)

    asyncio.run(notify.notify_team(STATE))

    assert len(alerts["email"]) == 1
    assert alerts["notified"] == [STATE["session_id"]]


def test_no_channel_set_up_leaves_the_lead_for_the_hourly_retry(monkeypatch, alerts):
    monkeypatch.setattr(notify.settings, "smtp_host", "")
    monkeypatch.setattr(notify.settings, "google_sheet_id", "")

    asyncio.run(notify.notify_team(STATE))

    assert alerts["notified"] == []


def test_google_token_is_requested_with_a_signed_key(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    key_file = tmp_path / "sa.json"
    key_file.write_text(json.dumps({"client_email": "bot@x.iam.gserviceaccount.com", "private_key": pem,
                                    "private_key_id": "1", "token_uri": "https://oauth2.example/token"}))
    monkeypatch.setattr(notify.settings, "google_service_account_json", str(key_file))
    seen = {}

    def token_server(request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "abc"})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(token_server)) as client:
            return await notify.google_token(client)

    assert asyncio.run(go()) == "abc"
    assert "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer" in seen["body"]
    assert "assertion=" in seen["body"]
