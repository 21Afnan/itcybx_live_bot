"""Tells the team about a complete lead: an email and a new Google Sheet row.

Runs in the background after the visitor's reply, so it never slows the
chat. If one channel fails the other still goes out; notified_at is only
set when every configured channel worked. An hourly job (app/jobs.py)
retries the leads whose alerts didn't all go out.
"""

import asyncio
import json
import logging
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import httpx
from google.auth import crypt, jwt

from app.config import settings
from app.db import repo
from app.graph.state import ChatState
from app.llm.models import TASK_SYSTEM, LLMUnavailable, Usage, stream_reply

log = logging.getLogger("chatbot.leads")

SHEET_COLUMNS = ["Date (UTC)", "Name", "Email", "WhatsApp", "Platform", "Market", "Store URL",
                 "Language", "Source page", "Chat summary"]


async def chat_summary(state: ChatState) -> str:
    """A short AI summary of the chat for the team."""
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in state.get("messages", []))
    question = (
        "Summarise this website chat for the IT Cybx sales team in 3 short bullet points: "
        "who the visitor is, what they need, and anything they asked about. English only. "
        "Reply with the bullets only.\n\n" + transcript
    )
    try:
        parts = [t async for t in stream_reply(question, "en", [], Usage(), system=TASK_SYSTEM)]
        return "".join(parts).strip()
    except LLMUnavailable:
        return "(summary unavailable)"


def lead_row(state: ChatState, source_page: str, summary: str) -> list[str]:
    lead = state["lead"]
    return [
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        state.get("name", ""), lead.get("email", ""), lead.get("whatsapp", ""),
        lead.get("platform", ""), lead.get("market", ""), lead.get("store_url", ""),
        state.get("language", ""), source_page or "", summary,
    ]


# ---- email --------------------------------------------------------------


def build_email(row: list[str]) -> EmailMessage:
    fields = dict(zip(SHEET_COLUMNS, row))
    msg = EmailMessage()
    details = ", ".join(v for v in (fields["Platform"], fields["Market"]) if v)
    msg["Subject"] = f"New chatbot lead: {fields['Name']}" + (f" ({details})" if details else "")
    msg["From"] = settings.smtp_user
    msg["To"] = settings.lead_email_to
    msg["Reply-To"] = fields["Email"]
    body = "\n".join(f"{k}: {v or '-'}" for k, v in fields.items() if k != "Chat summary")
    msg.set_content(f"A visitor finished sharing their details in the website chat.\n\n"
                    f"{body}\n\nChat summary:\n{fields['Chat summary']}\n")
    return msg


def _send(msg: EmailMessage) -> None:
    password = settings.smtp_password.get_secret_value()
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.login(settings.smtp_user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, password)
            smtp.send_message(msg)


async def send_email(row: list[str]) -> None:
    await asyncio.to_thread(_send, build_email(row))


async def send_text_email(subject: str, body: str) -> None:
    """A plain email to the team (used by the weekly website check)."""
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, settings.smtp_user, settings.lead_email_to
    msg.set_content(body)
    await asyncio.to_thread(_send, msg)


# ---- Google Sheet -------------------------------------------------------


async def google_token(client: httpx.AsyncClient) -> str:
    """An access token for the Sheets API, from the service account's key file."""
    info = json.loads(Path(settings.google_service_account_json).read_text(encoding="utf-8"))
    now = int(time.time())
    assertion = jwt.encode(crypt.RSASigner.from_service_account_info(info), {
        "iss": info["client_email"], "aud": info["token_uri"], "iat": now, "exp": now + 600,
        "scope": "https://www.googleapis.com/auth/spreadsheets",
    })
    resp = await client.post(info["token_uri"], data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion.decode() if isinstance(assertion, bytes) else assertion,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


async def append_to_sheet(row: list[str]) -> None:
    """Add one row at the bottom of the leads sheet's first tab."""
    async with httpx.AsyncClient(timeout=20) as client:
        token = await google_token(client)
        resp = await client.post(
            f"https://sheets.googleapis.com/v4/spreadsheets/{settings.google_sheet_id}"
            f"/values/A1:append",
            params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
            headers={"Authorization": f"Bearer {token}"},
            json={"values": [row]},
        )
        resp.raise_for_status()


# ---- both ---------------------------------------------------------------


RETRY_DELAYS = [10, 60]  # seconds before the 2nd and 3rd try of a failed alert
RETRY_WINDOW = (timedelta(minutes=15), timedelta(days=1))  # leads the hourly retry looks at


def channels() -> dict:
    """The alert channels that are set up in .env, by name."""
    configured = {
        "email": (send_email, bool(settings.smtp_host and settings.smtp_user)),
        "sheet": (append_to_sheet, bool(settings.google_sheet_id and settings.google_service_account_json)),
    }
    return {name: send for name, (send, ok) in configured.items() if ok}


async def with_retries(send, row: list[str]) -> None:
    """Try an alert up to 3 times, waiting a little longer each time."""
    for delay in [*RETRY_DELAYS, None]:
        try:
            return await send(row)
        except Exception:
            if delay is None:
                raise
            await asyncio.sleep(delay)


async def notify_team(state: ChatState) -> None:
    """Email + Sheet row for a complete lead.

    Each channel is tried a few times. Channels that already worked for this
    lead are skipped, so the hourly retry never sends the same alert twice.
    """
    session_id = state["session_id"]
    if not channels():
        log.warning("New lead, but no alert channel is set up (SMTP_* / GOOGLE_SHEET_ID in .env)")
        return
    todo = {name: send for name, send in channels().items()
            if name not in await repo.sent_alerts(session_id)}
    if todo:
        conversation = await repo.find_conversation(session_id)
        row = lead_row(state, conversation.source_page if conversation else "",
                       await chat_summary(state))
        results = await asyncio.gather(*(with_retries(send, row) for send in todo.values()),
                                       return_exceptions=True)
        failed = False
        for name, result in zip(todo, results):
            if isinstance(result, Exception):
                failed = True
                log.error("Lead alert by %s failed: %s", name, type(result).__name__)
            else:
                await repo.mark_alert_sent(session_id, name)
        if failed:
            return
    await repo.mark_lead_notified(session_id)


async def retry_unsent_alerts() -> None:
    """Hourly: resend the alerts of leads that are still not fully notified
    (the server restarted mid-alert, or SMTP / Google was down)."""
    try:
        conversations = await repo.unnotified_leads(*RETRY_WINDOW)
    except Exception:
        log.exception("Could not look for unsent lead alerts")
        return
    for conversation in conversations:
        try:
            await notify_team(await repo.rebuild_state(conversation))
        except Exception:
            log.exception("Lead alert retry failed")
