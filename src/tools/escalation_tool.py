# src/tools/escalation_tool.py

import json
import uuid
import datetime
import requests
from typing import Optional, Dict, Any, List
from langchain_core.tools import tool

from src.config.settings import ESCALATIONS_FILE, SLACK_WEBHOOK_URL
from src.agent.prompts_en import OFFICIAL_CONTACT_EMAIL, OFFICIAL_CONTACT_PHONE
from src.utils.logger import get_logger

logger = get_logger("EscalationTool")


def _ensure_escalations_file():
    """Ensures data directory and escalations.json exist."""
    if not ESCALATIONS_FILE.parent.exists():
        ESCALATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not ESCALATIONS_FILE.exists():
        with open(ESCALATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2, ensure_ascii=False)


def load_all_escalations() -> List[Dict[str, Any]]:
    """Loads all logged escalations from storage."""
    _ensure_escalations_file()
    try:
        with open(ESCALATIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Error reading {ESCALATIONS_FILE}: {e}. Returning empty list.")
        return []


def save_escalation_record(record: Dict[str, Any]) -> bool:
    """Appends a new escalation record to escalations.json."""
    _ensure_escalations_file()
    try:
        records = load_all_escalations()
        records.append(record)
        with open(ESCALATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Failed to save escalation record: {e}")
        return False


def notify_slack_escalation(escalation_record: Dict[str, Any]):
    """Sends an urgent Slack webhook alert for an escalated visitor conversation."""
    if not SLACK_WEBHOOK_URL:
        return

    try:
        urgency_emoji = "🚨" if escalation_record.get("urgency") in ["HIGH", "URGENT"] else "⚠️"
        payload = {
            "text": f"{urgency_emoji} *Human Escalation Alert!* [{escalation_record['escalation_id']}]",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"{urgency_emoji} Direct Human Escalation Requested"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Escalation ID:*\n{escalation_record['escalation_id']}"},
                        {"type": "mrkdwn", "text": f"*Urgency:*\n`{escalation_record.get('urgency', 'HIGH')}`"},
                        {"type": "mrkdwn", "text": f"*Reason:*\n{escalation_record.get('reason', 'N/A')}"},
                        {"type": "mrkdwn", "text": f"*Contact:*\n{escalation_record.get('user_contact', 'Not provided in chat')}"},
                    ]
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Conversation Summary:*\n{escalation_record.get('summary', 'Visitor requested human assistance.')}"}
                }
            ]
        }
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=6)
        if resp.status_code == 200:
            logger.info(f"Slack escalation notification sent for {escalation_record['escalation_id']}")
        else:
            logger.warning(f"Slack webhook returned status {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.warning(f"Failed to send Slack escalation webhook: {e}")


@tool
def escalate_to_human(
    reason: str,
    user_contact: str = "",
    urgency: str = "HIGH",
    summary: str = "",
    language: str = "en"
) -> str:
    """
    Alerts and escalates the conversation directly to the IT Cybx human team
    when a visitor requests to speak with a person, has complex custom requirements,
    requests a custom contract, or is unsatisfied with automated answers.

    Args:
        reason: Why the conversation is being escalated (e.g. 'Visitor wants custom pricing quote', 'Visitor requested direct human manager', 'Complex migration').
        user_contact: Optional email, phone, or name the user shared.
        urgency: Urgency level ('NORMAL', 'HIGH', 'URGENT').
        summary: Brief 1-2 sentence context of what the user is asking.
        language: 'en' for English, 'ar' for Arabic.

    Returns:
        Immediate confirmation and direct contact details for the user.
    """
    logger.info(f"Tool escalate_to_human called: reason='{reason}', contact='{user_contact}', urgency='{urgency}', lang='{language}'")
    is_ar = language.lower() == "ar"

    escalation_id = f"ESC-{uuid.uuid4().hex[:6].upper()}"
    timestamp = datetime.datetime.now().isoformat()

    escalation_record = {
        "escalation_id": escalation_id,
        "created_at": timestamp,
        "reason": reason.strip(),
        "user_contact": user_contact.strip() if user_contact else "Not provided",
        "urgency": urgency.upper(),
        "summary": summary.strip() if summary else reason.strip(),
        "language": "ar" if is_ar else "en",
        "status": "OPEN",
    }

    # Save to storage
    save_escalation_record(escalation_record)
    logger.info(f"Saved escalation {escalation_id}")

    # Dispatch Slack alert
    notify_slack_escalation(escalation_record)

    # Return localized response
    if is_ar:
        return (
            f"تم تحويل طلبك وتنبيه فريق العمل المختص في **IT Cybx** مباشرة!\n\n"
            f"• **رقم التذكرة:** {escalation_id}\n"
            f"• **البريد الإلكتروني المباشر:** {OFFICIAL_CONTACT_EMAIL}\n"
            f"• **الهاتف / واتساب المباشر:** {OFFICIAL_CONTACT_PHONE}\n\n"
            f"إذا كنت قد زوّدتنا ببيانات التواصل، سيتواصل معك أحد مسؤولي النمو لدينا في أقرب وقت. "
            f"كما يمكنك أيضاً التواصل معنا مباشرة عبر الهاتف أو البريد أعلاه."
        )
    else:
        return (
            f"Your request has been escalated directly to the **IT Cybx** team!\n\n"
            f"• **Ticket Reference:** {escalation_id}\n"
            f"• **Direct Email:** {OFFICIAL_CONTACT_EMAIL}\n"
            f"• **Direct Phone / WhatsApp:** {OFFICIAL_CONTACT_PHONE}\n\n"
            f"If you have provided your contact details, our team will reach out to you promptly. "
            f"You are also welcome to reach out to us directly via phone or email at any time."
        )


if __name__ == "__main__":
    test_res = escalate_to_human.invoke({
        "reason": "Visitor requested a custom enterprise migration quote for multiple Shopify Plus stores.",
        "user_contact": "omar@enterprise.sa",
        "urgency": "HIGH",
        "summary": "Brand has 4 stores with over $2M GMV needing full migration to Salla and Shopify Plus.",
        "language": "en"
    })
    print("\n=======================================================")
    print("          ESCALATION TO HUMAN TOOL TEST                ")
    print("=======================================================")
    print(test_res + "\n")
